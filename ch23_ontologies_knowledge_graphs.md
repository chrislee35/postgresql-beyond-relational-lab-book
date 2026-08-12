# Chapter 23 — Ontologies and Knowledge Graphs for AI Workflows

> *Chapter 22 gave you a way to store facts and query them. This
> chapter asks what it takes to make those facts machine-checkable —
> and why that specific property, more than raw graph storage, is
> what modern AI systems actually want from a "knowledge graph."*

---

## Background

### What an ontology actually is

Every earlier chapter in this book that touched structure —
`CREATE TABLE`, a JSONB shape, a domain constraint, a foreign key —
was really describing *storage*: where a value lives and what type it
is. An **ontology** describes something narrower and more specific:
the *meaning* of a domain, made explicit enough that a machine can
check it and derive new facts from it. Formally, an ontology is a
**shared, explicit specification of a conceptualization** — a fixed
vocabulary of classes (`Restaurant`, `Neighborhood`), the relationships
between them (`locatedIn`, `partOf`), and rules about how they behave
(`Restaurant` is a kind of `Business`; anything `locatedIn` a
`Neighborhood` is thereby `partOf` the `City`). The word comes from
philosophy — the study of what exists — repurposed by computer science
for a narrower question: what *categories* of thing does this system
need to agree exist, and how do they relate?

This isn't a new idea invented for RDF. Library scientists have used
formal classification systems (Dewey Decimal, Library of Congress
Subject Headings) for over a century to make "what is this book
about" checkable and consistent across a collection, not just prose in
a librarian's head. Biology and medicine lean on ontologies constantly
— the Gene Ontology, SNOMED CT — specifically because "is X a kind of
Y" needs to mean the same thing to every system and every researcher
touching the data, not just to whoever wrote the current database
schema. `schema.org`, the vocabulary search engines use to understand
web page markup, is an ontology in exactly this sense: a shared
agreement, external to any one company's database, about what a
"Recipe" or an "Event" *is*.

A useful way to place the term among near-neighbors this book has
already used:

| Term | What it fixes | Example from this book |
|---|---|---|
| Schema | Storage shape — columns, types, constraints | Chapter 1's `businesses` table, Chapter 15's domains |
| Taxonomy | A single hierarchy of categories, no other relationships | Chapter 12's `categories` tree, as plain parent/child rows |
| Knowledge graph | Facts as a graph, however structured | Chapter 21's property graph; Chapter 22's raw triples |
| **Ontology** | **Formal *semantics* for a vocabulary — classes, hierarchies, and rules a machine can check and reason over** | **This chapter: Chapter 12's category tree, reissued as `rdfs:subClassOf` classes with checkable entailment** |

The distinction that matters most for this chapter: Chapter 22's
triples had *predicates* (`:hasCategory "seafood"`) but no *semantics*
attached to them — nothing in the store knew that `"seafood"` was a
kind of `"restaurant"`, or that a `Business` and its `Category` were
different *kinds* of thing at all. An ontology is what turns "seafood"
from an opaque string into `:Category_seafood`, a class with a real,
checkable position in a hierarchy — the same category data Chapter 12
already had, given a semantics a machine can act on rather than a
human reading the parent-child column pairs.

### Why this matters specifically for AI workflows

Three ways this shows up in real AI system design, not just as
database theory:

**1. Grounding.** An embedding model (Chapter 6) retrieves documents
that are *semantically similar* to a query — a genuinely powerful,
genuinely fuzzy notion of relevance. It has no concept of *correctness*:
a document can be the closest vector match to a question and still be
about the wrong neighborhood, the wrong department, or a policy that
no longer applies. An ontology backs that retrieval with facts a system
can actually check — not "this text sounds related," but "this
specific business, in this specific neighborhood, is actually a
member of the category this policy affects." Retrieval-augmented
generation systems that combine both are usually called **GraphRAG**
in current practice: embeddings for recall, a graph for precision.

**2. Context for agents.** An LLM agent given free-text "context" has
to re-parse and re-infer structure from prose every time. Given a
queryable ontology instead — a small, explicit model of what entities
and relationships actually exist in a domain — an agent can ask a
precise question ("which businesses does this ordinance affect?") and
get a precise, checkable answer, rather than asking a language model to
eyeball a paragraph and guess.

**3. Explainability.** A cosine-similarity score is a number with no
narrative — it can't tell you *why* two things are considered related,
only *how close*. A fact derived by rule-based reasoning over an
ontology comes with a real derivation: this business is a `Restaurant`
because it's a `seafood` restaurant, and `seafood rdfs:subClassOf
restaurant` is an asserted fact you can point to. Chapter 22's
`justify()` function gestures at exactly this — proof trees for
inferred facts — even though this chapter's own testing found it
doesn't reliably return one yet. The *goal* it's reaching for —
inference a system can explain, not just assert — is the real reason
symbolic methods keep showing up alongside purely statistical ones in
current AI system design, often described as **neuro-symbolic**:
neural methods for fuzzy recall, symbolic methods for checkable
structure.

None of this makes vector search obsolete, and this chapter's own
central exercise (below) doesn't either — it uses *both*, deliberately,
because they answer different questions.

---

## The Scenario

Two upgrades to material this book already has, both layered onto the
**same** `pg-ripple` container from Chapter 22 (`docker/ch22/`, no new
environment needed):

1. Chapter 12's `categories` table — 48 rows, a real 3-level tree
   (`All Categories` → 5 top categories → 42 specific
   subcategories/cuisines) — reissued as an `rdfs:subClassOf` class
   hierarchy, with every Chapter 1 business reclassified as an instance
   of its *specific* category class rather than Chapter 22's flat
   `:hasCategory` string.
2. Chapter 6's `pgvector` embeddings (still on the live PostgreSQL 16
   `portsmith` database — nothing about Chapter 6 changes) paired with
   this graph for hybrid retrieval, and Chapter 5's 12 real
   ground-truth duplicate resident pairs
   (`residents.true_duplicate_of`) reused as a head-to-head entity-
   resolution benchmark against `pg-ripple`'s own record-linkage
   functions.

Same discipline as Chapters 21 and 22: every claim below was checked
against a real, running instance. This chapter's single most important
finding is a warning, not a feature — found exactly this way.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Design a small class hierarchy by hand and load it as
  `rdfs:subClassOf` facts alongside existing instance data.
- Query class hierarchies with SPARQL property paths
  (`rdfs:subClassOf*`) and know why this is the reliable way to ask
  "is X a kind of Y," rather than PostgreSQL's built-in RDFS rule
  engine.
- Know, from direct testing, exactly what `pg_ripple.infer('rdfs')`
  does to existing data in this version — and why that means treating
  any `infer()` call as a real write against production data, never a
  side-effect-free query.
- Build a real hybrid retrieval pipeline combining `pgvector` semantic
  search with graph-verified structured facts.
- Evaluate a record-linkage feature against real ground truth instead
  of trusting a README's description of it.

---

## Exercises

### Exercise 1 — Building the Ontology by Hand

Before generating anything from the database, the actual design
decision worth making deliberately: which of Chapter 12's 48
categories become *classes*, and what's the hierarchy? A short,
hand-written sample, to see the shape before scripting the full 48:

```turtle
@prefix : <http://portsmith.example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:Category_all_categories a rdfs:Class ; rdfs:label "All Categories" .
:Category_restaurant a rdfs:Class ; rdfs:label "restaurant" ;
    rdfs:subClassOf :Category_all_categories .
:Category_seafood a rdfs:Class ; rdfs:label "seafood" ;
    rdfs:subClassOf :Category_restaurant .
```

The full 48-class hierarchy, generated from the real `categories`
table (`data/ch23_export_ontology.py`), plus a reclassification of
every business as an instance of its *specific* category rather than
Chapter 22's flat string — using `cuisine` for restaurants and
`subcategory` for retail, joined carefully against the correct parent
category (`"pub"` genuinely exists twice in Chapter 12's data, once
under `restaurant` and once under `entertainment` — the script scopes
the lookup by each business's own top-level category to resolve this
correctly, not just by name):

```bash
python3 data/ch23_export_ontology.py "dbname=portsmith" data/ch23_ontology.ttl
```

```
Wrote 48 category classes, 48 business classifications (0 unmatched) to data/ch23_ontology.ttl
```

```turtle
:business_1 a :Category_seafood .
:business_2 a :Category_pub .
:business_3 a :Category_specialty_food .
```

Loaded into the same `pg-ripple` container Chapter 22 already has
running:

```sql
SELECT pg_ripple.load_turtle(:'ontology_ttl', false);
-- 191
```

Sanity check — does the class hierarchy itself resolve correctly, with
no reasoning involved yet, just a direct property-path query?

```sql
SELECT * FROM pg_ripple.sparql('
PREFIX : <http://portsmith.example.org/>
SELECT ?super WHERE { :Category_seafood <http://www.w3.org/2000/01/rdf-schema#subClassOf>* ?super }
');
```

```
:Category_seafood, :Category_restaurant, :Category_all_categories
```

Correct, and correctly reflexive — `*` (zero-or-more) includes
`Category_seafood` itself as well as both real ancestors. The class
hierarchy, queried directly, works exactly as an ontology should.

---

### Exercise 2 — `infer('rdfs')`: A Real, Serious Warning

The natural next question: if `Category_seafood rdfs:subClassOf
Category_restaurant` is asserted, does the RDFS-standard entailment
rule — "if X is a `Category_seafood` and `Category_seafood` is a
subclass of `Category_restaurant`, then X is also a
`Category_restaurant`" — actually fire? PostgreSQL 19's beta gap
(Chapter 21) and the custom-rule chaining bug (Chapter 22) both taught
the same lesson: test it, don't assume it. This time, testing it
mattered more than either of those cases.

`pg-ripple` ships built-in rule sets by name — discovered, as usual,
from a real error message rather than documentation:

```sql
SELECT pg_ripple.load_rules_builtin('bogus');
-- ERROR: unknown built-in rule set 'bogus'; valid values: rdfs, owl-rl,
-- owl-el, owl-ql, skos, skos-transitive, skosxl, dcterms,
-- dcterms-integrity, schema, schema-integrity, foaf, foaf-integrity
```

```sql
SELECT pg_ripple.load_rules_builtin('rdfs');  -- 13 (real RDFS entailment rules, loaded)
```

A clean, isolated test before touching the real dataset — the same
discipline Chapter 22's Datalog investigation used:

```sql
INSERT DATA {
  :Seafood a rdfs:Class ; rdfs:subClassOf :Restaurant .
  :Restaurant a rdfs:Class ; rdfs:subClassOf :Business .
  :thing1 a :Seafood .
}
```

```sql
-- BEFORE infer():
SELECT ?t WHERE { :thing1 a ?t }   →  :Seafood

SELECT pg_ripple.infer('rdfs');    →  8

-- AFTER infer():
SELECT ?t WHERE { :thing1 a ?t }   →  rdfs:Class,  :Seafood
```

Already wrong in two ways: the expected new facts (`:thing1 a
:Restaurant`, `:thing1 a :Business` — the actual entailment this rule
set exists to compute) never appear, and a spurious, incorrect fact
does — `:thing1 a rdfs:Class`, conflating the *instance* with the
*metaclass* of the class it belongs to.

Running the identical `infer('rdfs')` against the real 48-business
ontology made the real severity clear. `pg_ripple.infer()` does not
appear to be scoped to a query or a subset of data — it operates
across the whole default graph — and the result was not "no new facts
added," it was **active loss of the real, correctly-asserted data**:

```sql
SELECT ?t WHERE { :business_1 a ?t }
```

```
:business_1, rdfs:Class
```

Every one of the 48 real `:business_N a :Category_X` classification
triples was replaced by a nonsensical self-reference
(`:business_1 a :business_1`) plus the same spurious `rdfs:Class`
typing seen in the isolated test — reproducible, not a fluke of the
larger dataset. Restoring the correct data took two steps: reloading
the real `:Business` and `:Category_X` triples (`load_turtle()` is
additive, so this was safe), then explicitly `DELETE DATA`-ing the
exact corrupted triples (`:business_N a :business_N` and `:business_N
a rdfs:Class` for all 48) — `DELETE DATA` rather than `DELETE WHERE`,
deliberately, after Chapter 22's `DELETE WHERE`-collateral-deletion
lesson.

**The real, load-bearing conclusion**: in this version, running
`pg_ripple.infer()` with a built-in rule set is not a safe,
side-effect-free way to ask "what does this entail" — it's a real
write against the whole graph, and this specific rule set actively
corrupted correct data rather than merely failing to add new facts.
Treat it exactly like any other destructive operation: never run it
directly against data you haven't backed up, on this build.

The workaround, and the thing actually worth doing when you need
"is this instance a member of that class, including subclasses":
**query the class hierarchy with a property path and join it against
plain `rdf:type` yourself, entirely without calling `infer()`** — which
is exactly what Exercise 1's direct `rdfs:subClassOf*` query already
proved works correctly. Chapter 3's next exercise builds on precisely
that pattern.

---

### Exercise 3 — Hybrid Retrieval: Semantic Recall, Structural Precision

The concrete version of this chapter's "Background" claim: combine
Chapter 6's `pgvector` semantic search (still on the original
PostgreSQL 16 database) with this chapter's ontology (on the
PostgreSQL 18 / `pg-ripple` container) to answer a question neither
tool fully answers alone — "which real businesses does this policy
actually affect?" `data/ch23_hybrid_retrieval.py` does both queries,
joined in Python (two independent PostgreSQL instances; no cross-
database SQL, deliberately the same style as Chapter 6's own RAG
scripts):

```bash
python3 data/ch23_hybrid_retrieval.py "food truck vendor permits near restaurants"
```

```
Top semantic match (0.597): 'Council Minutes — Harbour District Food Truck Permits' [City Council]

Businesses actually affected (restaurant category, Harbour District or adjacent): 16
 - Anchor & Oar Tavern
 - Bella Napoli
 - Dragon Palace
 - ... (16 total)
```

The semantic half found the *relevant document* — a real, clearly
dominant match (0.597, well ahead of the second-best result at 0.341).
The structural half — deliberately built from the two primitives
Exercise 1 and Chapter 22 Exercise 3 both already verified work
(`rdfs:subClassOf*` and the undirected `adjacentTo` property path),
**not** `infer()` — turns "this document is relevant" into a precise,
checkable, named list: every real restaurant-category business in
Harbour District or an adjacent neighborhood, exactly the population a
food-truck-permit policy would actually affect. Neither half replaces
the other: the embedding model has no idea what "Harbour District" or
"restaurant category" formally mean; the graph has no idea which
document, out of thousands, is topically relevant. This is what
"grounding" concretely looks like — not a metaphor, a working pipeline
that composes exactly two things this book has already independently
verified are correct.

---

### Exercise 4 — Entity Resolution: A Real, Direct Comparison

Chapter 5 seeded 12 genuine duplicate resident pairs with real ground
truth (`residents.true_duplicate_of` — e.g. `Eleanor Whitmore` /
`Elenor Whitmore`, `Priyanka Deshmukh` / `Priyanka Deshmuk`). `pg-
ripple`'s README advertises "neuro-symbolic record linkage" and
"Privacy-Preserving Record Linkage via CLK Bloom-filter encoding" —
real, callable functions (`bloom_encode()`, `dice_similarity()`), worth
testing against the exact same ground truth Chapter 5 already used,
rather than a fresh, possibly-flattering example.

`data/ch23_entity_resolution.py` runs both approaches, head to head,
on all 12 real pairs:

```bash
python3 data/ch23_entity_resolution.py
```

```
name a                   name b                    pg_trgm  ripple dice
Eleanor Whitmore         Elenor Whitmore             0.737        0.000
Jonathan Castellano      Jonathon Castellano         0.739        0.035
Priyanka Deshmukh        Priyanka Deshmuk            0.842        0.000
Bartholomew Okonkwo      Bartholemew Okonkwo         0.739        0.033
Marguerite Delacroix     Marguerite Delacroiux       0.792        0.068
Siobhan McAllister       Siobhan MacAllister         0.773        0.034
Theodore Vance           Theodor Vance               0.812        0.034
Anastasia Volkov         Anastassia Volkov           0.842        0.035
Desmond Okafor           Desmund Okafor              0.667        0.000
Genevieve Laurent        Genevieve Lorent            0.667        0.000
Mikhail Petrenko         Mikail Petrenko             0.737        0.034
Fitzgerald Osei          Fitzgerld Osei              0.722        0.102
```

A complete, one-sided result: Chapter 5's `pg_trgm` correctly scores
every real duplicate pair high (0.667–0.842, comfortably above any
reasonable matching threshold); `pg-ripple`'s CLK Bloom-filter
`dice_similarity`, called via its documented function signature with
default parameters (`bloom_encode(value, key)`, `hash_count=30`,
`length=1024`), scores every single one of the same 12 real pairs
near-zero (0.000–0.102) — indistinguishable from genuinely unrelated
names. `dice_similarity` isn't broken as a function — identical
strings correctly score a perfect `1.0` — but the *default*
parameterization is far more brittle than pg_trgm's trigram approach
for exactly the class of error (single-character insertions/deletions,
not just substitutions) real name-typo duplicates actually have.
`pg_ripple.resolve_entities()`, a higher-level orchestration function
over the same primitives, ran without error against this same data but
returned an empty result (`{"canonicalized": 0}`) with a best-guess
options payload — its expected configuration schema wasn't
discoverable without deeper source access than this chapter's scope,
so it's reported as untested rather than assumed working or broken.

**The honest conclusion**: for this specific, realistic task — fuzzy
name deduplication — Chapter 5's mature, purpose-built `pg_trgm`
approach is the one that actually works, verified against real ground
truth. `pg-ripple`'s privacy-preserving linkage is a genuinely
different, valuable technique (Bloom-filter encoding lets you compare
records *without* ever decrypting the underlying names — a real
capability `pg_trgm` doesn't have), but "genuinely different
capability" and "works out of the box for this data" are two separate
claims, and only checking against real ground truth tells you which
one you actually have.

---

## Decision Guide: Four Ways to Model "How Things Relate"

The book's own data-modeling spectrum, in one table:

| Approach | Chapter | Best for | Real limitation found in this book |
|---|---|---|---|
| JSONB | 1 | Irregular attributes on a single document | No relationships between documents at all |
| `pgvector` embeddings | 6 | Fuzzy semantic recall | No explicit facts — a similarity score, not a checkable claim |
| Recursive CTEs | 12 | Unbounded-depth traversal over existing tables | Verbose for pattern-shaped (not depth-shaped) questions |
| SQL/PGQ property graphs | 21 | Fixed-depth pattern matching over existing tables | No variable-length paths yet (PostgreSQL 19 beta2) |
| RDF + SPARQL | 22 | Fact-shaped data, unbounded traversal, schema-free | Custom Datalog rule chaining is broken in this build |
| **Ontologies (RDFS/OWL over RDF)** | **23** | **Checkable class semantics, machine-explainable structure** | **Built-in RDFS instance-type inference corrupts data in this build — but direct property-path queries over the same hierarchy work correctly** |

No single row is "the" answer — this book's own running example needed
all four models for genuinely different questions, sometimes on the
very same underlying data (Chapter 1's businesses are JSONB documents,
Chapter 6's embeddings, Chapter 21's graph vertices, and Chapter 22's
triples, all at once, none of them wrong).

---

<img src="imgs/ch23_ontology_findings.svg" alt="Diagram summarizing Chapter 23's verified findings in two groups. Verified working, green stroke: direct rdfs:subClassOf* property path queries over the real 48-class category hierarchy, and hybrid retrieval combining pgvector semantic search with graph-verified structured facts using only those direct property path primitives. Verified broken, red stroke, with a warning label: pg_ripple.infer of the built-in rdfs rule set, which does not propagate instance types correctly and instead overwrites real business classification triples with a spurious self-reference and an incorrect rdfs Class typing, confirmed on both an isolated three-triple test and the full forty-eight business dataset. Also verified broken: CLK Bloom-filter dice_similarity with default parameters, which scored all twelve real ground truth duplicate resident pairs from Chapter 5 near zero, while Chapter 5's own pg_trgm approach correctly scored all twelve pairs high on the identical data."/>

---

## Summary — What You Should Now Know

| Tool | What it's actually for |
|---|---|
| `rdfs:subClassOf` (asserted) | Real, correct, queryable class hierarchy — verified transitive and reflexive under `subClassOf*` |
| `rdfs:subClassOf*` / `+` property paths | The **reliable** way to ask "is X a kind of Y" — direct query, no reasoning engine required |
| `pg_ripple.load_rules_builtin()` | Loads real, named rule sets (`rdfs`, `owl-rl`, `skos`, ...) — loading succeeds and reports a plausible count |
| `pg_ripple.infer('rdfs')` | **A real write against the whole default graph, verified to corrupt existing instance-classification data rather than just failing to add new facts — treat as destructive, back up before running** |
| Hybrid retrieval (embeddings + graph) | A real, working pattern: semantic search finds *what's relevant*; a graph query, built from independently-verified primitives, turns that into a precise, checkable answer |
| `pg_ripple.dice_similarity()` / `bloom_encode()` | A real, different capability (privacy-preserving comparison) — verified, with default parameters, to miss all 12 of Chapter 5's real ground-truth duplicate pairs that `pg_trgm` catches correctly |

**The key design insight**, closing out this book's run through
PostgreSQL's extension surface: an ontology's value was never really
about the storage format — RDF triples, a property graph, or plain
rows all can hold "X is a kind of Y." Its value is in the *semantics*
being explicit enough to check, and this chapter's own testing is the
clearest demonstration of exactly why that checking matters: the
class hierarchy itself, queried directly, was correct and useful
throughout; it was specifically the automated reasoning layer built on
top of it that silently produced wrong, damaging results until someone
actually ran it against real data and looked at what came back. That
is, in miniature, this entire book's argument — run the real thing,
check the real output, and don't take a feature's existence as
evidence of its correctness.

---

*Going further: this closes the book's numbered chapters. Chapter 21
extended PostgreSQL's own core with a genuinely new query model still
finding its footing; Chapters 22 and 23 extended it further still, into
territory (RDF, SPARQL, formal ontologies) with an even younger
implementation and correspondingly sharper edges. The throughline
across all three, and really across this entire book: PostgreSQL's
extension mechanism keeps making ambitious things installable in an
afternoon — but installable was never the same claim as correct, and
this book's own most useful moments came from checking the difference
directly rather than assuming either one.*
