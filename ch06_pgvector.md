# Chapter 6 — Vector Search: `pgvector` for Embeddings

> *"Full-text search finds documents that use your words. Vector search
> finds documents that share your meaning, whether or not they share a
> single word with you."*

---

## Background

Chapter 4 matched documents by shared vocabulary. Chapter 5 matched strings
by shared spelling. Neither technique can find a document about "the city's
dog park" when a resident searches "somewhere my pet can run off-leash" —
there isn't a misspelling to correct or a stemmed word in common; the two
phrases are simply *about the same thing*, expressed in unrelated words. No
amount of stemming, stopword tuning, or trigram threshold-adjusting closes
that gap, because all three earlier techniques operate on the text itself.
Closing it requires a representation of what the text *means*.

That representation is an **embedding**: a machine learning model reads a
piece of text and outputs a vector — literally an array of a few hundred
floating-point numbers — positioned in a high-dimensional space such that
texts with similar meaning end up as nearby points and unrelated texts end
up far apart. "Somewhere my pet can run off-leash" and "the city's dog park"
land close together in that space even though they share zero words. This
chapter never trains such a model — it uses a small, well-established,
freely available one (`all-MiniLM-L6-v2`) to turn text into 384-number
vectors, and PostgreSQL's `pgvector` extension to store, index, and search
them.

The two hard problems `pgvector` solves are storage (a native `vector` type,
instead of smuggling floats through a JSONB array or a comma-separated
text column) and **search at scale**. Finding the closest vector to a query
by brute force means comparing it against every single row — fine for the
thirty documents in Chapter 4's table, hopeless for a million-row photo
library. This chapter builds up to two different **approximate nearest
neighbor (ANN)** index types, IVFFlat and HNSW, that trade a small amount
of accuracy for a large amount of speed, and it's honest about exactly how
much accuracy each one actually costs you at its defaults, because the
answer is more surprising than most introductions let on.

---

## The Scenario

Two tables carry this chapter, and they get their vectors two very
different ways, on purpose.

`city_documents` — the council minutes, zoning ordinances, and public
notices from Chapter 4 — gets a real `embedding` column computed by
actually running `all-MiniLM-L6-v2` over each document's title and body.
These are genuine embeddings: semantic search over them in Exercise 5 finds
real conceptual matches, not a scripted demo.

`city_photos` is different, and says so in its own name: it's a synthetic
stand-in for a photo library's image embeddings (the kind a real vision
model like CLIP would produce for actual photographs), used purely to give
Exercises 3 and 4 a table large enough — 5,000 rows across ten categories —
for approximate indexing to be worth doing at all. Thirty rows, like
`city_documents` has, will never be large enough to make an ANN index pay
for itself; a sequential scan over thirty rows is already about as fast as
computation gets. There is no real photo behind any row in `city_photos` —
each one is a random point clustered around one of ten category "anchors"
in 384-dimensional space, which reproduces the *shape* of a real embedding
space (similar things cluster; different things don't) without needing a
single actual image.

| Table            | Vectors                                                                 | Used for |
|-------------------|--------------------------------------------------------------------------|----------|
| `city_documents`  | Real — `all-MiniLM-L6-v2` embeddings of each document's title + body    | Semantic search, hybrid search (Exercises 5-6) |
| `city_photos`     | Synthetic — 5,000 rows, 10 clustered categories, no real images         | ANN indexing at scale (Exercises 3-4) |

---

## Exercise Goals

By the end of this chapter you will be able to:

- Store embeddings in a native `vector` column and understand what the
  numbers in it actually represent.
- Compute exact nearest neighbors with `<->` (L2), `<#>` (negative inner
  product), and `<=>` (cosine distance), and know when the choice between
  them actually changes your results.
- Build an IVFFlat index, and correctly interpret its `lists` and `probes`
  parameters instead of trusting the defaults.
- Build an HNSW index, and make an informed build-time-vs-recall trade-off
  between it and IVFFlat instead of guessing.
- Run real semantic search: find documents by meaning even when they share
  no vocabulary with the query.
- Build hybrid search that blends a keyword score (`ts_rank`, from
  Chapter 4) with a semantic score into one ranking.

---

## Installation

This chapter has two dependencies, and they're independent of each other —
you need both, but you're installing two unrelated things for two unrelated
reasons.

### 1 — `pgvector`

```bash
sudo apt install -y postgresql-16-pgvector
```

Enable the extension. **Unlike `pg_trgm` in Chapter 5, `pgvector` 0.6.x is
not a "trusted" extension** — its control file doesn't set `trusted = true`,
so a regular database-owning role cannot enable it with a plain `CREATE
EXTENSION`. It has to be done once, by a superuser:

```bash
sudo -u postgres psql portsmith -c "CREATE EXTENSION vector;"
```

Confirm it's there:

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

```
 extversion
------------
 0.6.0
```

### 2 — `sentence-transformers`, CPU-only

The embedding model runs locally, in Python, via the `sentence-transformers`
library — no API key, no network calls at query time. It depends on
PyTorch, and installing PyTorch's default package pulls in a full NVIDIA
CUDA toolkit (several gigabytes) even on a machine with no GPU, which is
pure waste for embedding a few dozen short documents on CPU. Install the
CPU-only build explicitly, then `sentence-transformers` on top of it:

```bash
python3.12 -m venv .venv   # if you haven't already, from earlier chapters
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install sentence-transformers pgvector
```

> **Note:** this installs roughly 3GB into your virtual environment
> (PyTorch and its numerical dependencies are not small, even CPU-only) and
> the first time any script loads `all-MiniLM-L6-v2`, it downloads about
> 90MB of model weights from Hugging Face and caches them in
> `~/.cache/huggingface`. Every run after that is fully offline. If you see
> a `Warning: You are sending unauthenticated requests to the HF Hub` line
> the first time, that's expected and harmless — it's just Hugging Face
> reminding you that an account would raise your download rate limit.

---

## Loading the Data

### Prerequisites

Chapter 4's seed script must have been run first:

```bash
python data/ch04_seed.py
```

`ch04_seed.py` alone is **not** enough, though — this chapter's hybrid
search (Exercise 6) needs `city_documents.search_vector`, and that column
only gets created by hand-running Chapter 4's **Exercise 3** SQL; it is not
part of `ch04_seed.py`'s schema. (If you re-run `ch04_seed.py` after
already having done Exercise 3 — say, to reset the document data — it
drops `city_documents` and rebuilds it *without* `search_vector`, silently
undoing that exercise.) `ch06_seed.py` (below) checks for the column and
will stop with the exact fix if it's missing; if you'd rather do it now,
here it is verbatim from Chapter 4:

```sql
ALTER TABLE city_documents ADD COLUMN search_vector tsvector;

UPDATE city_documents
SET    search_vector = to_tsvector('english', title || ' ' || body);

CREATE OR REPLACE FUNCTION city_documents_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', NEW.title || ' ' || NEW.body);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_city_documents_search_vector
    BEFORE INSERT OR UPDATE OF title, body ON city_documents
    FOR EACH ROW
    EXECUTE FUNCTION city_documents_search_vector_update();

CREATE INDEX idx_city_documents_search_vector
    ON city_documents USING GIN (search_vector);
```

### Run the Chapter 6 seed

This adds the (initially empty) `embedding` column to `city_documents` and
creates and populates `city_photos`. It needs only `psycopg`, `numpy`, and
`pgvector` — not `sentence-transformers` — since `city_photos`'s vectors are
synthetic:

```bash
python data/ch06_seed.py
```

Expected output:

```
Connecting to: dbname=portsmith
Applying DDL …
Generating 5000 synthetic photo embeddings …
Done — 5000 rows in city_photos across 10 categories.
city_documents.embedding added but left NULL — run `python data/ch06_embed_documents.py` next.
```

### Compute real embeddings for `city_documents`

This is the step that actually loads and runs the model:

```bash
python data/ch06_embed_documents.py
```

Expected output:

```
Connecting to: dbname=portsmith
Loading all-MiniLM-L6-v2 (first run downloads ~90MB of model weights) …
Embedding 30 documents …
Done — 30 rows in city_documents now have an embedding.
```

### Verify the load

Open `psql portsmith` and run these checks.

**Check 1 — `city_photos` structure:**

```sql
\d city_photos
```

```
                                  Table "public.city_photos"
    Column     |    Type     | Collation | Nullable |                 Default
---------------+-------------+-----------+----------+-----------------------------------------
 id            | integer     |           | not null | nextval('city_photos_id_seq'::regclass)
 category      | text        |           | not null |
 neighbourhood | text        |           | not null |
 caption       | text        |           | not null |
 embedding     | vector(384) |           | not null |
Indexes:
    "city_photos_pkey" PRIMARY KEY, btree (id)
```

**Check 2 — 500 photos per category:**

```sql
SELECT category, COUNT(*) FROM city_photos GROUP BY category ORDER BY category;
```

```
          category           | count
-----------------------------+-------
 community_event             |   500
 harbour_waterfront          |   500
 historic_architecture       |   500
 industrial_dock             |   500
 infrastructure_construction |   500
 municipal_building          |   500
 public_park                 |   500
 residential_street          |   500
 street_market               |   500
 wildlife_nature             |   500
(10 rows)
```

**Check 3 — every `city_documents` row has an embedding:**

```sql
SELECT COUNT(*) AS total, COUNT(embedding) AS with_embedding FROM city_documents;
```

```
 total | with_embedding
-------+-----------------
    30 |              30
```

If all three match, proceed to the exercises.

---

## Exercises

---

### Exercise 1 — The `vector` Type

**1.1 — Literals and dimensions**

A `vector` literal is a bracketed list of numbers:

```sql
SELECT '[1,2,3]'::vector;
```

```
 vector
---------
 [1,2,3]
```

A `vector(384)` column, like `city_documents.embedding`, enforces its
dimension count at write time — every row's vector must have exactly 384
numbers. There is no meaningful way to compare a 384-dimensional embedding
to a 3-dimensional one, so PostgreSQL simply won't let a mismatched value
in:

```sql
SELECT '[1,2,3]'::vector(384);
```

```
ERROR:  expected 384 dimensions, not 3
```

**1.2 — What's actually in the column**

`city_documents.embedding` isn't hand-written — it came from
`ch06_embed_documents.py` calling `all-MiniLM-L6-v2` on each document's
title and body. Look at a real one:

```sql
SELECT id, title, embedding FROM city_documents WHERE id = 1;
```

The `embedding` value prints as 384 comma-separated floating-point numbers
between roughly -1 and 1 — not something a human reads directly, but
exactly what every operator and index in this chapter operates on. What
those particular 384 numbers *mean* isn't individually interpretable (no
single dimension corresponds to a concept like "is about harbours"); what
matters is only their *position relative to other documents' vectors*,
which is what the distance operators in Exercise 2 measure.

---

### Exercise 2 — Exact Nearest Neighbors: `<->`, `<#>`, `<=>`

`pgvector` gives you three distance operators. They agree more often than
you'd expect, and the case where they disagree is worth understanding
before it surprises you in production.

**2.1 — Three tiny vectors, three operators**

```sql
SELECT '[1,0,0]'::vector <-> '[0,1,0]'::vector AS l2_distance;
```

```
     l2_distance
--------------------
 1.4142135623730951
```

`<->` is **Euclidean (L2) distance** — straight-line distance between the
two points, exactly like distance in ordinary geometry. Two orthogonal unit
vectors are `√2` apart.

```sql
SELECT '[1,0,0]'::vector <#> '[0,1,0]'::vector AS neg_inner_product;
```

```
 neg_inner_product
--------------------
                 -0
```

`<#>` is the **negative inner product** — the dot product of the two
vectors, negated (pgvector negates it so that, consistent with the other
two operators, *smaller means closer*). Orthogonal vectors have a dot
product of zero.

```sql
SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector AS cosine_distance;
```

```
 cosine_distance
------------------
                1
```

`<=>` is **cosine distance** (`1 - cosine similarity`) — the angle between
the two vectors, completely ignoring their length. Orthogonal vectors have
maximum cosine distance, `1`.

**2.2 — Where they disagree: magnitude**

The three operators can rank the *same* pair of candidates in a *different*
order the moment the vectors involved aren't the same length. Compare a
query vector against two candidates — one that points in exactly the same
direction but is twice as long, and one that points in a slightly different
direction but is almost the same length:

```sql
SELECT
  '[1,0]'::vector <-> '[2,0]'::vector   AS l2_to_a,
  '[1,0]'::vector <-> '[1,0.5]'::vector AS l2_to_b,
  round(('[1,0]'::vector <=> '[2,0]'::vector)::numeric, 4)   AS cos_to_a,
  round(('[1,0]'::vector <=> '[1,0.5]'::vector)::numeric, 4) AS cos_to_b;
```

```
 l2_to_a | l2_to_b | cos_to_a | cos_to_b
---------+---------+----------+----------
       1 |     0.5 |   0.0000 |   0.1056
```

**The ranking flips.** By `<->` (L2), candidate B (`[1,0.5]`, distance
`0.5`) is closer than candidate A (`[2,0]`, distance `1`). By `<=>`
(cosine), it's the reverse — A is distance `0` (identical direction) while
B is `0.1056` away. Neither operator is "wrong"; they're answering
different questions. L2 asks "how far apart are these points." Cosine asks
"how similarly are these vectors oriented, regardless of scale."

**2.3 — Why this chapter normalizes, and what that buys you**

`ch06_embed_documents.py` calls `model.encode(texts,
normalize_embeddings=True)` — every stored embedding is scaled to unit
length before it's written. Once every vector in a comparison has the same
length, the magnitude difference that caused Exercise 2.2's disagreement
simply can't occur, and all three operators produce the *same ranking*
(just on different numeric scales). Embedding the query "waterfront
redevelopment funding" (Exercise 5 shows how) and checking the top 3
`city_documents` rows by each operator confirms it:

| | `<->` (L2) | `<#>` (neg. inner product) | `<=>` (cosine) |
|---|---|---|---|
| Rank 1 | doc 1 — `0.8605` | doc 1 — `-0.6298` | doc 1 — `0.3702` |
| Rank 2 | doc 22 — `1.0546` | doc 22 — `-0.4439` | doc 22 — `0.5561` |
| Rank 3 | doc 5 — `1.0646` | doc 5 — `-0.4333` | doc 5 — `0.5667` |

Same three documents, same order, every time — only the numbers' scale
differs between columns. The practical rule: **normalize your embeddings,
and pick whichever operator has an index you can build** — for normalized
vectors it stops being a search-quality decision and becomes a performance
one, covered next.

---

### Exercise 3 — IVFFlat: Approximate Search with `lists` and `probes`

**3.1 — Exact search doesn't scale**

`city_photos` has 5,000 rows — small by real standards, but already enough
to feel the cost of brute-force search. Find the 10 nearest neighbors of
photo `id = 1` by comparing it against every other row:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, category, embedding <-> (SELECT embedding FROM city_photos WHERE id = 1) AS dist
FROM   city_photos
WHERE  id != 1
ORDER  BY embedding <-> (SELECT embedding FROM city_photos WHERE id = 1)
LIMIT  10;
```

```
                                                     QUERY PLAN
---------------------------------------------------------------------------------------------------------------------
 Limit  (cost=1439.32..1439.35 rows=10 width=30) (actual time=4.164..4.167 rows=10 loops=1)
   ->  Sort  (cost=1431.02..1443.52 rows=4999 width=30) (actual time=4.163..4.164 rows=10 loops=1)
         Sort Key: ((city_photos.embedding <-> $0))
         Sort Method: top-N heapsort  Memory: 26kB
         ->  Seq Scan on city_photos  (cost=0.00..1323.00 rows=4999 width=30) (actual time=0.024..3.381 rows=4999 loops=1)
```

Every one of the 4,999 other rows gets its distance computed and sorted —
about 4.6ms here. That cost grows linearly with table size; at real photo
library scale (millions of rows) it stops being viable.

**3.2 — Build the index**

```sql
CREATE INDEX idx_city_photos_ivfflat
    ON city_photos
    USING ivfflat (embedding vector_l2_ops)
    WITH (lists = 50);
```

```
CREATE INDEX
Time: 152.129 ms
```

`lists = 50` partitions the 5,000 vectors into 50 clusters (via k-means at
index-build time) and stores each vector under its nearest cluster
centroid. A rule of thumb from the pgvector docs: `lists ≈ rows / 1000` for
up to roughly a million rows.

**3.3 — The planner picks it up on its own**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, category, embedding <-> (SELECT embedding FROM city_photos WHERE id = 1) AS dist
FROM   city_photos
WHERE  id != 1
ORDER  BY embedding <-> (SELECT embedding FROM city_photos WHERE id = 1)
LIMIT  10;
```

```
                                                             QUERY PLAN
-------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=61.55..62.35 rows=10 width=30) (actual time=0.145..0.168 rows=10 loops=1)
   ->  Index Scan using idx_city_photos_ivfflat on city_photos  (cost=53.25..455.00 rows=4999 width=30) (actual time=0.145..0.166 rows=10 loops=1)
         Order By: (embedding <-> $0)
```

No `enable_seqscan = off` trick needed this time, unlike the small tables
in earlier chapters — at 5,000 rows the planner's own cost estimate already
favors the index: **4.6ms down to about 0.2ms.**

**3.4 — The catch: default `probes` gives up a lot of accuracy**

An IVFFlat search only examines the clusters nearest the query vector, not
all 50 — controlled by `ivfflat.probes`, which **defaults to 1**. Compare
the approximate top-10 against the true exact top-10:

```sql
-- Exact (force a sequential scan to get true ground truth):
SET enable_indexscan = off;
SELECT array_agg(id) FROM (
    SELECT id FROM city_photos WHERE id != 1
    ORDER BY embedding <-> (SELECT embedding FROM city_photos WHERE id = 1) LIMIT 10
) t;
```

```
                 array_agg
--------------------------------------------
 {146,357,485,468,500,261,384,397,185,226}
```

```sql
-- Approximate, default probes = 1:
RESET enable_indexscan;
SELECT array_agg(id) FROM (
    SELECT id FROM city_photos WHERE id != 1
    ORDER BY embedding <-> (SELECT embedding FROM city_photos WHERE id = 1) LIMIT 10
) t;
```

```
                 array_agg
--------------------------------------------
 {485,261,185,226,385,22,274,433,56,327}
```

Only **4 of the 10** results match (`485`, `261`, `185`, `226`) — **40%
recall**, at the default setting, on a real query. This is not a contrived
worst case; it's what `ivfflat.probes = 1` actually does: it searches only
the single cluster closest to the query and simply never looks at the
other 49, even though some of the true nearest neighbors live in a
different cluster.

> **A note on reproducing these exact numbers:** IVFFlat's clustering step
> uses k-means with a random initialization at *index build* time — even
> against `city_photos`'s fixed, seeded synthetic data, rebuilding the same
> `CREATE INDEX ... USING ivfflat` statement can shift which photos land in
> which of the 50 clusters, and therefore which specific IDs and exact
> recall percentage `probes = 1` produces. Rerunning this exercise on your
> own machine will very likely show different IDs and a different
> percentage than the ones printed here. The pattern that reproduces
> reliably is the *shape*: `probes = 1` is measurably, often substantially,
> incomplete.

**3.5 — Raise `probes`, watch recall recover**

```sql
SET ivfflat.probes = 2;
```

```
                 array_agg
--------------------------------------------
 {146,357,485,468,500,261,384,397,185,226}
```

At `probes = 2` the result already matches the exact set exactly —
**100% recall** on this query. Timing at a slightly more conservative
`probes = 5`, and at `probes = 50` (every list — the most exhaustive an
IVFFlat search can be):

| `probes` | Recall (this query) | Query time |
|----------|---------------------|------------|
| 1 (default) | 40% | ~0.4ms |
| 5           | 100% | ~0.6ms |
| 50 (all lists) | 100% | ~0.6ms |

Timings vary run to run more than the recall figures do (expect noise in
the tenths of a millisecond on a table this size) — the shape that
matters is that `probes = 1` is consistently fastest *and* the least
reliable, while anything from `probes = 5` up delivers full recall on
this query without a further, proportional cost from probing still more
lists; the IVFFlat index structure keeps even an "examine every list"
search meaningfully faster than the 4.6ms plain sequential scan from
Exercise 3.1. Reset before continuing:

```sql
SET ivfflat.probes = 1;
```

Two probes happened to be enough for this particular query; it isn't a
guarantee for every query, which is why a small safety margin (a
starting point of `probes ≈ √lists`, so `√50 ≈ 7`) is the honest
recommendation rather than the bare minimum that worked once. The overall
lesson: **IVFFlat's out-of-the-box defaults are fast and unreliable at the
same time** — `lists` and `probes` are not optional tuning, they're the
whole feature.

---

### Exercise 4 — HNSW: A Different Trade-off

**4.1 — Build it, and time the build**

```sql
CREATE INDEX idx_city_photos_hnsw
    ON city_photos
    USING hnsw (embedding vector_l2_ops);
```

```
CREATE INDEX
Time: 513.963 ms
```

Compare against IVFFlat's build time from Exercise 3.2: **152ms.** HNSW
(Hierarchical Navigable Small World) builds a multi-layer graph structure
connecting each vector to its approximate neighbors, which costs roughly
**3x longer to build** than IVFFlat's k-means clustering, on this table.

**4.2 — Recall at HNSW's default settings**

Drop (or temporarily disable) the IVFFlat index so the planner has no
choice but to use HNSW, then repeat the exact same top-10 query from
Exercise 3.4:

```sql
BEGIN;
DROP INDEX idx_city_photos_ivfflat;

SELECT array_agg(id) FROM (
    SELECT id FROM city_photos WHERE id != 1
    ORDER BY embedding <-> (SELECT embedding FROM city_photos WHERE id = 1) LIMIT 10
) t;

ROLLBACK;  -- put idx_city_photos_ivfflat back
```

```
                 array_agg
--------------------------------------------
 {146,357,485,468,500,261,384,397,185,226}
```

**Exact match with the true top-10 — 100% recall, at HNSW's default
settings**, no tuning required. Query time for this was about 0.63ms.
Repeating the comparison against a second, independent query point
(`id = 1001`, a `public_park` photo) confirms it isn't a fluke: HNSW again
returned the exact top-10, while IVFFlat at default `probes = 1` again
recovered only 3 of 10 (30% recall — as Exercise 3.4 noted, the exact
percentage shifts between index rebuilds; what doesn't shift is that it's
consistently well short of complete). HNSW's default, across every test in
this chapter, has not missed a single true neighbor.

**4.3 — The trade-off, stated plainly**

| | IVFFlat | HNSW |
|---|---------|------|
| Build time (5,000 rows) | 152ms | 514ms (~3x) |
| Recall at defaults | 30-40% in this chapter's tests, varies by build (needs `probes` tuned up) | ~100% (no tuning needed) |
| Query time (well-tuned) | Comparable | Comparable |
| Tuning burden | On you, every session (`probes` is a session-level `SET`) | Minimal |

This matches the general guidance in the pgvector documentation: **HNSW is
the better default choice for most workloads** — better recall out of the
box, no per-session parameter to remember to set. IVFFlat's advantages are
real but narrower: faster to build (relevant if you rebuild the index
often, e.g. after large bulk loads) and somewhat lower memory overhead at
very large scale. Choose IVFFlat deliberately for those reasons, not by
default.

---

### Exercise 5 — Semantic Search: Finding Meaning, Not Words

**5.1 — A query with no vocabulary overlap**

`data/ch06_semantic_search.py` embeds a query string with the same model
used to build the column, and searches `city_documents` by cosine
similarity:

```bash
python data/ch06_semantic_search.py "stray dogs and pet-friendly spaces"
```

```
  id      sim  title
   6   0.4447  Council Minutes — Riverside Dog Park Funding
  24   0.3927  Public Notice — Riverside Dog Park Ribbon-Cutting Event
  16   0.2683  Zoning Ordinance — Riverside Short-Term Rental Restrictions
  ...
```

Not one word of the query — "stray," "dogs," "pet-friendly," "spaces" —
appears in document 6's title, and full-text search (Chapter 4) would
return zero rows for it; there's no shared lexeme to match on, misspelled
or otherwise, so Chapter 5's trigram matching wouldn't help either. The
embedding model has no notion of exact words at all — it read "the city's
dog park" and "somewhere my pet can run off-leash" as *about the same
thing*, which is precisely the gap described in this chapter's Background.

**5.2 — A stronger example**

```bash
python data/ch06_semantic_search.py "waterfront redevelopment funding"
```

```
  id      sim  title
   1   0.6298  Council Minutes — Harbour District Waterfront Renovation Budget
  22   0.4439  Public Notice — Public Hearing on Harbour District Waterfront Rezoning
   5   0.4333  Council Minutes — Riverside Road Resurfacing Program
  12   0.4207  Zoning Ordinance — Harbour District Waterfront Height Variance
   9   0.4101  Council Minutes — Canal Road Bike Lane Expansion
  ...
```

**5.3 — Reading the gap, not just the ranking**

Look at the jump between rank 1 (`0.6298`) and rank 2 (`0.4439`) — a much
bigger drop than between ranks 2 through 5. That gap is meaningful: it
says document 1 isn't merely the *best available* match, it's a
*genuinely strong* one, while the rest are progressively looser
associations. Semantic search has a property full-text search doesn't:
**it never returns zero results.** Every document has *some* cosine
similarity to any query — the model will confidently rank all thirty
documents even for a nonsense query, it just won't find any of them close.
A real application needs a similarity-score cutoff (or a "confidence" gap
check like this one) to distinguish "found it" from "here's our least-bad
guess," a problem keyword search's honest zero-rows sidesteps entirely.

---

### Exercise 6 — Hybrid Search: Blending Keyword and Semantic Signals

Semantic search and keyword search fail differently. Semantic search
misses exact terms that matter — a specific ordinance number, a street
name — treating them as just more words to average into a general
impression of meaning. Keyword search misses paraphrases entirely, as
Exercise 5 just showed. Hybrid search runs both and blends the scores.

**6.1 — Keyword-only ranking**

```sql
SELECT id, title, round(ts_rank(search_vector, plainto_tsquery('english','bike lane'))::numeric,4) AS kw_rank
FROM   city_documents
WHERE  search_vector @@ plainto_tsquery('english','bike lane')
ORDER  BY kw_rank DESC;
```

```
 id |                               title                                | kw_rank
----+----------------------------------------------------------------------+---------
  9 | Council Minutes — Canal Road Bike Lane Expansion                   |  0.2928
 28 | Public Notice — Canal Road Bike Lane Construction Schedule         |  0.1960
 30 | Public Notice — Annual Fireworks Display and Street Closures       |  0.1759
  5 | Council Minutes — Riverside Road Resurfacing Program               |  0.0992
 15 | Zoning Ordinance — Reduced Parking Minimums Near Transit Corridors |  0.0991
```

**6.2 — Semantic-only ranking, same query**

```bash
python data/ch06_semantic_search.py "bike lane" --top 8
```

```
  id      sim  title
   9   0.5513  Council Minutes — Canal Road Bike Lane Expansion
  28   0.4433  Public Notice — Canal Road Bike Lane Construction Schedule
  15   0.4117  Zoning Ordinance — Reduced Parking Minimums Near Transit Corridors
   5   0.3965  Council Minutes — Riverside Road Resurfacing Program
  21   0.2754  Public Notice — Bay Street Water Main Repair Road Closure
   6   0.2688  Council Minutes — Riverside Dog Park Funding
  30   0.2653  Public Notice — Annual Fireworks Display and Street Closures
  10   0.2359  Council Minutes — Special Session on Flood Mitigation Infrastructure
```

Both agree on the top 2 (documents 9 and 28 — a real, strong signal either
way finds them). They disagree further down: document 30 ranks **3rd** by
keyword (it happens to use the phrase "biking along the Canal Road bike
lane" once, in passing) but only **7th** by semantic similarity, while
document 15 ranks **5th** by keyword but **3rd** semantically (it's
substantively about bike-lane-adjacent parking policy, using different
phrasing throughout).

**6.3 — Blend both into one score**

```bash
python data/ch06_semantic_search.py "bike lane" --hybrid --top 8
```

```
  id       kw      sem   hybrid  title
   9   0.2928   0.5513   0.4479  Council Minutes — Canal Road Bike Lane Expansion
  28   0.1960   0.4433   0.3444  Public Notice — Canal Road Bike Lane Construction Schedule
  15   0.0991   0.4117   0.2867  Zoning Ordinance — Reduced Parking Minimums Near Transit Corridors
   5   0.0992   0.3965   0.2776  Council Minutes — Riverside Road Resurfacing Program
  30   0.1759   0.2653   0.2295  Public Notice — Annual Fireworks Display and Street Closures
  21   0.0000   0.2754   0.1652  Public Notice — Bay Street Water Main Repair Road Closure
   6   0.0000   0.2688   0.1613  Council Minutes — Riverside Dog Park Funding
  10   0.0000   0.2359   0.1415  Council Minutes — Special Session on Flood Mitigation Infrastructure
```

The underlying SQL (`HYBRID_SQL` in `ch06_semantic_search.py`) is a `LEFT
JOIN` between a keyword-matched candidate set and a semantic top-10
candidate set, so documents 21, 6, and 10 — never matched by the keyword
query at all (`kw = 0.0000`) — still appear, carried in purely by semantic
similarity:

```sql
hybrid_score = 0.4 * COALESCE(kw_score, 0) + 0.6 * COALESCE(sem_score, 0)
```

Document 15 moves from 5th (keyword) up to 3rd (hybrid); document 30 moves
from 3rd (keyword) down to 5th (hybrid) — the blend genuinely changes the
ranking, not just the score.

**6.4 — The honest caveat about the weights**

`0.4` and `0.6` here are fixed constants chosen because `ts_rank` and
cosine similarity happen to land in roughly comparable numeric ranges on
*this* dataset — they are not principled, and they are not portable to a
different corpus or a different embedding model without re-checking that
assumption. A production hybrid-search system typically normalizes each
signal (min-max or z-score, over the actual candidate set returned) before
blending, rather than trusting that two arbitrary scoring functions happen
to land in the same numeric neighborhood. Treat the weights here as a
teaching simplification, not a formula to copy into production untested.

---

## Summary — What You Should Now Know

| Tool | What it does |
|------|-------------|
| `vector(N)` | A fixed-dimension floating-point array column type; enforces `N` at write time |
| `<->` | L2 (Euclidean) distance — straight-line distance between points |
| `<#>` | Negative inner product — dot product, negated so smaller means closer |
| `<=>` | Cosine distance — angle between vectors, ignoring magnitude |
| `normalize_embeddings=True` | Makes all three operators agree on ranking; without it, they can disagree |
| `USING ivfflat (col vector_l2_ops) WITH (lists = N)` | Clusters vectors into `N` buckets; fast to build, needs `probes` tuned up from its default to get usable recall |
| `SET ivfflat.probes = N` | How many clusters an IVFFlat search actually examines — defaults to `1`, often too low |
| `USING hnsw (col vector_l2_ops)` | Graph-based ANN index; ~3x slower to build than IVFFlat here, but near-exact recall by default |
| `ts_rank(...) + (1 - cosine_distance)` weighted blend | Hybrid search — keyword precision plus semantic recall in one ranking |

**The key design insight** from this chapter is that "approximate" in
"approximate nearest neighbor" is not a rounding error — at IVFFlat's
default settings, this chapter repeatedly measured 30-40% recall on real
queries, which means 6-7 of the top 10 *true* nearest neighbors were
silently missing from the results, with no error, no warning, nothing to
indicate anything was wrong. Every ANN index trades recall for speed on a
dial you control (`probes`, `ef_search`); the failure mode to avoid is not
knowing where that dial is set.

The `city_documents` table's `embedding` column is reused in Chapter 10
(PostgREST), which exposes the semantic search query from Exercise 5 as a
public RPC endpoint alongside the fuzzy "did you mean?" search from
Chapter 5.

---

*Going further: this chapter used `all-MiniLM-L6-v2` (384 dimensions)
because it's small, fast on CPU, and good enough to teach with — production
systems often use larger models (OpenAI's `text-embedding-3-small` at 1536
dimensions, or similar) for better semantic quality, at proportionally
higher storage and compute cost per vector. For tables much larger than
`city_photos`'s 5,000 rows, revisit `lists` (scale roughly with row count)
and consider `hnsw`'s `m` and `ef_construction` build-time parameters,
which trade index size and build time for recall the same way `probes`
trades query time for it. And if your embeddings change meaning over time
— a newer, better model version — remember that a `vector` column has no
built-in versioning; re-embedding the whole table and rebuilding the index
is a full migration, not an in-place update.*

---
---

## Bonus Section — Build a Local RAG System

*This section is optional and sits outside the numbered exercises — nothing
later in the book depends on it. It exists because semantic search
(Exercise 5) is one step short of the thing most people actually mean when
they say "AI search": a system that doesn't just return matching documents,
but reads them and answers the question directly. That's **Retrieval-
Augmented Generation (RAG)**, and you already built the hard half of it —
retrieval — in Exercises 1 through 5. This section adds the other half.*

### What RAG actually is

Every large language model has a knowledge cutoff and no idea what's in
your `city_documents` table. Ask one directly "what are the rules for
Portsmith's dog park?" and it will either say it doesn't know or, worse,
confidently invent something plausible-sounding and wrong — a
**hallucination**. RAG sidesteps this without retraining or fine-tuning
anything: before asking the model the question, retrieve the most relevant
real text from your own database and paste it directly into the prompt,
instructing the model to answer *only* from that text. The model isn't
recalling facts from training anymore; it's reading comprehension over
text you handed it seconds ago.

This means RAG is two independent systems wired together, and it's worth
keeping them mentally separate:

1. **Retrieval** — PostgreSQL, `pgvector`, and everything from Exercises 1-5
   of this chapter. Given a question, find the most relevant chunks of text.
2. **Generation** — a large language model that turns "here are some
   relevant facts, here is a question" into a fluent, direct answer.

Nothing about retrieval changes when you add generation on top of it — the
`<=>` cosine-distance query from Exercise 5 is exactly what runs here too.
What's new is chunking (documents are usually too long and too
topically mixed to embed as a single vector) and the LLM call itself,
which this section runs locally through **Ollama** rather than a paid API,
for the same reason Chapter 6 as a whole runs its embedding model locally:
no API key, no per-query cost, nothing leaves your machine.

### Installation — Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

This installs Ollama as a systemd service listening on `localhost:11434`.
Pull a chat model — this section uses `llama3.1:8b` (about 4.9GB):

```bash
ollama pull llama3.1:8b
```

If disk space or RAM is tight, `ollama pull phi` gets you a much smaller
(~1.6GB) model at a real quality cost; every example below works with
either, since the model name is a plain argument to the RAG script, not
something hardcoded.

> **Note:** the *first* request to any given model incurs a one-time load
> delay (10-15 seconds isn't unusual) while Ollama loads its weights into
> memory. Every request after that, to the same model, is fast — Ollama
> keeps recently used models resident for a while. Don't judge a model's
> real latency by its very first response.

### Ingest: chunk and embed a directory of documents

`data/rag_docs/` contains four new, longer, informational documents — a
business licensing guide, a parks and recreation guide, a utilities guide,
and a newcomer's guide — distinct from `city_documents`'s formal council
records, written in the plain-prose register an actual city help-desk
handout would use. `ch06_rag_ingest.py` splits each file into overlapping
word-count chunks, embeds every chunk with `all-MiniLM-L6-v2` (the same
model used everywhere else in this chapter — retrieval only works if the
same model embeds both the documents and the questions), and loads them
into a table you name on the command line:

```bash
python data/ch06_rag_ingest.py data/rag_docs --table portsmith_rag --recreate
```

```
Connecting to: dbname=portsmith
Loading all-MiniLM-L6-v2 …
  getting_a_business_license.txt: 4 chunks
  newcomer_guide.txt: 4 chunks
  parks_and_recreation.txt: 4 chunks
  utilities_and_public_works.txt: 4 chunks
Done — 16 chunks from 4 files loaded into 'portsmith_rag'.
```

Each ~700-word document became 4 chunks of 180 words with a 40-word
overlap between consecutive chunks (both configurable via `--chunk-size`
and `--chunk-overlap`). The overlap matters: without it, a sentence that
happens to fall right at a chunk boundary gets split across two chunks,
and neither half alone may retrieve well for a question about it.

The table it creates is deliberately the same generic shape regardless of
what you point it at:

```sql
\d portsmith_rag
```

```
                                 Table "public.portsmith_rag"
   Column    |    Type     | Collation | Nullable |                  Default
-------------+-------------+-----------+----------+-------------------------------------------
 id          | integer     |           | not null | nextval('portsmith_rag_id_seq'::regclass)
 source      | text        |           | not null |
 chunk_index | integer     |           | not null |
 content     | text        |           | not null |
 embedding   | vector(384) |           | not null |
Indexes:
    "portsmith_rag_pkey" PRIMARY KEY, btree (id)
    "idx_portsmith_rag_embedding" hnsw (embedding vector_cosine_ops)
```

`--table` is a plain identifier you choose — point the same script at a
different directory with `--table` set to something else, and you have a
second, independent knowledge base in the same database. Run it against
your own notes, a project's documentation, anything in `.txt` or `.md`
files.

> **Why the table name is validated, not just interpolated:** `--table`
> comes from the command line and flows into `CREATE TABLE`, `INSERT`, and
> `CREATE INDEX` statements. SQL identifiers (table names) can't be passed
> as query parameters the way values can — `cur.execute("... WHERE id =
> %s", (table_name,))` only works for *values*. `ch06_rag_ingest.py` and
> `ch06_rag_chat.py` both reject anything that isn't a plain lowercase
> identifier before it touches SQL, and use `psycopg.sql.Identifier` to
> quote it correctly rather than dropping it into an f-string. For a
> script you run yourself against your own database this is a small
> concern; the habit is worth keeping anyway, because the same shortcut in
> a script that takes a table name from a web form is a real SQL injection
> hole.

### Ask a question

`ch06_rag_chat.py` takes three required arguments — `model`, `table`,
`question`, in that order — plus `--host` and `--port` for Ollama (both
default to `localhost` and `11434`, so you only need them if Ollama runs
elsewhere):

```bash
python data/ch06_rag_chat.py llama3.1:8b portsmith_rag \
    "How do I get a business license in Portsmith?" --show-context
```

```
--- retrieved context ---
[getting_a_business_license.txt#0  dist=0.2743] Getting a Business License in Portsmith Anyone opening a business within city limits needs a busines...
[getting_a_business_license.txt#3  dist=0.5796] to change their registered category — a retail shop adding a small cafe counter, for example — need ...
[getting_a_business_license.txt#2  dist=0.6149] scratch rather than simply renewing, which means a new round of inspections for categories that requ...
[newcomer_guide.txt#0  dist=0.6176] A Newcomer's Guide to Portsmith Welcome to Portsmith. This guide covers the basics every new residen...

To get a business license in Portsmith, you need to start online through the city's permitting portal, where you choose a business category since it determines which inspections and follow-up permits apply. Most applications are processed within two to three weeks, but those involving food service or alcohol take longer because they require scheduled in-person inspections.
```

`--show-context` prints exactly what got retrieved before the model ever
saw the question — the same top-K cosine-distance query from Exercise 5,
just with `content` instead of `title` as the payload. The answer isn't
copied from any single chunk; it's the model synthesizing across the top
few, which is the actual value RAG adds over raw semantic search: Exercise
5 would have handed a person four ranked chunks to read themselves, this
hands them one sentence that already did the reading.

> **Reproducibility, honestly:** the retrieved chunks and their `dist`
> values above are fully deterministic — rerun the exact query and you'll
> get the exact same four chunks in the exact same order, because
> embedding and cosine distance are pure math. The generated *answer*
> is not — Ollama samples from the model's output distribution, so
> wording will differ run to run (sometimes prose, sometimes a bulleted
> list) even against identical context. That's a property of the
> generation half of RAG, not the retrieval half; don't expect to
> reproduce this exact paragraph verbatim.

### What happens when the answer isn't in the documents

This is the case that actually matters for trusting a RAG system — ask
something the ingested documents have no way of answering:

```bash
python data/ch06_rag_chat.py llama3.1:8b portsmith_rag \
    "What is the capital of France?" --show-context
```

```
--- retrieved context ---
[newcomer_guide.txt#1  dist=0.9228] river on the city's western edge and is primarily residential, with the new dog park, several parks ...
[utilities_and_public_works.txt#1  dist=0.9272] requires temporarily shutting off service to a section of a neighbourhood, Public Works issues a boi...
[newcomer_guide.txt#0  dist=0.9361] A Newcomer's Guide to Portsmith Welcome to Portsmith. This guide covers the basics every new residen...
[newcomer_guide.txt#2  dist=0.9475] alike. Noise ordinance enforcement is more actively watched here than in other neighbourhoods given ...

I don't know. The context only provides information about the city of Portsmith, its neighbourhoods, and various services offered by the city, but does not mention the capital of France.
```

Two things to notice. First, retrieval **still returned four chunks** —
exactly as Exercise 5 described, cosine similarity search never returns
"no results," it returns the *least bad* matches available, and here
they're genuinely irrelevant. Second, look at the distances: `0.92-0.95`,
versus `0.27-0.61` for the business license question. That gap is the
signal a production system would actually act on — this script's prompt
template happens to lean on the model's own judgment to say "I don't
know," but a more defensive design would check the top distance against a
threshold *before* even calling the LLM, and skip generation entirely for
a question this poorly matched. Relying on the model to notice the
context is irrelevant works here because `llama3.1:8b` is reasonably
well-behaved about it — it is not a guarantee every model or every prompt
will get right, and it's the single biggest reliability risk in any RAG
system: nothing stops a language model from answering confidently from
weak or irrelevant context if the prompt doesn't insist otherwise.

### The prompt: the actual glue between the two systems

`ask_ollama()` in `ch06_rag_chat.py` sends the model one plain-text prompt
via Ollama's `/api/generate` endpoint — no special "RAG mode" exists in
Ollama or in the model itself, it's just a string:

```
You are a help-desk assistant for the city of Portsmith. Answer the question using ONLY the context below. If the context doesn't contain the answer, say you don't know rather than guessing.

Context:
(getting_a_business_license.txt) Getting a Business License in Portsmith Anyone opening a business ...
(getting_a_business_license.txt) to change their registered category — a retail shop adding a small ...
...

Question: How do I get a business license in Portsmith?

Answer:
```

This is the entire mechanism. There is no fine-tuning, no special API,
nothing model-specific — "retrieval-augmented generation" is a prompt
template plus a database query, which is exactly why it was worth showing
you the whole thing at this level rather than reaching for a framework.

---

*Going further: this section's retrieval is intentionally the simplest
version that works — top-K by raw cosine distance, no re-ranking, no
distance-threshold cutoff before generation, no limit on how many tokens
of context get sent to the model regardless of length. Production RAG
systems typically add a **re-ranking** step (retrieve a wider candidate
set cheaply, then re-score the top candidates with a slower, more accurate
model before picking the final context), **hybrid retrieval** (blend
`ts_rank` back in, exactly as Exercise 6 did, since keyword precision and
semantic recall are just as complementary here as they were there), and
explicit **citations** in the generated answer so a user can verify a
claim against the source chunk rather than trusting the model's summary
outright. None of that changes the shape of what you built here — it's
still retrieval, then generation, with more care taken at each step.*
