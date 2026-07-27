# Chapter 4 — Full-Text Search: `tsvector`, Stopwords, and Ranking

> *"Grep finds characters. Full-text search finds meaning — or at least gets
> a lot closer."*

---

## Background

`LIKE '%harbour%'` finds the literal substring "harbour". It will not find
"Harbour", "harbours", or a document about "the harbor" (different spelling)
unless you handle every variation yourself, and it cannot tell you whether a
match in the title is more relevant than a match buried in paragraph six. As
soon as an application needs to search prose — meeting minutes, support
tickets, product descriptions, articles — substring matching stops being
enough. The usual reflex is to reach for Elasticsearch or a similar dedicated
search engine.

PostgreSQL has had a full-text search engine built in since version 8.3. It
tokenizes text into words, reduces those words to normalized root forms
(*stemming*), discards low-information words like "the" and "of"
(*stopwords*), and stores the result in a specialized `tsvector` type that a
GIN index can search in milliseconds. A companion `tsquery` type lets you
express boolean and phrase searches, and a family of ranking functions score
how well each match fits the query. None of this requires an extension —
it is core PostgreSQL, the same engine `websearch_to_tsquery`-powered search
boxes on production sites are built on.

This chapter builds a search feature over a small document archive: how text
becomes a `tsvector`, what stopword removal actually throws away, how to keep
the vector in sync as rows change, how query syntax differs between a
developer-facing boolean query language and a plain-text search box, and how
to rank and highlight results. The final exercise customizes the stopword
list itself — because in a *city* government's document archive, the words
"city" and "council" appear so often they stop being useful signals, exactly
the kind of domain-specific tuning full-text search is designed to support.

---

## The Scenario

Portsmith's city clerk publishes an archive of public records: council
meeting minutes, zoning ordinances, and public notices. Residents need to
search this archive by keyword — "what happened with the Riverside dog
park?", "which ordinances mention Canal Road?" — and get back the most
relevant documents first, with a highlighted snippet showing why each one
matched.

The `city_documents` table holds all three document types in one place, with
a `body` column of plain prose text and a few relational columns for
filtering:

| Column           | Purpose                                                              |
|------------------|-----------------------------------------------------------------------|
| `doc_type`       | `council_minutes`, `zoning_ordinance`, or `public_notice`             |
| `department`     | Which city department published it (City Council, Public Works, …)   |
| `title`          | Short document title                                                  |
| `body`           | Full plain-text document body — the field full-text search runs over |
| `published_date` | When the document was published                                       |

The documents share recurring topics on purpose — the Riverside dog park,
the Harbour District waterfront rezoning, the Canal Road bike lane — so that
searches in the exercises return more than one hit, and ranking has
something real to sort between. No extensions are required for this
chapter: `tsvector`, `tsquery`, and every function used below are core
PostgreSQL.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Convert text to a `tsvector` and read the lexeme:position notation it
  produces.
- Explain exactly what stopword removal and stemming do to a document, using
  `ts_debug` to see PostgreSQL's tokenizer classify each word.
- Maintain a `tsvector` column automatically with a trigger, and index it
  with GIN for sub-millisecond searches.
- Write boolean queries with `to_tsquery` and understand why
  `plainto_tsquery` is the safer choice for a plain search box.
- Rank results with `ts_rank` and `ts_rank_cd`, and generate highlighted
  snippets with `ts_headline`.
- Build a custom text search configuration that treats domain-specific words
  as stopwords, and see it change real search results.

---

## Installation

This chapter needs nothing beyond what Chapter 1 already set up: PostgreSQL
16 and a Python 3.12 virtual environment with `psycopg`. If you skipped
Chapter 1, see its Installation section. Full-text search is core
PostgreSQL — there is no extension to enable.

---

## Loading the Data

### Run the seed script

From the `book/` directory, with the virtual environment active:

```bash
python data/ch04_seed.py
```

Expected output:

```
Connecting to: dbname=portsmith
Creating schema …
Inserting 30 documents …
Done — 30 rows in city_documents.
```

The seed script is self-contained — it does not depend on any earlier
chapter's data. Note that it deliberately does **not** create a `tsvector`
column or index; you build both by hand in Exercise 3, which is the point of
the chapter.

### Verify the load

Open `psql portsmith` and run these checks.

**Check 1 — table structure:**

```sql
\d city_documents
```

```
                                Table "public.city_documents"
     Column     |  Type   | Collation | Nullable |                  Default
----------------+---------+-----------+----------+--------------------------------------------
 id             | integer |           | not null | nextval('city_documents_id_seq'::regclass)
 doc_type       | text    |           | not null |
 department     | text    |           | not null |
 title          | text    |           | not null |
 body           | text    |           | not null |
 published_date | date    |           | not null |
Indexes:
    "city_documents_pkey" PRIMARY KEY, btree (id)
    "idx_city_documents_doc_type" btree (doc_type)
    "idx_city_documents_published_date" btree (published_date)
Check constraints:
    "city_documents_doc_type_check" CHECK (doc_type = ANY (ARRAY['council_minutes'::text, 'zoning_ordinance'::text, 'public_notice'::text]))
```

**Check 2 — counts by document type:**

```sql
SELECT doc_type, COUNT(*) AS documents
FROM   city_documents
GROUP  BY doc_type
ORDER  BY doc_type;
```

```
     doc_type     | documents
------------------+-----------
 council_minutes  |        10
 public_notice    |        10
 zoning_ordinance |        10
(3 rows)
```

**Check 3 — counts by department:**

```sql
SELECT department, COUNT(*) AS documents
FROM   city_documents
GROUP  BY department
ORDER  BY department;
```

```
     department     | documents
--------------------+-----------
 City Council       |         9
 Finance            |         1
 Parks & Recreation |         3
 Planning & Zoning  |        12
 Public Works       |         5
(5 rows)
```

If all three match, proceed to the exercises.

---

## Exercises

---

### Exercise 1 — Converting Text to `tsvector`

**1.1 — A basic conversion**

`to_tsvector` is the function that turns plain text into PostgreSQL's
searchable representation. Try it on one document's body:

```sql
SELECT title FROM city_documents WHERE id = 1;
```

```
               title
------------------------------------
 Council Minutes — Harbour District Waterfront Renovation Budget
```

```sql
SELECT to_tsvector('english', body) FROM city_documents WHERE id = 1;
```

```
'along':38 'approv':67 'begin':79 'boardwalk':34 'bond':53 'budget':10 'citi':3
'construct':76 'conven':5 'council':4,41,61 'cover':28 'debat':56 'director':18
'discuss':43 'district':14 'expect':77 'fall':82 'first':69 'fund':44,74
'grant':50 'harbour':13,40,72 'includ':46 'infrastructur':49 'light':36
'measur':54 'member':42 'new':32 'one':65 'pedestrian':33 'phase':26,70
'plan':27 'portsmith':2 'present':22 'propos':9 'public':20 'renov':16,73
'repair':30 'review':7 'seawal':29 'six':63 'sourc':45 'state':48
'three':25 'three-phas':24 'timelin':59 'upgrad':37 'vote':62
'waterfront':15 'work':21
```

**1.2 — Reading the format**

Each entry is `'lexeme':position,position,…`. A **lexeme** is a normalized
word form, not the literal text — notice `'vote':62` even though the source
text says "voted", `'approv':67` for "approve", and `'renov':16,73` for both
"renovation" (position 16) and "renovation" again later (position 73, from
"harbour **renovation** funding"). PostgreSQL stems words to their root so
that a search for "vote" also matches documents containing "voted",
"votes", or "voting" — you don't have to enumerate every inflection
yourself.

The **positions** are the word's ordinal location in the original text (1st
word, 2nd word, …). They exist for two reasons: `ts_rank` uses them to
compute how spread out or clustered a document's matches are, and phrase
search (`<->`, used in Exercise 4) uses them to require words to appear
adjacent to each other, not just anywhere in the document.

**1.3 — Case and punctuation are already handled**

Note that "Council" (capitalized, position 4) and "council" (lowercase,
positions 41 and 61) both collapsed into the single lexeme `'council'` with
three positions — `to_tsvector` lowercases everything and strips punctuation
as part of tokenization, before stemming ever runs.

---

### Exercise 2 — What Stopword Removal Actually Throws Away

**2.1 — Compare `simple` and `english` configurations**

PostgreSQL ships several **text search configurations** — named bundles of
tokenizer + dictionary rules. `simple` lowercases and tokenizes but does
*no* stemming and drops *no* stopwords; `english` does both. Run the same
body through each and count the resulting lexemes:

```sql
SELECT array_length(regexp_split_to_array(body, '\s+'), 1) AS raw_words
FROM   city_documents WHERE id = 1;
```

```
 raw_words
-----------
        80
```

```sql
SELECT array_length(tsvector_to_array(to_tsvector('simple', body)), 1) AS lexemes_simple,
       array_length(tsvector_to_array(to_tsvector('english', body)), 1) AS lexemes_english
FROM   city_documents WHERE id = 1;
```

```
 lexemes_simple | lexemes_english
-----------------+------------------
              59 |               49
```

80 raw whitespace-separated words collapse to 59 distinct lexemes under
`simple` (repeated words like "the" and "council" count once each, but
nothing is removed or stemmed) and to 49 under `english` — ten fewer,
because `english` additionally discards stopwords like "the", "a", "of",
"to", "in", and "and" entirely. They carry no search-relevant meaning on
their own, and indexing them would only bloat the index with entries that
match nearly every document.

**2.2 — Watch the tokenizer classify each word with `ts_debug`**

`ts_debug` is the diagnostic function for seeing exactly what a
configuration does to a piece of text, word by word — useful whenever a
search isn't matching what you expect and you need to know why. Run it on a
short sentence:

```sql
SELECT alias, token, dictionaries, lexemes
FROM   ts_debug('english', 'The council voted to approve the budget for the harbour renovation.')
WHERE  alias <> 'blank';
```

```
   alias   |   token    |  dictionaries  |  lexemes
-----------+------------+----------------+-----------
 asciiword | The        | {english_stem} | {}
 asciiword | council    | {english_stem} | {council}
 asciiword | voted      | {english_stem} | {vote}
 asciiword | to         | {english_stem} | {}
 asciiword | approve    | {english_stem} | {approv}
 asciiword | the        | {english_stem} | {}
 asciiword | budget     | {english_stem} | {budget}
 asciiword | for        | {english_stem} | {}
 asciiword | the        | {english_stem} | {}
 asciiword | harbour    | {english_stem} | {harbour}
 asciiword | renovation | {english_stem} | {renov}
```

Every token gets classified (`asciiword` here — a plain word) and routed to
the `english_stem` dictionary. Content words come back with a stemmed
lexeme; stopwords ("The", "to", "the", "for", "the") come back with an
**empty** `lexemes` array — recognized, looked up, and explicitly discarded.
That empty array is the entire mechanism: a word is a stopword precisely
when its dictionary entry maps it to nothing.

**2.3 — When you'd reach for `simple` instead**

`english` is the right default for prose. `simple` is useful for columns
where stemming would be actively wrong — product SKUs, tag lists, or
anything where "waterfront" and "waterfronts" should *not* be treated as the
same token. `city_documents.body` is prose, so the rest of this chapter uses
`english`.

---

### Exercise 3 — A Maintained Column and a GIN Index

Computing `to_tsvector(body)` at query time works, but it means recomputing
the same tokenization on every single search, over every row, every time.
The standard pattern is to store the vector in its own column, keep it
current as rows change, and index it.

**3.1 — Add the column and backfill it**

```sql
ALTER TABLE city_documents ADD COLUMN search_vector tsvector;

UPDATE city_documents
SET    search_vector = to_tsvector('english', title || ' ' || body);
```

Indexing `title` alongside `body` means a search for a word that only
appears in the title (not repeated in the body text) still matches.

**3.2 — Keep it current with a trigger**

A column populated once goes stale the moment anyone edits `title` or
`body`. A `BEFORE` trigger recomputes it on every write:

```sql
CREATE FUNCTION city_documents_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', NEW.title || ' ' || NEW.body);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_city_documents_search_vector
    BEFORE INSERT OR UPDATE OF title, body ON city_documents
    FOR EACH ROW
    EXECUTE FUNCTION city_documents_search_vector_update();
```

`OF title, body` scopes the trigger so it only fires when one of the two
source columns actually changes — an `UPDATE` that only touches
`published_date` doesn't pay for a needless re-tokenization.

> **Note — the manual way vs. the modern way:** This trigger pattern is how
> every PostgreSQL version has supported derived `tsvector` columns, and
> it's still exactly right when the derived value depends on more than one
> column, as it does here (`title` **and** `body`). PostgreSQL 12 added
> **generated columns** (`GENERATED ALWAYS AS (...) STORED`), which handle
> the common case — a `tsvector` derived from a single column — with less
> boilerplate and no trigger function to maintain by hand. Chapter 16
> revisits this exact table and replaces this trigger with a generated
> column once `body` alone is the source. Both approaches produce an
> identical `tsvector`; the trigger is simply the general-purpose tool that
> works whenever the derivation is more than one column deep.

**3.3 — Index it with GIN**

```sql
CREATE INDEX idx_city_documents_search_vector
    ON city_documents USING GIN (search_vector);
```

```sql
\d city_documents
```

```
                                Table "public.city_documents"
     Column     |   Type   | Collation | Nullable |                  Default
----------------+----------+-----------+----------+--------------------------------------------
 id             | integer  |           | not null | nextval('city_documents_id_seq'::regclass)
 doc_type       | text     |           | not null |
 department     | text     |           | not null |
 title          | text     |           | not null |
 body           | text     |           | not null |
 published_date | date     |           | not null |
 search_vector  | tsvector |           |          |
Indexes:
    "city_documents_pkey" PRIMARY KEY, btree (id)
    "idx_city_documents_doc_type" btree (doc_type)
    "idx_city_documents_published_date" btree (published_date)
    "idx_city_documents_search_vector" gin (search_vector)
Check constraints:
    "city_documents_doc_type_check" CHECK (doc_type = ANY (ARRAY['council_minutes'::text, 'zoning_ordinance'::text, 'public_notice'::text]))
Triggers:
    trg_city_documents_search_vector BEFORE INSERT OR UPDATE OF title, body ON city_documents FOR EACH ROW EXECUTE FUNCTION city_documents_search_vector_update()
```

**3.4 — Confirm the index is used**

The `@@` operator tests whether a `tsvector` matches a `tsquery`:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, title
FROM   city_documents
WHERE  search_vector @@ to_tsquery('english', 'harbour & waterfront');
```

```
                                               QUERY PLAN
---------------------------------------------------------------------------------------------------------
 Seq Scan on city_documents  (cost=0.00..8.38 rows=1 width=36) (actual time=0.025..0.047 rows=5 loops=1)
   Filter: (search_vector @@ '''harbour'' & ''waterfront'''::tsquery)
   Rows Removed by Filter: 25
   Buffers: shared hit=8
```

On 30 rows the planner reasonably decides a sequential scan is cheaper than
an index lookup — same behaviour you saw with the JSONB GIN index in
Chapter 1. Force the index to confirm it works, exactly as in that chapter:

```sql
SET enable_seqscan = off;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, title
FROM   city_documents
WHERE  search_vector @@ to_tsquery('english', 'harbour & waterfront');

SET enable_seqscan = on;   -- always restore this
```

```
                                                                Query Plan
------------------------------------------------------------------------------------------------------------------------------------------
 Bitmap Heap Scan on city_documents  (cost=12.98..16.99 rows=1 width=36) (actual time=0.024..0.033 rows=5 loops=1)
   Recheck Cond: (search_vector @@ '''harbour'' & ''waterfront'''::tsquery)
   Heap Blocks: exact=5
   Buffers: shared hit=10
   ->  Bitmap Index Scan on idx_city_documents_search_vector  (cost=0.00..12.98 rows=1 width=0) (actual time=0.014..0.014 rows=5 loops=1)
         Index Cond: (search_vector @@ '''harbour'' & ''waterfront'''::tsquery)
         Buffers: shared hit=5
```

`Bitmap Index Scan on idx_city_documents_search_vector` confirms the GIN
index is doing the work. This is what makes full-text search viable at
scale: instead of tokenizing every row's text on every query, PostgreSQL
looks up each query lexeme directly in the index.

---

### Exercise 4 — `to_tsquery` vs. `plainto_tsquery`

**4.1 — `to_tsquery`: a boolean query language**

`to_tsquery` expects an expression using explicit operators: `&` (AND),
`|` (OR), `!` (NOT), and `<->` (phrase — "immediately followed by"):

```sql
SELECT id, title
FROM   city_documents
WHERE  search_vector @@ to_tsquery('english', 'harbour & waterfront')
ORDER  BY id;
```

```
 id |                                 title
----+--------------------------------------------------------------------------
  1 | Council Minutes — Harbour District Waterfront Renovation Budget
  8 | Council Minutes — Harbour District Food Truck Permits
 12 | Zoning Ordinance — Harbour District Waterfront Height Variance
 22 | Public Notice — Public Hearing on Harbour District Waterfront Rezoning
 30 | Public Notice — Annual Fireworks Display and Street Closures
(5 rows)
```

`!` excludes a term. This finds documents about flooding that are *not*
about the flood-mitigation infrastructure program specifically:

```sql
SELECT id, title
FROM   city_documents
WHERE  search_vector @@ to_tsquery('english', 'flood & !mitigation')
ORDER  BY id;
```

```
 id |                        title
----+--------------------------------------------------------
  5 | Council Minutes — Riverside Road Resurfacing Program
(1 row)
```

That single hit mentions "flooding" (which stems to `flood`) while
discussing drainage damage, but never says "mitigation" — exactly what the
query asked for.

**4.2 — `to_tsquery` has no forgiveness for plain text**

Feed it a raw phrase with no operator between the words, and it errors
instead of guessing what you meant:

```sql
SELECT id, title
FROM   city_documents
WHERE  search_vector @@ to_tsquery('english', 'flood mitigation');
```

```
ERROR:  syntax error in tsquery: "flood mitigation"
```

This is `to_tsquery`'s defining trade-off: it is a precise query language
for code that constructs queries deliberately, and it is the wrong function
to hand raw user input from a search box — a user typing "flood mitigation"
with no operators will get an error page instead of results.

**4.3 — `plainto_tsquery`: safe for a search box**

`plainto_tsquery` takes plain text, tokenizes and stems it exactly like
`to_tsvector` does, drops stopwords, and **ANDs** everything that survives.
Feed it the same two words that made `to_tsquery` error out in 4.2, but
typed the way an actual user would type them — with a stray "the" in front:

```sql
SELECT plainto_tsquery('english', 'the flood mitigation');
```

```
  plainto_tsquery
--------------------
 'flood' & 'mitig'
```

"the" never makes it into the query — `plainto_tsquery` drops it as a
stopword, exactly the way `to_tsvector` would drop it from a document, and
ANDs together whatever content words are left. Run it against the table:

```sql
SELECT id, title
FROM   city_documents
WHERE  search_vector @@ plainto_tsquery('english', 'the flood mitigation')
ORDER  BY id;
```

```
 id |                                 title
----+------------------------------------------------------------------------
 10 | Council Minutes — Special Session on Flood Mitigation Infrastructure
 25 | Public Notice — City Council Special Session on Flood Mitigation
(2 rows)
```

No error this time, and no operators to get wrong — `plainto_tsquery` took
a sentence fragment with a stopword in it and produced exactly the query
4.2 had to write by hand. The trade-off runs the other way from
`to_tsquery`: you get safety and stopword handling for free, but you lose
the ability to express OR, NOT, or phrase search — `plainto_tsquery` always
ANDs every surviving word together.

**4.4 — `|` for OR searches**

```sql
SELECT to_tsquery('english', 'dog | bike');
```

```
   to_tsquery
----------------
 'dog' | 'bike'
```

```sql
SELECT id, title
FROM   city_documents
WHERE  search_vector @@ to_tsquery('english', 'dog | bike')
ORDER  BY id;
```

```
 id |                               title
----+---------------------------------------------------------------------
  5 | Council Minutes — Riverside Road Resurfacing Program
  6 | Council Minutes — Riverside Dog Park Funding
  9 | Council Minutes — Canal Road Bike Lane Expansion
 15 | Zoning Ordinance — Reduced Parking Minimums Near Transit Corridors
 24 | Public Notice — Riverside Dog Park Ribbon-Cutting Event
 28 | Public Notice — Canal Road Bike Lane Construction Schedule
 30 | Public Notice — Annual Fireworks Display and Street Closures
(7 rows)
```

Document 5 (road resurfacing) and 15 (parking minimums) show up because
each mentions "bike" in passing — the resurfacing minutes note the work
being coordinated with "the planned Canal Road bike lane construction," and
the parking ordinance references "the city's ongoing bike lane expansion."
`OR` genuinely means *either*, which is exactly why it's useful and why it
returns more, looser matches than `AND`.

---

### Exercise 5 — Ranking with `ts_rank` and `ts_rank_cd`, and `ts_headline` Snippets

`@@` tells you whether a document matches — it says nothing about *how
well*. A user searching a 30-document archive can eyeball every hit, but a
user searching 30,000 documents needs the best matches first.

**5.1 — `ts_rank`: weight by term frequency**

```sql
SELECT id, title, round(ts_rank(search_vector, query)::numeric, 4) AS rank
FROM   city_documents, to_tsquery('english', 'harbour & waterfront') AS query
WHERE  search_vector @@ query
ORDER  BY rank DESC;
```

```
 id |                                 title                                  |  rank
----+------------------------------------------------------------------------+--------
 12 | Zoning Ordinance — Harbour District Waterfront Height Variance         | 0.1986
  1 | Council Minutes — Harbour District Waterfront Renovation Budget        | 0.1959
 22 | Public Notice — Public Hearing on Harbour District Waterfront Rezoning | 0.1895
  8 | Council Minutes — Harbour District Food Truck Permits                  | 0.0999
 30 | Public Notice — Annual Fireworks Display and Street Closures           | 0.0992
(5 rows)
```

`ts_rank` scores primarily on how often the query terms appear relative to
the document's overall length — it does not care where in the document they
appear or how close together they are. Documents 12, 1, and 22 rank
highest because "harbour" and "waterfront" are central, repeated themes in
short documents; 8 and 30 rank lower because each mentions the harbour only
in passing within a longer document about something else.

**5.2 — `ts_rank_cd`: weight by proximity too ("cover density")**

```sql
SELECT id, title,
       round(ts_rank(search_vector, query)::numeric, 4) AS rank,
       round(ts_rank_cd(search_vector, query)::numeric, 4) AS rank_cd
FROM   city_documents, to_tsquery('english', 'harbour & waterfront') AS query
WHERE  search_vector @@ query
ORDER  BY rank_cd DESC;
```

```
 id |                                 title                                  |  rank  | rank_cd
----+------------------------------------------------------------------------+--------+---------
  1 | Council Minutes — Harbour District Waterfront Renovation Budget        | 0.1959 |  0.1107
 22 | Public Notice — Public Hearing on Harbour District Waterfront Rezoning | 0.1895 |  0.1053
 12 | Zoning Ordinance — Harbour District Waterfront Height Variance         | 0.1986 |  0.0700
 30 | Public Notice — Annual Fireworks Display and Street Closures           | 0.0992 |  0.0545
  8 | Council Minutes — Harbour District Food Truck Permits                  | 0.0999 |  0.0542
(5 rows)
```

The order changes: document 12 had the *highest* `ts_rank` but drops to
third under `ts_rank_cd`. `ts_rank_cd` additionally rewards matched terms
that cluster close together in the text ("cover density") — in documents 1
and 22, "harbour" and "waterfront" appear right next to each other
("Harbour District **Waterfront** Renovation…"); in document 12 they occur
further apart. Neither function is universally "more correct" — `ts_rank`
is the standard choice; `ts_rank_cd` is worth trying when word proximity
itself signals relevance, as it often does for short phrase-like queries.

**5.3 — Highlighted snippets with `ts_headline`**

A ranked list of titles is useful; showing *why* a document matched, with
the query terms highlighted in context, is what users actually expect from
a search results page:

```sql
SELECT ts_headline('english', body, to_tsquery('english', 'harbour & waterfront'),
                    'StartSel=**, StopSel=**, MaxWords=25, MinWords=10')
FROM   city_documents
WHERE  id = 1;
```

```
 **Harbour** District **waterfront** renovation. The Director of Public Works presented
```

`ts_headline` re-scans the original text (not the `tsvector`) looking for
the query terms, extracts a window around the best-matching fragment
bounded by `MinWords`/`MaxWords`, and wraps each match in `StartSel`/
`StopSel` markers — `**…**` here, but in a web application you'd use
`<mark>…</mark>` or similar. This is genuinely expensive compared to a
`tsvector` lookup (it re-tokenizes the source text on every call), so use
it only on the page of results you're actually displaying, never inside a
`WHERE` clause.

---

### Exercise 6 — A Custom Text Search Configuration for Domain Stopwords

**6.1 — The problem: some "content" words carry no information here**

This is a city document archive. The words "Portsmith", "city", and
"council" appear constantly — they are structurally present in almost every
record, the way "the" is present in almost every English sentence. Standard
`english` stopword removal has no way to know that, because it is tuned for
general English, not this specific corpus:

```sql
SELECT count(*) FROM city_documents
WHERE  search_vector @@ to_tsquery('english', 'city & council');
```

```
 count
-------
     8
```

Eight of thirty documents — over a quarter of the entire archive — "match"
a query on words that describe almost nothing about what makes any one of
them relevant. Left alone, these words dilute ranking scores and inflate
plain-text queries with noise terms the searcher didn't mean to require.

**6.2 — Build a stopword file that extends the standard list**

A text search configuration's stopword list is a plain text file, one word
per line, that PostgreSQL reads from its `tsearch_data` directory. Start
from the existing `english.stop` file so you keep every standard English
stopword, then append the domain-specific ones:

```bash
PG_SHAREDIR=$(pg_config --sharedir)
sudo bash -c "cat '$PG_SHAREDIR/tsearch_data/english.stop' > '$PG_SHAREDIR/tsearch_data/portsmith_english.stop'"
sudo bash -c "printf 'portsmith\ncity\ncouncil\n' >> '$PG_SHAREDIR/tsearch_data/portsmith_english.stop'"
```

> Placing files here requires root, since `tsearch_data` lives under
> PostgreSQL's shared install directory rather than anything database-owned.
> If your platform's PostgreSQL package stores it elsewhere, `pg_config
> --sharedir` will always point at the right location.

**6.3 — Wire the file into a dictionary and a configuration**

A stopword file alone does nothing — it has to be attached to a **text
search dictionary**, and that dictionary mapped into a **text search
configuration** that queries can actually reference:

```sql
CREATE TEXT SEARCH DICTIONARY portsmith_stem (
    TEMPLATE = snowball,
    LANGUAGE = english,
    STOPWORDS = portsmith_english
);

CREATE TEXT SEARCH CONFIGURATION public.portsmith_english (COPY = pg_catalog.english);

ALTER TEXT SEARCH CONFIGURATION portsmith_english
    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
    WITH portsmith_stem;
```

`TEMPLATE = snowball` reuses PostgreSQL's standard English stemming
algorithm — only the stopword list changes, not the stemming rules.
`COPY = pg_catalog.english` starts the new configuration as an exact clone
of `english` (same tokenizer, same handling of numbers, emails, URLs, …),
and the `ALTER MAPPING` line is the one substitution: word tokens now route
through `portsmith_stem` instead of the stock `english_stem` dictionary.

**6.4 — Confirm the noise words are gone**

```sql
SELECT to_tsvector('portsmith_english', body) FROM city_documents WHERE id = 25;
```

```
'affect':37 'area':27 'attend':44 'basin':59 'comment':47 'conven':11 'develop':61
'discuss':16 'drain':56 'encourag':42 'engin':53 'flood':17,40,68 'given':4
'herebi':3 'infrastructur':19 'last':65 'mitig':18 'northgat':24 'notic':1
'open':31 'present':50 'propos':60 'provid':46 'public':34 'resid':36
'respons':63 'retain':25 'retent':58 'riversid':21 'session':14,29 'special':13
'spring':39 'staff':48 'storm':55 'wall':26 'year':66
```

Compare to `to_tsvector('english', body)` on the same row, which still
carries `'citi':8,52`, `'council':9`, and `'portsmith':7` — three entries
present under `english` and absent under `portsmith_english`. Everything
else is untouched, because only the stopword list changed.

**6.5 — Watch a noise-only query collapse to nothing**

```sql
SELECT to_tsquery('portsmith_english', 'city & council');
```

```
NOTICE:  text-search query contains only stop words or doesn't contain lexemes, ignored
 to_tsquery
------------

(1 row)
```

Under `portsmith_english`, "city" and "council" are *both* stopwords, so a
query built from nothing else has nothing left to search for — PostgreSQL
says so explicitly instead of silently matching everything (or nothing) for
an unclear reason.

**6.6 — See it fix a real plain-text search**

This is the exercise's payoff: a resident searching for "Portsmith dog park
council" — a completely natural way to phrase it — under `english`:

```sql
SELECT plainto_tsquery('english', 'Portsmith dog park council');
```

```
             plainto_tsquery
-------------------------------------------
 'portsmith' & 'dog' & 'park' & 'council'
```

```sql
SELECT id, title FROM city_documents
WHERE  search_vector @@ plainto_tsquery('english', 'Portsmith dog park council')
ORDER  BY id;
```

```
 id |                          title
----+-----------------------------------------------------------
 24 | Public Notice — Riverside Dog Park Ribbon-Cutting Event
(1 row)
```

Only one hit. The council minutes that actually approved funding for the
same dog park (document 6) never happens to use the literal word
"Portsmith," so requiring it as an AND term silently excludes the single
most relevant record. Under `portsmith_english`:

```sql
SELECT plainto_tsquery('portsmith_english', 'Portsmith dog park council');
```

```
 plainto_tsquery
-----------------
 'dog' & 'park'
```

```sql
SELECT id, title FROM city_documents
WHERE  search_vector @@ plainto_tsquery('portsmith_english', 'Portsmith dog park council')
ORDER  BY id;
```

```
 id |                          title
----+-----------------------------------------------------------
  6 | Council Minutes — Riverside Dog Park Funding
 24 | Public Notice — Riverside Dog Park Ribbon-Cutting Event
(2 rows)
```

Stripped down to the two words that actually distinguish this search —
`dog` and `park` — both relevant documents come back. This is the concrete
argument for a custom configuration: it is not a cosmetic tweak, it changes
which documents a real user actually finds.

> **Note:** the `search_vector` column built in Exercise 3 was populated
> with the stock `english` configuration, so it still contains `'citi'`,
> `'council'`, and `'portsmith'` lexemes. The comparisons above work because
> `@@` only needs the *query's* surviving lexemes to be a subset of the
> document's — extra lexemes in the document that the query no longer asks
> for are simply irrelevant. To fully adopt `portsmith_english` as the
> table's search configuration going forward, you would update the trigger
> from Exercise 3 to call `to_tsvector('portsmith_english', …)` and rebuild
> `search_vector` for existing rows.

---

## Summary — What You Should Now Know

| Tool | What it does |
|------|-------------|
| `to_tsvector(config, text)` | Tokenizes, lowercases, stems, and removes stopwords, producing a searchable `lexeme:position` vector |
| `to_tsquery(config, expr)` | Parses a boolean query language (`&`, `\|`, `!`, `<->`); errors on plain text with no operators |
| `plainto_tsquery(config, text)` | Tokenizes plain text the same way as `to_tsvector`, then ANDs every surviving lexeme — safe for a search box |
| `@@` | Tests whether a `tsvector` matches a `tsquery` |
| `ts_debug(config, text)` | Shows exactly how each token was classified and which lexeme (if any) it produced — the tool for "why didn't this match?" |
| GIN index on a `tsvector` column | Turns `@@` from a sequential scan into an index lookup |
| `ts_rank` / `ts_rank_cd` | Score match quality by term frequency, or by term frequency **and** proximity ("cover density") |
| `ts_headline(config, text, query, options)` | Re-scans the source text and returns a highlighted snippet — expensive; use only on displayed results |
| `CREATE TEXT SEARCH DICTIONARY ... (STOPWORDS = ...)` + `CREATE TEXT SEARCH CONFIGURATION` | Build a custom configuration with domain-specific stopwords |

**The key design insight** from this chapter is that full-text search is not
one function call — it's a pipeline (tokenize → stem → filter stopwords)
that you can inspect at every stage with `ts_debug`, store the output of
with a maintained column and a GIN index, query against with two very
different trade-offs (`to_tsquery` for precision, `plainto_tsquery` for
safety), and tune for your specific corpus by swapping the stopword list —
exactly the kind of tuning a generic search engine bolted on top of your
database can't do without shipping your schema knowledge to it.

The `city_documents` table you built here is reused directly in later
chapters: Chapter 6 (`pgvector`) adds embeddings to the same table for
semantic search and builds a hybrid search combining `ts_rank` with cosine
distance, and Chapter 16 (Generated Columns) replaces the hand-written
trigger from Exercise 3 with a `GENERATED ALWAYS AS (...) STORED` column.

---

*Going further: `websearch_to_tsquery` (PostgreSQL 11+) is worth knowing
about even though this chapter didn't use it — it accepts the same
quoted-phrase and `-exclude` syntax as a typical web search box (e.g.
`"flood mitigation" -infrastructure`) while remaining as forgiving as
`plainto_tsquery`, making it the best default for a real user-facing search
field. For very large document sets, look into PostgreSQL's built-in
support for weighted vectors (`setweight()`, ranking title matches above
body matches) and consider whether a dedicated search engine becomes
worthwhile once ranking quality and query latency requirements outgrow what
a GIN index over a single table can deliver — the honest answer, for most
applications, is later than you'd expect.*
