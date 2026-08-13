# Appendix D — Index Decision Guide

A decision tree for which index type to reach for, built from the real
index choices this book actually made — and, in one important case
(Chapter 20), a real index choice that turned out to be wrong until
measured.

## The decision tree

**1. Is the column being matched with plain equality or a range
(`=`, `<`, `BETWEEN`, `ORDER BY`)?**
→ **B-tree** — PostgreSQL's default, and correct by default for most
columns. Every primary key and foreign key in this book uses one
without a second thought. The one real trap: an **implicit type cast**
silently defeats it. Chapter 20 Exercise 3 found `businesses.id = 5`
(integer column, integer literal) using `Index Cond` correctly, while
`businesses.id = 5::numeric` used `Filter` instead — a full scan
comparing every row, invisible unless you actually read the plan.

**2. Is the column a `JSONB` document, and are you querying with
containment (`@>`) or existence (`?`)?**
→ **GIN**, directly on the `jsonb` column. Chapter 1's `businesses.details`
uses this for exactly this reason — Chapter 1 Exercise 3 confirms via
`EXPLAIN ANALYZE` that the GIN index is actually used, not just
present. `jsonb_path_ops` is worth a second GIN index alongside the
default operator class if your queries are containment-only —
Chapter 1 builds both, on the same column, and compares.

**3. Is the column full-text search (`tsvector`) or a trigram-matched
string (`pg_trgm`)?**
→ **GIN** in both cases, for the same underlying reason: both are
matching against a large, variable-length set of tokens (lexemes for
text search, trigrams for fuzzy matching) per row, which is what GIN
is actually built for. Chapter 4's `city_documents.search_vector` and
Chapter 5's trigram indexes on `residents`/`business_names` both use
GIN. `pg_trgm` also supports a **GiST** trigram index
(`gist_trgm_ops`) — Chapter 5 builds one specifically to compare: GiST
trigram indexes are typically smaller and faster to build, GIN indexes
are typically faster to query, and the right choice depends on your
write-vs-read ratio more than any fixed rule.

**4. Is the column geometry, a network range (`ip4r`), or otherwise a
"does this overlap/contain that" question rather than plain equality?**
→ **GiST**. Chapter 2's `neighborhoods.geom`/`businesses.geom` and
Chapter 7's `blocklists` CIDR ranges both use GiST for the same
underlying reason: both are answering containment/overlap questions
over 2D or range-shaped data, which B-tree's linear ordering can't
represent and GIN's token-set model doesn't fit either.

**5. Is the table huge, append-mostly, and naturally correlated with
insertion order (a timestamp, a sequential ID)?**
→ **BRIN**, and *only* if that correlation is real. Chapter 8's
`sensor_readings` (9.6M rows, inserted roughly in `recorded_at` order)
is the textbook case — a BRIN index stores block-range summaries, not
per-row entries, so it's tiny compared to a B-tree on the same column,
at the cost of only being useful when physical row order genuinely
tracks the indexed value. Combined with partitioning (also Chapter 8),
most queries never need the index at all — partition pruning already
eliminates the irrelevant months before any index gets consulted.

**6. Is the column a vector embedding, queried by approximate nearest
neighbor?**
→ **HNSW** or **IVFFlat**, both `pgvector`-specific, both genuinely
different trade-offs rather than one being strictly better:
- **IVFFlat**: faster to build, needs `lists`/`probes` tuning, recall
  degrades further from exact as the dataset grows unless retuned.
- **HNSW**: slower to build, no equivalent tuning parameter needed,
  generally better recall at query time.

Chapter 6 builds both against the same data specifically to compare
build time and recall directly rather than taking either trade-off on
faith.

**7. Does the query only ever touch a small, predictable subset of
rows — most rows never relevant to any query that matters?**
→ A **partial index**, on top of whichever type above fits the column.
Chapter 3's `idx_jobs_claim_order` only indexes `queued` jobs — a
`completed` job is never going to be claimed again, so indexing it is
pure waste. This isn't a separate index *type*, it's a `WHERE` clause
on any of the types above, and it's worth considering by default for
any status-flag-shaped column, not just this one.

**8. Do queries always filter on a column combination together, not
independently?**
→ A **compound index**, ordered with the most selective/most-commonly-
filtered column first (or the one narrowing the range in a partitioned
table, so the query planner can combine it with partition pruning).
Chapter 20's most important, counter-intuitive real finding belongs
here: a naive single-column index on `sensor_readings.sensor_id` (a
low-cardinality, evenly-scattered column, roughly 1-in-120 rows
matching) made a real query **slower** — 338ms → 377ms — than the
original parallel sequential scan, because a Bitmap Heap Scan at that
scatter still has to visit nearly every heap page, while giving up the
seq scan's free parallelism entirely. The actual fix needed both a
realistic, time-bounded query (letting Chapter 8's partition pruning
narrow to one month first) *and* a compound index,
`(sensor_id, recorded_at)`, matching that query's actual shape — a
real, measured ~4.5× win over pruning alone, ~43× over the original
query. **Row count and column cardinality alone don't tell you whether
an index will help — the physical scatter of matching rows across
pages does, and the only way to know is `EXPLAIN (ANALYZE, BUFFERS)`
against the real query shape, not an assumption about "add an index"
being automatically correct.**

## Quick-reference table

| Index type | Best for | Chapter(s) | Real caveat found in this book |
|---|---|---|---|
| B-tree | Equality, range, `ORDER BY` | 1, 3, 15, 20 | Implicit casts silently defeat it — check `Index Cond` vs. `Filter` |
| GIN (`jsonb`) | JSONB containment/existence | 1 | Two operator classes worth having side by side (default + `jsonb_path_ops`) |
| GIN (`tsvector`) | Full-text search | 4, 16 | Pair with a *generated* `tsvector` column, not a trigger, where possible (Chapter 16) |
| GIN (`pg_trgm`) | Fuzzy/substring matching | 5 | Faster queries, larger index/slower writes than the GiST alternative |
| GiST (`pg_trgm`) | Fuzzy/substring matching | 5 | Smaller/faster to build; slower queries than GIN |
| GiST (geometry) | Spatial containment/overlap | 2 | The only correct choice for `ST_*` operators — B-tree/GIN don't apply |
| GiST (`ip4r`) | CIDR/range containment | 7 | Same shape of problem as spatial GiST, different domain |
| BRIN | Huge, insertion-order-correlated columns | 8 | Only useful if physical order genuinely correlates — verify, don't assume |
| HNSW | Vector ANN, best recall | 6 | Slower to build than IVFFlat |
| IVFFlat | Vector ANN, faster build | 6 | Needs `lists`/`probes` tuning; recall degrades more as data grows |
| Partial (any type) | Narrow, predictable subset of rows | 3, 18 | Free win wherever a status flag makes most rows permanently irrelevant |
| Compound (any type) | Multi-column filter shapes | 20 | Match the index to the *actual query shape*, not just "the columns in the `WHERE` clause" — verified via `EXPLAIN`, not assumed |
