# Chapter 22 — RDF Triple Stores: `pg-ripple`

> *Everything so far in this book has been rows, or documents shaped
> like rows. This chapter asks what happens when the unit of storage
> is a single fact — subject, predicate, object — and the query
> language is built around walking a graph of those facts rather than
> joining tables of them.*

---

## Background

RDF (the Resource Description Framework) models data as **triples**:
`subject predicate object`, e.g. `:business_1 :locatedIn
:harbour_district`. A whole database becomes one large set of these
facts, queried with **SPARQL** rather than SQL. `pg-ripple`
(`github.com/trickle-labs/pg-ripple`) brings this model into
PostgreSQL as a real extension — not an ORM convention on top of
ordinary tables, but genuine triple storage, a SPARQL 1.1 query engine,
SHACL validation, and a Datalog-based reasoning engine, all installed
with `CREATE EXTENSION`.

This is the third time this book has modeled the same kind of question
— "how are things connected" — with a different tool:

- **Chapter 1 (JSONB)** models irregular *attributes* of a single
  document. It doesn't model relationships between documents at all.
- **Chapter 12 (recursive CTEs) and Chapter 21 (SQL/PGQ)** model
  relationships as edges between *rows in tables you already have*,
  queried either by hand-written recursion or, as of PostgreSQL 19
  beta2, fixed-depth graph pattern matching.
- **This chapter** models relationships as first-class facts, with no
  underlying table shape at all — a business's category, its
  neighborhood, and a neighborhood's population are all just more
  triples, indistinguishable in storage from the edges connecting them.

The honest throughline from Chapter 21 continues here: `pg-ripple` is
real, working software, verified live against an actual build — and,
same as Chapter 21, hands-on testing surfaced genuine gaps between what
the README advertises and what this specific version actually does
correctly. Two of this chapter's exercises exist *because* of gaps
found this way, not despite them.

---

## The Scenario

A slice of the Portsmith domain, recast as triples: the 48 rows of
`businesses` (Chapter 1) and the 6 rows of `neighborhoods` (Chapter 2),
plus a genuinely new fact with no earlier equivalent — real
**neighborhood adjacency**, derived from Chapter 2's actual polygon
geometry via `ST_Touches`, not invented. This mirrors Chapter 12's own
practice of deriving graph edges from real geometry rather than making
them up, and sets up a direct rerun of Chapter 21's central finding: an
"is X reachable from Y" question, asked of two different graph engines.

Like Chapter 21, this runs in its own isolated PostgreSQL container —
version 18, matching what `pg-ripple`'s own README documents support
for, not 19 (see the Environment Setup below for why that distinction
mattered in practice).

---

## Exercise Goals

By the end of this chapter you will be able to:

- Build a real Rust/`pgrx` PostgreSQL extension from source and know
  the specific version-pinning trap that broke the first attempt.
- Export relational rows as Turtle triples and load them with
  `pg_ripple.load_turtle()`.
- Write real SPARQL `SELECT` queries, including aggregation.
- Use SPARQL property paths for unbounded-depth traversal — and know
  exactly why this succeeds here when the equivalent quantified path
  failed in Chapter 21's PostgreSQL 19 beta2.
- Define a SHACL shape and get a real, precise violation report — and
  know which part of SHACL support (scoring) works today versus which
  part (insert-time rejection) needs a second extension not installed
  here.
- Write a custom Datalog inference rule — and know, from a reproduced,
  isolated test, exactly how this build's rule engine fails to chain
  a two-atom rule body correctly.

---

## Environment Setup — Compiling a Rust Extension

`pg-ripple` isn't an apt package like anything earlier in this book —
it's a Rust project built against real PostgreSQL server headers via
`pgrx`, PostgreSQL's Rust extension framework. `docker/ch22/` builds
it from scratch, on **PostgreSQL 18** (GA, unlike Chapter 21's
PostgreSQL 19 beta2 — `pg-ripple`'s own README documents support for
18, and there was no reason to add PostgreSQL 19's own beta
uncertainty on top of a Rust build that had plenty of its own).

Bring it up:

```bash
cd docker/ch22
docker compose up --build
```

Two real build failures happened getting there, both worth knowing if
you build a `pgrx` extension yourself:

**1. `cargo install cargo-pgrx --version` wants a full version, not a
bare `major.minor`.** `--version "0.18"` fails outright
(`unexpected end of input while parsing minor version number`); it
needs either a specific version or an explicit range qualifier.

**2. `cargo-pgrx`'s own version must exactly match the `pgrx` library
version pinned in the extension's `Cargo.toml` — a loose range match
isn't good enough.** The natural fix for problem 1 looked like
`--version "^0.18"`, which resolved to the newest `0.18.x` release
(`0.18.1`) — but pg-ripple's `Cargo.toml` pins `pgrx = 0.18.0` exactly,
and `cargo-pgrx` itself refuses to proceed when its own version
doesn't match, with a real, specific error naming the exact version it
wants:

```
Error:
   0: The installed cargo-pgrx 0.18.1 is not compatible with the dependencies in ./Cargo.toml:
      pgrx = 0.18.0, pgrx-macros = 0.18.0, pgrx-sql-entity-graph = 0.18.0, pgrx-tests = 0.18.0
      cargo-pgrx and pgrx library versions must be identical.
      help: cargo install cargo-pgrx --version 0.18.0 --locked
```

The fix, exactly as the error suggests: pin the exact version,
`cargo install --locked cargo-pgrx --version "0.18.0"`.

Building the cluster itself reused Chapter 21's `pg_dropcluster --stop
18 main` fix for Debian's config/data-splitting auto-created cluster,
and the same `initdb --auth-local=trust` fix for the OS-user/role-name
mismatch — both explained in Chapter 21's Environment Setup, not
repeated here.

**One more real gotcha, found only after the extension was already
running:** the first `CREATE EXTENSION pg_ripple` and first `sparql()`
call both worked, but printed a real warning:

```
WARNING:  pg_ripple: loaded without shared_preload_libraries; HTAP merge
worker, CONSTRUCT writeback, and dictionary cache are disabled. Add
pg_ripple to shared_preload_libraries in postgresql.conf.
```

Exactly the same class of gotcha Chapters 19 and 20 hit with
`pg_cron`/`pg_stat_statements`/`auto_explain` — some of `pg-ripple`'s
functionality needs to be loaded at server-start time, not merely
`CREATE EXTENSION`-ed into a running one. Fixed in `entrypoint.sh` by
writing `shared_preload_libraries = 'pg_ripple'` into
`postgresql.conf` *before* the first `pg_ctl start`, not after:

```
$ psql -h localhost -p 5434 -U chris -d portsmith22 -c "\dx pg_ripple"
  pg_ripple | 0.128.0 | public | High-performance RDF triple store with SPARQL 1.1, SHACL, Datalog, HTAP, federation, and Datalog-native PageRank
```

---

## Exercises

### Exercise 1 — Exporting Real Rows as Triples

`data/ch22_export_turtle.py` connects to the *live* PostgreSQL 16
`portsmith` database — not this chapter's scratch container — and
writes real rows as Turtle:

```bash
python3 data/ch22_export_turtle.py "dbname=portsmith" data/ch22_portsmith.ttl
```

```
Wrote 6 neighborhoods, 10 adjacency edges, 48 businesses to data/ch22_portsmith.ttl
```

The 10 adjacency edges are genuinely derived, not invented — the exact
same `ST_Touches` technique Chapter 12 used for its road-intersection
graph, applied here to Chapter 2's neighborhood polygons:

```sql
SELECT a.name, b.name
FROM neighborhoods a
JOIN neighborhoods b ON a.id < b.id AND ST_Touches(a.geom, b.geom);
```

A sample of the output Turtle:

```turtle
@prefix : <http://portsmith.example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:harbour_district a :Neighborhood ; rdfs:label "Harbour District" ; :population 4200 ; :partOf :portsmith .
:harbour_district :adjacentTo :industrial_port .
:business_1 a :Business ; rdfs:label "The Gilded Clam" ; :locatedIn :harbour_district ; :hasCategory "restaurant" .
```

Loading it into the `pg-ripple` container — note the loader connects
to the *container* (port 5434), reading the file this script just
wrote:

```python
with psycopg.connect("host=localhost port=5434 ... dbname=portsmith22") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_ripple.load_turtle(%s, false);", (ttl,))
        print("Triples loaded:", cur.fetchone()[0])
    conn.commit()
```

```
Triples loaded: 261
```

Passing the Turtle content as a bind parameter, rather than trying to
shell-escape it into a `psql -c` call, sidesteps a real amount of pain
— Turtle syntax is full of the exact characters (colons, angle
brackets, quotes) that are worst to quote correctly in a shell.

---

### Exercise 2 — Real SPARQL, Including Aggregation

```sql
SELECT * FROM pg_ripple.sparql('
PREFIX : <http://portsmith.example.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?nlabel (COUNT(?b) AS ?n) WHERE {
  ?b a :Business ; :locatedIn ?nb .
  ?nb rdfs:label ?nlabel .
} GROUP BY ?nlabel ORDER BY ?nlabel
');
```

```
                    result
------------------------------------------------
 {"n": 9, "nlabel": "\"Harbour District\""}
 {"n": 9, "nlabel": "\"Old Town\""}
 {"n": 9, "nlabel": "\"Northgate\""}
 {"n": 9, "nlabel": "\"Riverside\""}
 {"n": 5, "nlabel": "\"University Quarter\""}
 {"n": 7, "nlabel": "\"Industrial Port\""}
```

Real, correct, and a genuine test of the query engine, not just triple
storage — `GROUP BY`/`COUNT` over a join of three triple patterns, and
the six counts sum to exactly 48, the real business count. One
formatting quirk worth knowing before it surprises you: `sparql()`
returns `TABLE(result jsonb)`, and string-literal bindings keep their
RDF lexical quoting inside the JSON value (`"\"Harbour District\""`,
not `"Harbour District"`) — strip the outer quote pair in application
code rather than assuming a plain string.

---

### Exercise 3 — Property Paths: The Feature Chapter 21 Didn't Have

Chapter 21 ended on a wall: PostgreSQL 19 beta2's `GRAPH_TABLE`
rejected every form of variable-length path with `element pattern
quantifier is not supported`. SPARQL's equivalent — the `+`
(one-or-more) property path operator — is exactly the kind of
unbounded traversal that broke there. Try it here, on the real
adjacency data:

```sql
SELECT * FROM pg_ripple.sparql('
PREFIX : <http://portsmith.example.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?label WHERE {
  :harbour_district :adjacentTo+ ?n .
  ?n rdfs:label ?label .
} ORDER BY ?label
');
```

```
               result
-------------------------------------
 {"label": "\"Old Town\""}
 {"label": "\"Northgate\""}
 {"label": "\"Riverside\""}
 {"label": "\"University Quarter\""}
 {"label": "\"Industrial Port\""}
```

Real, unbounded, works — all five other neighborhoods, reached through
however many `adjacentTo` hops it takes. This is a genuine, verified
capability gap in this book's favor for once: the exact shape of query
that PostgreSQL 19 beta2 explicitly rejects, `pg-ripple`'s SPARQL
engine handles correctly.

Adjacency was only stored in one direction per pair (matching
`ST_Touches`'s symmetric result once, not twice), so a *directed* `+`
path from a node that's only ever the object of an edge would miss
real neighbors — the same directionality question Chapter 21 solved
with an undirected `-[ ]-` pattern. SPARQL's answer is the inverse-path
operator, `^`, combined with alternation:

```sql
SELECT * FROM pg_ripple.sparql('
PREFIX : <http://portsmith.example.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label WHERE {
  :northgate (:adjacentTo|^:adjacentTo)+ ?n .
  ?n rdfs:label ?label .
} ORDER BY ?label
');
```

```
               result
-------------------------------------
 {"label": "\"Harbour District\""}
 {"label": "\"Old Town\""}
 {"label": "\"Northgate\""}
 {"label": "\"Riverside\""}
 {"label": "\"University Quarter\""}
 {"label": "\"Industrial Port\""}
```

Six rows, not five — **Northgate appears in its own reachability set.**
Not a bug: the directed version of this same query
(`ASK { :northgate :adjacentTo+ ?n . FILTER(?n = :northgate) }`)
returns `false`, but the undirected version
(`ASK { :northgate (:adjacentTo|^:adjacentTo)+ :northgate }`) returns
`true` — because the *undirected* adjacency graph genuinely contains a
cycle: Northgate → Riverside → Harbour District → Old Town → Northgate.
`+` finds it correctly. This is Chapter 12 Exercise 4's cycle-detection
lesson again, from a completely different query language: an unbounded
traversal operator will walk straight into a real cycle and return the
start node as its own descendant unless you explicitly guard against
it (`FILTER(?n != :northgate)`, the SPARQL analog of Chapter 12's
`CYCLE ... SET ... USING`).

---

### Exercise 4 — SHACL: Real Scoring, Gated Enforcement

A SHACL shape requiring every `:Business` to have both a category and
a location:

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix : <http://portsmith.example.org/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:BusinessShape a sh:NodeShape ;
    sh:targetClass :Business ;
    sh:property [ sh:path :hasCategory ; sh:minCount 1 ; sh:datatype xsd:string ] ;
    sh:property [ sh:path :locatedIn ; sh:minCount 1 ] .
```

```sql
SELECT pg_ripple.load_shacl(:'shacl_text');
-- Shapes loaded: 1

SELECT pg_ripple.shacl_score('default');
-- shacl_score: 1     (fully conformant against the real, clean data)
```

Deliberately loading a malformed business — missing `:hasCategory` —
and re-scoring:

```turtle
:business_bad_1 a :Business ; rdfs:label "No Category Cafe" ; :locatedIn :harbour_district .
```

```sql
SELECT pg_ripple.shacl_score('default');
-- shacl_score: 0.5

SELECT pg_ripple.shacl_report_scored('default');
```

```
(http://portsmith.example.org/business_bad_1, http://portsmith.example.org/BusinessShape,
 Violation, 1, "expected at least 1 value(s) for <http://portsmith.example.org/hasCategory>, found 0")
```

Real, precise, and immediately actionable — names the exact offending
entity, shape, and missing property. But this is *scoring already-
stored data*, not *rejecting it at the door*. The README's "violations
caught on insert" claim is a different feature, gated behind
`enable_shacl_monitors()` — which, tried here, returns a clear real
answer rather than silently doing nothing:

```
WARNING:  pg_trickle is not installed; SHACL violation monitors are
unavailable. Install pg_trickle and run SELECT pg_ripple.enable_shacl_monitors()
to enable.
 enable_shacl_monitors
-----------------------
 f
```

A second extension, not built for this chapter. Real gap, honestly
reported rather than assumed away: as installed here, `pg-ripple`
validates on demand; it does not reject bad data on write.

Cleanup, using SPARQL 1.1 Update rather than reloading anything:

```sql
SELECT pg_ripple.sparql_update('
PREFIX : <http://portsmith.example.org/>
DELETE DATA { :business_bad_1 a :Business ; rdfs:label "No Category Cafe" ; :locatedIn :harbour_district . }
');
```

---

### Exercise 5 — Custom Datalog Rules: A Real, Reproduced Engine Bug

The guide's original plan for this exercise: a transitive rule —
"if X `locatedIn` Y and Y `partOf` Z, then X `partOf` Z" — inferring
that every business is part of Portsmith through its neighborhood.
Getting there required first finding the real rule syntax by iterating
against actual parser errors, the same technique Chapter 21 used for
`CREATE PROPERTY GRAPH`:

```sql
SELECT pg_ripple.validate_rule('partOf(?x, ?z) :- locatedIn(?x, ?y), partOf(?y, ?z) .');
-- ERROR-shaped result: expected 3 terms in triple pattern, got 2: partOf(?x, ?z)
```

Prolog-style `predicate(args)` functors aren't the syntax — rule heads
and body atoms have to be full RDF triple patterns, `subject predicate
object`, comma-separated in the body, one trailing period, and (found
by trial) full IRIs rather than an inline `PREFIX` line:

```sql
SELECT pg_ripple.validate_rule(
  '?x <http://portsmith.example.org/partOf> ?z :- ?x <http://portsmith.example.org/locatedIn> ?y , ?y <http://portsmith.example.org/partOf> ?z .'
);
-- {"valid": true, "warnings": [{"code": "UNUSED_BODY_VARIABLE", "message": "body variable ?y does not appear in the head"}]}
```

That warning turned out to matter. Loading the rule and running it
against the real 48-business dataset reported success —
`pg_ripple.infer('transitive_partof')` returned `1` — but querying the
actual result showed every business newly linked to its *neighborhood*
by `:partOf`, not to Portsmith. Wrong, and worth not trusting on faith
— confirmed with an isolated, minimal test to rule out anything about
the real dataset's shape being the cause:

```sql
-- fresh, tiny dataset: :a :locatedIn :b .  :b :partOf :c .
-- same rule, same predicates, isolated namespace
SELECT pg_ripple.infer('test_transitive');  -- inferred: 1
SELECT * FROM pg_ripple.sparql('PREFIX : <.../test/> SELECT ?p ?o WHERE { :a ?p ?o }');
```

```
 {"o": "<.../test/b>", "p": "<.../test/partOf>"}
 {"o": "<.../test/b>", "p": "<.../test/locatedIn>"}
```

`:a :partOf :b` — not the correct `:a :partOf :c`. The rule's second
body atom (`?y partOf ?z`) isn't actually constraining `?z`; the
engine is binding the head's `?z` to `?y` instead of chaining through
to the real join result. Reordering the body atoms (`partOf` first,
`locatedIn` second) produces the identical wrong answer, ruling out a
simple "only evaluates the first atom" explanation — whatever the
underlying cause, it's consistent and reproducible, not a fluke of
atom order. `pg_ripple.justify()`, the function meant to return a
proof tree for exactly this kind of question, returned an empty result
for both the correct and the actually-inferred triple — so the
"explainability" feature isn't independently confirming or denying
anything here either.

**The honest conclusion, matching Chapter 21's**: multi-atom custom
Datalog rule chaining does not work correctly in this build of
`pg-ripple`. `load_rules()`/`validate_rule()`/`infer()` all function —
they parse, load, and report a plausible-looking success count — but
the actual inference this exercise needed is wrong, verified by
checking the derived triple directly rather than trusting the success
message. (The wrong triples were cleaned up with `DELETE WHERE` —
which carries its own real gotcha, worth knowing before you reach for
it: a `DELETE WHERE` template with *multiple* triple patterns deletes
*every* pattern in the template for each matched solution, not just
the one you meant. `DELETE WHERE { ?s :partOf ?o . ?s a :Business . }`
correctly removed the wrong `:partOf` facts, but also silently deleted
all 48 real `rdf:type :Business` declarations along with them — caught
by re-checking the business count afterward, not assumed correct.)

---

## Decision Guide: RDF/SPARQL vs. Chapter 21's SQL/PGQ vs. Chapter 12's Recursive CTEs

| Need | Use |
|---|---|
| Unbounded-depth traversal today | `pg-ripple`'s SPARQL property paths (`+`, `*`, undirected `\|^`) — verified working; **or** Chapter 12's recursive CTEs. Not PostgreSQL 19 beta2's `GRAPH_TABLE` (Chapter 21) — quantified paths aren't implemented there yet. |
| Data that's naturally row-shaped, with a few graph-like relationships | Chapter 21's `GRAPH_TABLE` over existing tables, or a plain foreign key + recursive CTE — no reason to introduce a whole second data model for this |
| Data that's naturally fact-shaped — sparse, irregular attributes, relationships as first-class as the data itself | RDF/`pg-ripple` — closer to the actual shape of the problem than forcing it into either a fixed relational schema or JSONB |
| Schema/data validation with a real conformance report | `pg-ripple`'s SHACL scoring — real, working, precise. Insert-time enforcement needs `pg_trickle`, not verified here. |
| Rule-based inference over your own custom relationships | Not `pg-ripple`'s custom Datalog rules, as of this version — multi-atom chaining is broken, verified by direct testing, not by assumption |

---

<img src="imgs/ch22_verified_capabilities.svg" alt="Diagram listing pg-ripple capabilities actually tested against the real container, split into two groups. Verified working, green stroke: load_turtle, basic SPARQL SELECT with aggregation, SPARQL property paths including the undirected inverse combinator, SPARQL 1.1 Update, and SHACL scoring and violation reporting. Verified broken or gated, red stroke: SHACL insert time enforcement which requires the separate pg_trickle extension that is not installed, and custom Datalog rule chaining across multiple body atoms which was reproduced with an isolated minimal test and returns a wrong triple regardless of body atom order."/>

---

## Summary — What You Should Now Know

| Tool | What it's actually for |
|---|---|
| `pg_ripple.load_turtle()` | Bulk-loads Turtle triples — pass as a bind parameter, not shell-escaped text |
| `pg_ripple.sparql()` | Real SPARQL 1.1 `SELECT`, including aggregation — returns `TABLE(result jsonb)` with RDF lexical quoting preserved in string values |
| SPARQL property paths (`+`, `\|^`) | **Working, unbounded-depth traversal** — the exact capability PostgreSQL 19 beta2's `GRAPH_TABLE` doesn't have yet (Chapter 21) |
| `pg_ripple.shacl_score()` / `shacl_report_scored()` | Real, precise, on-demand conformance scoring |
| `enable_shacl_monitors()` | Gated behind a second extension (`pg_trickle`) not installed here — insert-time SHACL rejection isn't demonstrated working |
| `pg_ripple.load_rules()` / `infer()` | Parse and execute without error, but **multi-atom rule body chaining produces a wrong result**, reproduced on an isolated minimal dataset independent of atom order |
| `cargo-pgrx` version pinning | Must exactly match the `pgrx` version an extension's `Cargo.toml` pins — a semver range isn't sufficient |

**The key design insight** from this chapter is the same discipline
Chapter 21 needed, applied to a completely different piece of new
software: a young extension's README describes what it's *building
toward*, and the only way to know what actually works *today* is to
run it and check the output, not the success message. This chapter
found real wins (property paths genuinely outclass Chapter 21's current
`GRAPH_TABLE`) sitting right next to real gaps (custom rule chaining,
gated SHACL enforcement) — both equally worth knowing before reaching
for this in anything beyond a lab exercise.

---

*Going further: Chapter 23 builds directly on this chapter's working
parts — SPARQL, property paths, and SHACL scoring — layering a real
ontology (a class hierarchy, not just flat triples) on top, and pairing
it with Chapter 6's `pgvector` embeddings for hybrid retrieval. It
deliberately does not lean on this chapter's broken custom-rule
chaining; RDFS/OWL reasoning in Chapter 23 uses `pg-ripple`'s built-in
rule sets rather than hand-written Datalog, which is worth verifying
independently rather than assuming it avoids the same bug.*
