# Chapter 5 — Fuzzy Matching: `pg_trgm`

> *"Every registry that outlives a year of real data entry ends up with the
> same person in it twice, spelled two different ways."*

---

## Background

Full-text search, from the last chapter, is built for a specific kind of
imprecision: the same *word*, inflected differently ("vote", "voted",
"voting"). It does nothing for a different, equally common kind of
imprecision — the same word, **spelled** differently. "Portsmith" typed as
"Portsmith" versus "Portsmyth". "McAllister" versus "MacAllister". A
resident registry filled in by hand, twice, by two different clerks, on two
different days. Stemming cannot fix a typo, because a typo isn't a
grammatical variant of the correct word — it's a different string that a
human reader recognizes as "close enough" and a computer, by default, does
not.

`pg_trgm` is PostgreSQL's answer: it breaks strings into overlapping
three-character sequences (**trigrams**) and measures how many trigrams two
strings share. Two spellings of the same name share most of their trigrams
even when several letters differ; two unrelated strings usually share
almost none. That single idea — measured, thresholded, and indexed — is
enough to power "did you mean?" search boxes, deduplicate messy records, and
accelerate substring `LIKE` queries that would otherwise force a sequential
scan.

This chapter builds a small deduplication and search tool around that idea:
what a trigram actually is, how `similarity()` scores a pair of strings, how
to turn that into an index instead of an O(n²) scan, and — the harder,
more honest part — where trigram matching's judgment calls are, because no
similarity threshold gets every case right.

---

## The Scenario

Portsmith's resident registry has been filled in over years by different
staff at different counters, and it shows: the same person appears twice
under two spellings of their name often enough that nobody trusts a raw
`COUNT(*)` on it anymore. Separately, the city's 311 line fields phone
searches for local businesses, and callers rarely spell a business name
correctly on the first try.

Two tables model this:

| Table            | Purpose                                                                 |
|-------------------|--------------------------------------------------------------------------|
| `residents`       | Synthetic residents, including intentional near-duplicate entries — the same person, typed twice, with a typo, transposition, or variant spelling the second time |
| `business_names`  | A flat `(business_id, name)` lookup extending the `businesses` table from Chapter 1, used for "did you mean?" search |

`residents` includes a `true_duplicate_of` column that a real registry would
**not** have — you would not know in advance which rows are duplicates; that
is the entire problem fuzzy matching exists to solve. It's here purely so
the exercises can check whether your queries found the right answers. The
dataset also includes two pairs that are deliberately *not* marked as
duplicates, on purpose — more on those in Exercise 2.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Explain what a trigram is and compute `similarity()` between two strings
  by hand for a short example.
- Use the `%` operator to find near-matches at a configurable similarity
  threshold, and explain why no single threshold is perfectly correct.
- Use `word_similarity()` to find a short query as a strong partial match
  inside a longer string, and explain how it differs from `similarity()`.
- Create a GIN trigram index and confirm it accelerates both `%` and
  `LIKE '%term%'` queries that would otherwise force a sequential scan.
- Build a "did you mean?" query using a GiST trigram index and `ORDER BY
  ... <->`, and explain why GiST — not GIN — is the right index for that
  access pattern.
- Compare trigram matching against full-text search on the same kind of
  short, keyword-style query, and know which one to reach for.

---

## Installation

`pg_trgm` ships as part of the standard `postgresql-16` package on
Debian/Ubuntu — unlike PostGIS in Chapter 2, there is no separate package to
install. Enable it in the database:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

---

## Loading the Data

### Prerequisites

Chapter 1's seed script must have been run first — `business_names` is
populated directly from the `businesses` table:

```bash
python data/ch01_seed.py
```

### Run the Chapter 5 seed

```bash
python data/ch05_seed.py
```

Expected output:

```
Connecting to: dbname=portsmith
Creating schema …
Inserting 58 residents …
Populating business_names from businesses …
Done — 58 rows in residents, 48 rows in business_names.
```

### Verify the load

Open `psql portsmith` and run these checks.

**Check 1 — table structure:**

```sql
\d residents
```

```
                                  Table "public.residents"
      Column       |  Type   | Collation | Nullable |                Default
-------------------+---------+-----------+----------+---------------------------------------
 id                | integer |           | not null | nextval('residents_id_seq'::regclass)
 full_name         | text    |           | not null |
 neighbourhood     | text    |           | not null |
 true_duplicate_of | integer |           |          |
Indexes:
    "residents_pkey" PRIMARY KEY, btree (id)
Foreign-key constraints:
    "residents_true_duplicate_of_fkey" FOREIGN KEY (true_duplicate_of) REFERENCES residents(id)
Referenced by:
    TABLE "residents" CONSTRAINT "residents_true_duplicate_of_fkey" FOREIGN KEY (true_duplicate_of) REFERENCES residents(id)
```

**Check 2 — every marked duplicate points at a real canonical row:**

```sql
SELECT COUNT(*) AS duplicate_pairs
FROM   residents
WHERE  true_duplicate_of IS NOT NULL;
```

```
 duplicate_pairs
-----------------
              12
```

**Check 3 — `business_names` mirrors `businesses` 1:1:**

```sql
SELECT COUNT(*) FROM business_names;
```

```
 count
-------
    48
```

If all three match, proceed to the exercises.

---

## Exercises

---

### Exercise 1 — What a Trigram Is, and `similarity()`

**1.1 — Break a string into trigrams**

`show_trgm()` returns the actual set of trigrams PostgreSQL generates for a
string:

```sql
SELECT show_trgm('Eleanor');
```

```
                show_trgm
-------------------------------------------
 {"  e"," el",ano,ean,ele,lea,nor,"or "}
```

Before splitting, PostgreSQL pads the string with two leading spaces and one
trailing space — `"  eleanor "` — then takes every overlapping run of three
characters: `"  e"`, `" el"`, `"ele"`, `"lea"`, `"ean"`, `"ano"`, `"nor"`,
`"or "`. The padding matters: it means the first and last letters of a word
each get their own distinguishing trigram (`"  e"` marks "starts with e";
`"or "` marks "ends with or"), so two strings that only differ at the very
start or end still register as different rather than accidentally looking
identical in the middle.

<img src="imgs/ch05_trigram_window.svg" alt="A 3-character window sliding one position at a time across the padded string '  eleanor ', producing the 8 overlapping trigrams: '  e', ' el', ele, lea, ean, ano, nor, 'or '"/>

**1.2 — `similarity()`: how much overlap, as a fraction**

```sql
SELECT similarity('Eleanor Whitmore', 'Elenor Whitmore');
```

```
 similarity
------------
  0.7368421
```

`similarity()` compares the trigram sets of both strings and returns
roughly the fraction that overlap — mostly shared trigrams (both names are
16-17 characters, differing by one dropped letter) means a high score close
to 1. Two unrelated strings — "Eleanor Whitmore" and, say, "Ironside Auto"
— share almost no trigrams and score close to 0. The scale is intuitive by
construction: 1.0 is identical, 0.0 is nothing alike.

**1.3 — All twelve duplicate pairs, scored**

```sql
SELECT a.full_name AS canonical, b.full_name AS duplicate_entry,
       round(similarity(a.full_name, b.full_name)::numeric, 3) AS sim
FROM   residents a
JOIN   residents b ON b.true_duplicate_of = a.id
ORDER  BY a.id;
```

```
      canonical        |    duplicate_entry     |  sim
------------------------+------------------------+-------
 Eleanor Whitmore       | Elenor Whitmore        | 0.737
 Jonathan Castellano    | Jonathon Castellano    | 0.739
 Priyanka Deshmukh      | Priyanka Deshmuk       | 0.842
 Bartholomew Okonkwo    | Bartholemew Okonkwo    | 0.739
 Marguerite Delacroix   | Marguerite Delacroiux  | 0.792
 Siobhan McAllister     | Siobhan MacAllister    | 0.773
 Theodore Vance         | Theodor Vance          | 0.813
 Anastasia Volkov       | Anastassia Volkov      | 0.842
 Desmond Okafor         | Desmund Okafor         | 0.667
 Genevieve Laurent      | Genevieve Lorent       | 0.667
 Mikhail Petrenko       | Mikail Petrenko        | 0.737
 Fitzgerald Osei        | Fitzgerld Osei         | 0.722
```

Every genuine duplicate in this dataset scores well above 0.6, regardless
of whether the typo was a dropped letter, a swapped letter, or a spelling
variant. That range is the working intuition Exercise 2 turns into an
actual threshold.

---

### Exercise 2 — The `%` Operator, and Why One Threshold Isn't Enough

**2.1 — `%`: "similar enough," using a session-wide threshold**

Computing `similarity()` for every pair by hand doesn't scale. The `%`
operator wraps it into a boolean test against a configurable cutoff:

```sql
SHOW pg_trgm.similarity_threshold;
```

```
 pg_trgm.similarity_threshold
-------------------------------
 0.3
```

`0.3` is the default. Self-join `residents` against itself to find every
pair of *different* rows that clears it — this is the actual "find likely
duplicates" query:

```sql
SELECT a.id, a.full_name, b.id, b.full_name,
       round(similarity(a.full_name, b.full_name)::numeric, 3) AS sim
FROM   residents a
JOIN   residents b ON a.id < b.id
WHERE  a.full_name % b.full_name
ORDER  BY sim DESC, a.id;
```

```
 id |      full_name       | id |       full_name       |  sim
----+-----------------------+----+------------------------+-------
 35 | Priyanka Deshmukh     | 36 | Priyanka Deshmuk       | 0.842
 45 | Anastasia Volkov      | 46 | Anastassia Volkov      | 0.842
 43 | Theodore Vance        | 44 | Theodor Vance          | 0.813
 39 | Marguerite Delacroix  | 40 | Marguerite Delacroiux  | 0.792
 41 | Siobhan McAllister    | 42 | Siobhan MacAllister    | 0.773
 57 | Nadia Kowalski        | 58 | Nadia Kowalska         | 0.765
 33 | Jonathan Castellano   | 34 | Jonathon Castellano    | 0.739
 37 | Bartholomew Okonkwo   | 38 | Bartholemew Okonkwo    | 0.739
 31 | Eleanor Whitmore      | 32 | Elenor Whitmore        | 0.737
 51 | Mikhail Petrenko      | 52 | Mikail Petrenko        | 0.737
 53 | Fitzgerald Osei       | 54 | Fitzgerld Osei         | 0.722
 47 | Desmond Okafor        | 48 | Desmund Okafor         | 0.667
 49 | Genevieve Laurent     | 50 | Genevieve Lorent       | 0.667
 55 | Robert Ashworth       | 56 | Bobby Ashworth         | 0.409
(14 rows)
```

`a.id < b.id` keeps each pair once instead of twice (A-vs-B and B-vs-A are
the same comparison). Notice: **fourteen** rows came back, not twelve. Check
`true_duplicate_of` on every row involved and you'll find twelve of these
pairs marked as genuine duplicates and two that are not — "Nadia Kowalski"
/ "Nadia Kowalska" and "Robert Ashworth" / "Bobby Ashworth". They're in
this dataset on purpose, and — this is the point of the exercise — look at
*where* they landed in the ranking.

**2.2 — A false positive sitting in the middle of the true positives**

"Nadia Kowalski" and "Nadia Kowalska" are two unrelated Riverside
residents who happen to share a first name and a Polish surname that
differs only in its masculine/feminine ending. Their similarity, `0.765`,
isn't an edge case at the bottom of the list — it sits **between** "Siobhan
McAllister"/"Siobhan MacAllister" (`0.773`) and "Bartholomew Okonkwo"/
"Bartholemew Okonkwo" (`0.739`), two genuine duplicates. `similarity()` is
doing exactly what it's designed to do: these two strings really are that
close. Whether that means "probably the same person" is a judgment call
the function cannot make on its own — the central limitation of fuzzy
matching. It finds **candidates**, not verified duplicates. A production
dedup pipeline treats a `%` match as "flag for review" or "compare a
second field too" (a shared phone number or address), never as "merge
automatically."

**2.3 — Prove no threshold fixes it**

Try to set a threshold that excludes the Kowalski pair:

```sql
SET pg_trgm.similarity_threshold = 0.77;
```

Re-run the query from 2.1. "Nadia Kowalski"/"Nadia Kowalska" (`0.765`) is
gone — but so are seven of the twelve genuine duplicates, everything
scoring below `0.77`. There is no number you can put in that `SET`
statement that keeps all twelve real duplicates and excludes the Kowalski
pair, because a real duplicate ("Bartholomew Okonkwo"/"Bartholemew
Okonkwo", `0.739`) scores *lower* than the false positive you're trying to
exclude. Put the threshold back before continuing:

```sql
SET pg_trgm.similarity_threshold = 0.3;
```

**2.4 — A different failure: the false negative you'd never even see**

"Robert Ashworth" and "Bobby Ashworth" are, in this dataset's backstory,
the same person — entered once with a nickname. Notice they only made the
results list at all (`0.409`) because of the shared surname "Ashworth"; as
given names alone, "Robert" and "Bobby" share nothing:

```sql
SELECT similarity('Robert', 'Bobby');
```

```
 similarity
------------
          0
```

A resident with a *less* distinctive shared surname and a nicknamed given
name would score near zero overall and never appear in a `%` results list
at any threshold — not a borderline case to review, just silently absent.
`similarity()` measures string closeness, not identity; it has no way to
know "Bobby" is short for "Robert" unless something else tells it, such as
a synonym table consulted alongside it.

**2.5 — The honest takeaway**

Between the Kowalski pair and the Ashworth pair, this dataset has one
false positive that no threshold can cleanly exclude without also losing
real duplicates, and one true duplicate that scores so low it would never
surface as a candidate in the first place. Tune
`pg_trgm.similarity_threshold` to trade recall against precision for your
own data — but go in expecting a trade-off, not a number that gets both
sides to zero.

---

### Exercise 3 — `word_similarity()` for Partial Matches

`similarity()` compares two whole strings — it penalizes a short query
against a long target just for being different lengths, which makes it a
poor fit for "does this short input appear as a strong match somewhere
inside this longer string?"

**3.1 — Compare the two functions on the same query**

```sql
SELECT name, round(similarity('bake', name)::numeric, 3) AS full_sim
FROM   business_names
ORDER  BY full_sim DESC, name
LIMIT  3;
```

```
          name          | full_sim
-------------------------+----------
 River Bend Bakery       |    0.222
 Campus Bike & Sports    |    0.091
 Finch & Sons Barbers    |    0.091
```

```sql
SELECT name, round(word_similarity('bake', name)::numeric, 3) AS word_sim
FROM   business_names
ORDER  BY word_sim DESC, name
LIMIT  3;
```

```
          name          | word_sim
-------------------------+----------
 River Bend Bakery       |    0.800
 Bay Street Electronics  |    0.400
 Finch & Sons Barbers    |    0.400
```

Same query, same top result, very different score: `0.222` versus `0.800`.
`word_similarity()` finds the best-matching *substring extent* inside the
target — effectively "if I could crop this longer string down to the part
that best matches my query, how similar would that piece be?" — rather than
scoring the query against the target's full length. "bake" against "River
Bend **Bake**ry" scores high because "Bake" is a near-perfect fragment
match, even though "bake" is a small fraction of the full business name.

**3.2 — When to reach for which**

Use `similarity()` when you're comparing two values that *should* represent
the same whole thing — two spellings of one name, as in Exercises 1 and 2.
Use `word_similarity()` when a short query is expected to be a fragment of
a longer field — autocomplete-style search-as-you-type, or matching a
partial business name a caller remembers.

---

### Exercise 4 — GIN Trigram Indexes

**4.1 — Without an index**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT name FROM business_names WHERE name LIKE '%Bakery%';
```

```
                                                QUERY PLAN
------------------------------------------------------------------------------------------------------
 Seq Scan on business_names  (cost=0.00..25.88 rows=1 width=32) (actual time=0.008..0.009 rows=1 loops=1)
   Filter: (name ~~ '%Bakery%'::text)
   Rows Removed by Filter: 47
   Buffers: shared hit=1
```

A plain B-tree index cannot help here — `%Bakery%` has no fixed prefix, so
there's nothing for a B-tree to seek to. This is exactly the case `pg_trgm`
was built for: it indexes every trigram in every row, so a `LIKE` pattern
(itself broken into trigrams) can be looked up directly.

**4.2 — Create the index**

```sql
CREATE INDEX idx_business_names_trgm
    ON business_names
    USING GIN (name gin_trgm_ops);
```

**4.3 — Confirm it's used**

As in earlier chapters, force the index on a table this small to see the
mechanism:

```sql
SET enable_seqscan = off;

EXPLAIN (ANALYZE, BUFFERS)
SELECT name FROM business_names WHERE name LIKE '%Bakery%';

SET enable_seqscan = on;   -- always restore this
```

```
                                                           QUERY PLAN
-----------------------------------------------------------------------------------------------------------------------------
 Bitmap Heap Scan on business_names  (cost=21.82..25.83 rows=1 width=32) (actual time=0.024..0.025 rows=1 loops=1)
   Recheck Cond: (name ~~ '%Bakery%'::text)
   Heap Blocks: exact=1
   Buffers: shared hit=10
   ->  Bitmap Index Scan on idx_business_names_trgm  (cost=0.00..21.82 rows=1 width=0) (actual time=0.016..0.017 rows=1 loops=1)
         Index Cond: (name ~~ '%Bakery%'::text)
         Buffers: shared hit=9
```

`Bitmap Index Scan on idx_business_names_trgm` — the same GIN index also
accelerates `%`, `word_similarity() %>`, and both `LIKE` and `ILIKE` with
leading wildcards, all from one index.

---

### Exercise 5 — A "Did You Mean?" Query with GiST

**5.1 — The pattern: order by trigram distance, take the top few**

`pg_trgm` defines a distance operator, `<->` — the complement of
similarity (smaller means more alike) — which makes "closest matches
first" a plain `ORDER BY ... LIMIT`:

```sql
SELECT name, round(similarity(name, 'Ironsyde Auto')::numeric, 3) AS sim
FROM   business_names
ORDER  BY name <-> 'Ironsyde Auto', name
LIMIT  5;
```

```
        name         |  sim
----------------------+-------
 Ironside Auto        | 0.647
 AutoFix Portsmith    | 0.143
 Harbour Inn          | 0.040
 The Art Depot        | 0.037
 Riverside Cinema     | 0.033
```

A caller who typed "Ironsyde Auto" (transposed letters) gets "Ironside
Auto" back as the clear top match, well clear of the noise below it — this
is the entire "did you mean?" feature.

**5.2 — Why the GIN index from Exercise 4 doesn't help here**

```sql
EXPLAIN (ANALYZE)
SELECT name FROM business_names
ORDER BY name <-> 'Ironsyde Auto'
LIMIT  5;
```

```
                                                      QUERY PLAN
-----------------------------------------------------------------------------------------------------------------------
 Limit  (cost=2.40..2.41 rows=5 width=36) (actual time=0.182..0.183 rows=5 loops=1)
   ->  Sort  (cost=2.40..2.52 rows=48 width=36) (actual time=0.181..0.182 rows=5 loops=1)
         Sort Key: ((name <-> 'Ironsyde Auto'::text))
         Sort Method: top-N heapsort  Memory: 25kB
         ->  Seq Scan on business_names  (cost=0.00..1.60 rows=48 width=36) (actual time=0.040..0.157 rows=48 loops=1)
```

Even with `idx_business_names_trgm` in place, this plan is a full scan plus
a sort — GIN accelerates *lookups* ("which rows contain trigrams matching
this pattern") but has no notion of a distance ordering. Nearest-neighbor
queries need an index that natively understands "closest," which is what
**GiST** provides:

```sql
CREATE INDEX idx_business_names_trgm_gist
    ON business_names
    USING GIST (name gist_trgm_ops);
```

```sql
EXPLAIN (ANALYZE)
SELECT name FROM business_names
ORDER BY name <-> 'Ironsyde Auto'
LIMIT  5;
```

```
                                                                     QUERY PLAN
-------------------------------------------------------------------------------------------------------------------------------------------------------
 Limit  (cost=0.14..1.07 rows=5 width=36) (actual time=0.130..0.143 rows=5 loops=1)
   ->  Index Scan using idx_business_names_trgm_gist on business_names  (cost=0.14..9.09 rows=48 width=36) (actual time=0.129..0.141 rows=5 loops=1)
         Order By: (name <-> 'Ironsyde Auto'::text)
```

`Order By: (name <-> 'Ironsyde Auto'::text)` inside an `Index Scan` — the
GiST index walks straight to the nearest rows instead of scoring and
sorting every row in the table. **Rule of thumb: GIN for `%`/`LIKE`
membership lookups, GiST for `ORDER BY ... <-> ... LIMIT n` nearest-match
queries.** It's common to keep both, as this table now does, if an
application needs both access patterns.

**5.3 — One more example**

```sql
SELECT name, round(similarity(name, 'Portsmith Vetrinary Clinic')::numeric, 3) AS sim
FROM   business_names
ORDER  BY name <-> 'Portsmith Vetrinary Clinic', name
LIMIT  5;
```

```
            name              |  sim
-------------------------------+-------
 Portsmith Veterinary Clinic   | 0.833
 AutoFix Portsmith             | 0.286
 Portsmith Pharmacy            | 0.286
 Portsmith Tailors             | 0.286
 Portsmith Arms Hotel          | 0.263
```

---

### Exercise 6 — Trigram Matching vs. Full-Text Search, Head to Head

Chapter 4 built full-text search over `city_documents`; this chapter built
trigram matching over `business_names`. Both can answer "find rows
matching this word" — they are good at it for different, almost opposite,
reasons.

**6.1 — A spelling variant: trigram wins**

Portsmith's own documents consistently use the British spelling
"harbour." A caller who types the American spelling "harbor" gets nothing
from full-text search — stemming normalizes *inflection* ("harbors" →
"harbor"), not *spelling*:

```sql
SELECT to_tsvector('english', 'Harbour View Theater') @@ to_tsquery('english', 'harbor');
```

```
 ?column?
----------
 f
```

Trigram similarity doesn't care that they're "different words" — it only
sees how many three-letter fragments overlap, and "harbor"/"harbour" share
almost all of theirs:

```sql
SELECT similarity('harbor', 'harbour');
```

```
 similarity
------------
        0.5
```

**6.2 — A short, correctly-spelled keyword: full-text search wins**

Run a short, exact keyword against `business_names` both ways:

```sql
SELECT name, round(similarity(name, 'bay')::numeric, 3) AS sim
FROM   business_names
ORDER  BY sim DESC, name
LIMIT  6;
```

```
          name           |  sim
--------------------------+-------
 Mango Bay Caribbean      | 0.200
 Bay Street Electronics   | 0.174
 River Bend Bakery        | 0.105
 Finch & Sons Barbers     | 0.095
 Bella Napoli             | 0.063
 Le Petit Bistro          | 0.053
```

A three-letter query like "bay" barely produces any trigrams of its own,
so the scores are all low and close together — "River Bend Bakery" and
"Finch & Sons Barbers" show up with real, if small, similarity despite
having nothing to do with "bay." There's no clean gap between signal and
noise. Full-text search, which matches on whole tokens rather than
character fragments, has no such problem:

```sql
SELECT name FROM business_names
WHERE  to_tsvector('english', name) @@ plainto_tsquery('english', 'bay')
ORDER  BY name;
```

```
          name
------------------------
 Bay Street Electronics
 Mango Bay Caribbean
(2 rows)
```

Exactly the two relevant matches, no noise, no threshold to tune.

**6.3 — The rule of thumb**

Short queries made of correctly-spelled whole words belong to full-text
search — it was built to match tokens precisely and cheaply via a GIN
index over lexemes. Queries that might be misspelled, transposed, or
OCR-damaged belong to trigram matching — it was built to tolerate exactly
that kind of noise, at the cost of weaker signal on very short inputs. Many
real search boxes run both: try full-text search first, and fall back to a
trigram "did you mean?" only when it returns nothing.

---

## Summary — What You Should Now Know

| Tool | What it does |
|------|-------------|
| `show_trgm(text)` | Shows the padded, overlapping 3-character sequences a string breaks into |
| `similarity(a, b)` | Fraction of shared trigrams between two whole strings — best for "are these two values the same thing, spelled differently?" |
| `word_similarity(a, b)` | Best-matching substring extent of `a` inside `b` — best for "is `a` a fragment somewhere inside `b`?" |
| `a % b` | Boolean test: does `similarity(a, b)` clear `pg_trgm.similarity_threshold` (default `0.3`)? |
| `a <-> b` | Trigram distance (`1 - similarity`) — sort by this for nearest-match-first results |
| `GIN (col gin_trgm_ops)` | Accelerates `%` and `LIKE`/`ILIKE` membership-style lookups |
| `GIST (col gist_trgm_ops)` | Accelerates `ORDER BY col <-> query LIMIT n` nearest-neighbor lookups |
| `pg_trgm.similarity_threshold` | Session-level cutoff for `%`; tune it, but expect trade-offs, not a perfect split |

**The key design insight** from this chapter is that fuzzy matching
produces *candidates*, not verdicts. The `%` operator surfaced all twelve
real duplicate pairs in the `residents` table — and two pairs of genuinely
different, or differently-named, people right alongside them, at every
threshold tried. That isn't a shortcoming to engineer away; it's the
nature of measuring string similarity instead of identity. Build fuzzy
matching into a review queue or a secondary confirmation step, not an
automatic merge.

The `business_names` table you built here is reused in Chapter 10
(PostgREST), which exposes the "did you mean?" query from Exercise 5 as a
public RPC endpoint.

---

*Going further: `pg_trgm` also provides `%>` and `<->>` variants tuned for
`word_similarity()` rather than `similarity()`, useful for indexing
substring-style "did you mean?" search the same way Exercise 5 indexed
whole-string search. For very large tables, GiST trigram indexes are
typically smaller and faster to build than GIN but slower for pure
membership lookups — benchmark both on your actual data distribution
rather than assuming one is strictly better. And if deduplication is a
recurring, business-critical process rather than an occasional query,
look at dedicated record-linkage tools (e.g. the `dedupe` Python library),
which combine trigram-style string similarity with other fields — address,
phone number, date of birth — and a trained classifier, instead of a single
threshold on a single column.*
