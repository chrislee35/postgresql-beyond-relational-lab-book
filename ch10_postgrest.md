# Chapter 10 — PostgREST: A Web-Native REST API from Your Schema

> *"PostgREST doesn't generate an API from your schema. It *is* your
> schema, addressed over HTTP."*

---

## Background

Every chapter so far has ended at `psql`. Getting from "a well-designed
database" to "a web application that uses it" usually means writing a
backend: routes, an ORM layer, and — this is the part that should sound
familiar by now — a second, hand-written copy of the authorization rules
the database already enforces. A `GRANT`, a `CHECK` constraint, a row
level security policy: none of that goes away when you add a web
service, but it's astonishingly common to see it duplicated, in a
different language, in application code that can quietly drift out of
sync with what the database actually allows.

PostgREST removes the backend, not by hiding the database behind a
generated client SDK, but by putting the database directly on the wire.
It's a single stateless binary that connects to PostgreSQL, introspects
the catalog, and turns every table and view it finds into a REST
resource and every function into an RPC endpoint. There is no PostgREST
authorization system to configure separately — a request arrives, an
HTTP verb and a role from a JWT decide what SQL statement to attempt, a
single transaction runs it as that role, and the same `GRANT`s and RLS
policies from every earlier chapter decide whether it succeeds. The
entire security model of this chapter is Postgres roles you already know
how to create.

That trade cuts both ways, and it's worth naming up front: you get an
API with no application code to audit, but you also get an API that can
only do what a single SQL statement per request can do. There's no
middle-tier caching, no multi-step business logic spanning several
tables outside of what a view or function can express, no background
jobs. For Portsmith's needs this chapter builds — a public directory, a
permit intake form, a resident self-service lookup, a fuzzy search box —
that's not a limitation, it's the entire point.

---

## The Scenario

Portsmith's small dev team wants four thin pieces of "app" without
writing a backend for any of them:

- a public, filterable directory of the businesses from Chapter 1
- an intake endpoint for the permit applications from Chapter 3's job
  queue
- a self-service portal where a logged-in resident can look up their own
  entry in Chapter 5's registry — and *only* their own
- a "did you mean?" business-name search box, reusing Chapter 5's
  trigram matching directly

Every one of these reuses a table this book already built. Nothing new
gets seeded — Chapter 10 is entirely about *exposing* data, not
generating it.

| Role            | Purpose                                                                |
|------------------|--------------------------------------------------------------------------|
| `authenticator`  | The only role PostgREST ever logs in as — `NOINHERIT`, switches roles per request |
| `web_anon`       | The public role — active whenever no JWT is presented                  |
| `web_resident`   | Authenticated role for the resident portal, assumed via a JWT `role` claim |

| Object                    | Purpose                                                              |
|----------------------------|-----------------------------------------------------------------------|
| `api.businesses`           | Curated view over `businesses` (Chapter 1) — the public directory   |
| `api.jobs`                 | Curated view over `jobs` (Chapter 3) — permit intake                |
| `api.residents`            | Curated view over `residents` (Chapter 5) — RLS-protected            |
| `api.search_businesses()`  | Wraps Chapter 5's `business_names` trigram search as an RPC endpoint |

---

## Exercise Goals

By the end of this chapter you will be able to:

- Install and configure PostgREST against an existing database, and
  explain why it connects as a single `NOINHERIT` role instead of one
  role per API user.
- Build filtered, sorted, paginated `GET` requests using PostgREST's
  query-parameter syntax, and read the `Content-Range` header it returns.
- Insert a row through a `POST` request against an updatable view.
- Prove, by making the exact same request before and after a single
  `GRANT`/`REVOKE`, that PostgREST's authorization is really just
  PostgreSQL's — no application code changes, no restart.
- Enable row level security on a table and issue signed JWTs so that two
  different callers see two different, correctly scoped slices of the
  same table through the same endpoint.
- Expose a SQL function as an RPC endpoint, and use it to serve Chapter
  5's fuzzy business-name search over HTTP.

---

## Installation

### 1 — PostgreSQL and Chapters 1, 3, and 5's data

This chapter assumes PostgreSQL 16 is already running with the
`businesses`, `jobs`, and `residents`/`business_names` tables in place —
see Loading the Data, below.

### 2 — PostgREST

Debian doesn't ship a current PostgREST package, and PostgREST's own
documentation recommends the prebuilt static binary over any distro
package anyway — it's a single file with no runtime dependencies. This
chapter was written against **v12.2** — check
[github.com/PostgREST/postgrest/releases](https://github.com/PostgREST/postgrest/releases)
for the current version and adjust the URL if a newer one exists:

```bash
curl -L -o postgrest.tar.xz \
  https://github.com/PostgREST/postgrest/releases/download/v14.16/postgrest-v14.16-linux-static-x86-64.tar.xz
tar xJf postgrest.tar.xz
sudo mv postgrest /usr/local/bin/
rm postgrest.tar.xz
postgrest --help | head -3
```

```
postgrest - Serve a RESTful API from any Postgres database

Usage: postgrest [-v|--version] [-e|--example] 
                 [--dump-config | --dump-schema | --ready] [FILENAME]
```

### 3 — `pyjwt`, for minting test tokens

```bash
source .venv/bin/activate
pip install pyjwt
```

### 4 — `curl` and `jq`

```bash
sudo apt install -y curl jq
```

`jq` isn't required, but every example below pipes through `| jq` to
keep the JSON readable — drop it if you'd rather see raw output.

---

## Loading the Data

Nothing new to seed. This chapter needs Chapters 1, 3, and 5's data to
already exist:

```bash
python data/ch01_seed.py   # businesses
python data/ch03_seed.py   # jobs, dead_letter_jobs
python data/ch05_seed.py   # residents, business_names
```

### Verify the prerequisites

```sql
SELECT 'businesses' AS table, COUNT(*) FROM businesses
UNION ALL SELECT 'jobs', COUNT(*) FROM jobs
UNION ALL SELECT 'residents', COUNT(*) FROM residents
UNION ALL SELECT 'business_names', COUNT(*) FROM business_names;
```

```
     table      | count
-----------------+-------
 businesses      |    48
 jobs            |    45
 residents       |    58
 business_names  |    48
(4 rows)
```

If all four match, proceed to the exercises.

---

## Exercises

---

### Exercise 1 — Install, Configure, Connect

**1.1 — The role PostgREST actually logs in as**

PostgREST doesn't map "one API caller" to "one Postgres login." It
authenticates to Postgres exactly once, as a single low-privilege role,
and then uses `SET ROLE` inside each request's transaction to switch to
whichever role the request is actually entitled to. That role has to be
`NOINHERIT` — otherwise it would automatically carry the privileges of
every role it can switch to, all the time, defeating the entire point:

```bash
sudo -u postgres psql portsmith
```

```sql
CREATE ROLE authenticator NOINHERIT LOGIN PASSWORD 'devsecret';
CREATE ROLE web_anon      NOLOGIN;
CREATE ROLE web_resident  NOLOGIN;

GRANT web_anon     TO authenticator;
GRANT web_resident TO authenticator;
```

`web_anon` and `web_resident` can never log in directly (`NOLOGIN`) —
they exist purely as identities `authenticator` is allowed to become.

**1.2 — A curated schema, not the raw tables**

PostgREST exposes exactly the schema(s) you tell it to, and nothing
about `db-schemas` requires that schema to be `public`. Building a
separate `api` schema of views — rather than pointing PostgREST straight
at `businesses`, `jobs`, and `residents` — means the public-facing shape
of the data can diverge from its internal shape without either side
having to know about the other's constraints:

```sql
CREATE SCHEMA IF NOT EXISTS api;

CREATE VIEW api.businesses AS
SELECT id,
       name,
       neighbourhood,
       details ->> 'category'          AS category,
       (details ->> 'rating')::numeric AS rating
FROM   businesses;

GRANT USAGE ON SCHEMA api TO web_anon, web_resident;
GRANT SELECT ON api.businesses TO web_anon;
```

`category` and `rating` didn't exist as real columns anywhere — they're
pulled out of Chapter 1's `details` JSONB and given real, typed names.
That's a small but genuine payoff from Chapter 1: the messy, schema-free
column becomes a clean, filterable, sortable API field, and the flexible
storage and the tidy public interface aren't in tension with each other.

**1.3 — `postgrest.conf`**

```ini
db-uri            = "postgres://authenticator:devsecret@localhost:5432/portsmith"
db-schemas        = "api"
db-anon-role      = "web_anon"
jwt-secret        = "portsmith-lab-book-dev-secret-do-not-use-in-production"
db-channel-enabled = true
db-channel        = "pgrst"
server-port       = 3000
```

`db-anon-role` is what `authenticator` becomes for any request that
doesn't carry a valid JWT. `db-channel-enabled` turns on `LISTEN pgrst` —
Exercise 3 uses it to tell a running PostgREST server about new views
without restarting it.

**1.4 — Start it, and make one request**

```bash
postgrest postgrest/postgrest.conf
```

```
Listening on port 3000
```

From another terminal:

```bash
curl -s "http://localhost:3000/businesses?limit=3" | jq
```

```json
[
  { "id": 1, "name": "The Gilded Clam",       "neighbourhood": "Harbour District", "category": "restaurant", "rating": 4.5 },
  { "id": 2, "name": "Anchor & Oar Tavern",    "neighbourhood": "Harbour District", "category": "restaurant", "rating": 4.1 },
  { "id": 3, "name": "Portsmith Fish Market",  "neighbourhood": "Harbour District", "category": "retail",     "rating": 4.8 }
]
```

No route was written anywhere. `/businesses` exists because
`api.businesses` exists, `db-schemas` says look in `api`, and `web_anon`
has `SELECT` on it. Delete the view and the route disappears with it.

---

### Exercise 2 — `GET /businesses`: Filter, Sort, Paginate

**2.1 — Filtering with `eq`, `gte`, and friends**

```bash
curl -s "http://localhost:3000/businesses?category=eq.restaurant&rating=gte.4.5&order=rating.desc&limit=5" | jq
```

```json
[
  { "id": 28, "name": "River Bend Bakery", "neighbourhood": "Riverside",   "category": "restaurant", "rating": 4.8 },
  { "id": 11, "name": "Le Petit Bistro",   "neighbourhood": "Old Town",    "category": "restaurant", "rating": 4.7 },
  { "id": 10, "name": "Bella Napoli",      "neighbourhood": "Old Town",    "category": "restaurant", "rating": 4.6 },
  { "id": 31, "name": "Quay Street Deli",  "neighbourhood": "Riverside",   "category": "restaurant", "rating": 4.6 },
  { "id": 24, "name": "Spice Garden",      "neighbourhood": "Northgate",   "category": "restaurant", "rating": 4.6 }
]
```

Every operator here — `eq`, `gte`, `order`, `limit` — is a plain query
parameter, translated straight into a `WHERE`/`ORDER BY`/`LIMIT` clause.
`gte.4.5` reads almost like the SQL it becomes:
`WHERE category = 'restaurant' AND rating >= 4.5`.

**2.2 — Paginating, and reading `Content-Range`**

```bash
curl -si "http://localhost:3000/businesses?category=eq.restaurant&order=name&limit=5&offset=5" \
  -H "Prefer: count=exact" | head -20
```

```
HTTP/1.1 206 Partial Content
Content-Range: 5-9/15
Content-Type: application/json; charset=utf-8

[
  { "id": 26, "name": "Mango Bay Caribbean", "neighbourhood": "Northgate",         "category": "restaurant", "rating": 4.5 },
  { "id": 42, "name": "Port Canteen",        "neighbourhood": "Industrial Port",   "category": "restaurant", "rating": 3.7 },
  { "id": 31, "name": "Quay Street Deli",    "neighbourhood": "Riverside",         "category": "restaurant", "rating": 4.6 },
  { "id": 28, "name": "River Bend Bakery",   "neighbourhood": "Riverside",         "category": "restaurant", "rating": 4.8 },
  { "id": 25, "name": "Sol y Mar",           "neighbourhood": "Northgate",         "category": "restaurant", "rating": 4.3 }
]
```

`206 Partial Content` and `Content-Range: 5-9/15` — rows 6 through 10 (0
indexed) out of 15 restaurants total. `Prefer: count=exact` is what
makes PostgREST bother computing that total at all; without it, the
`/15` is simply omitted, since counting the full match set costs an
extra query PostgREST won't run unless asked. The same pagination is
also available as a `Range: 5-9` request header instead of
`limit`/`offset` query parameters — two spellings of the identical SQL.

**2.3 — Narrowing columns with `select`**

```bash
curl -s "http://localhost:3000/businesses?select=name,rating&neighbourhood=eq.Riverside&order=rating.desc" | jq
```

```json
[
  { "name": "River Bend Bakery",      "rating": 4.8 },
  { "name": "Portsmith Veterinary Clinic", "rating": 4.8 },
  { "name": "Dr. Chen Dentistry",     "rating": 4.7 },
  { "name": "The Art Depot",          "rating": 4.6 },
  { "name": "Quay Street Deli",       "rating": 4.6 }
]
```

`select` maps directly onto the `SELECT` list — the response body is
exactly the columns asked for, never the whole row, which matters once a
client is fetching this over a slow connection or a metered one.

---

### Exercise 3 — `POST /jobs`: Filing a Permit Application

**3.1 — Expose the queue, add it to the running server**

```sql
CREATE VIEW api.jobs AS
SELECT id, job_type, payload, priority, status, created_at
FROM   jobs;

GRANT SELECT, INSERT ON api.jobs TO web_anon;
```

`api.jobs` didn't exist when PostgREST started, so it isn't in the
server's schema cache yet — a plain `curl` against `/jobs` right now
would 404. Tell the running server to pick up the change, without
restarting it:

```sql
NOTIFY pgrst, 'reload schema';
```

**3.2 — File a new permit application**

```bash
curl -si -X POST "http://localhost:3000/jobs" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{
    "job_type": "sign_permit",
    "priority": 5,
    "payload": {
      "application_id": "SP-2024-0007",
      "applicant_name": "Quay Street Deli",
      "property_address": "31 Quay Street",
      "neighbourhood": "Riverside",
      "description": "New illuminated storefront sign",
      "fee_due": 120.00
    }
  }'
```

```
HTTP/1.1 401 Unauthorized
Content-Type: application/json; charset=utf-8

{"code":"42501","details":null,"hint":null,"message":"permission denied for sequence jobs_id_seq"}
```

Not the response Exercise 3.1's `GRANT` seemed to promise. `jobs.id` is
`BIGSERIAL` — shorthand for a `BIGINT` column with
`DEFAULT nextval('jobs_id_seq')`, backed by a real sequence object the
table doesn't own outright. The client never mentions `id` in the
request body, but Postgres still has to *call* `nextval()` to fill in
that default while executing the `INSERT`, and calling a sequence
requires its own `USAGE` privilege — separate from, and not implied by,
`INSERT` on the table or view sitting on top of it. `GRANT INSERT` alone
is never enough for a table whose primary key is
`SERIAL`/`BIGSERIAL`/`IDENTITY`:

```sql
GRANT USAGE ON SEQUENCE jobs_id_seq TO web_anon;
```

**3.3 — Retry**

```bash
curl -si -X POST "http://localhost:3000/jobs" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{
    "job_type": "sign_permit",
    "priority": 5,
    "payload": {
      "application_id": "SP-2024-0007",
      "applicant_name": "Quay Street Deli",
      "property_address": "31 Quay Street",
      "neighbourhood": "Riverside",
      "description": "New illuminated storefront sign",
      "fee_due": 120.00
    }
  }'
```

```
HTTP/1.1 201 Created
Content-Type: application/json; charset=utf-8

[
  {
    "id": 46, "job_type": "sign_permit", "priority": 5,
    "payload": { "application_id": "SP-2024-0007", "applicant_name": "Quay Street Deli", ... },
    "status": "queued", "created_at": "2026-08-02T09:41:07.221Z"
  }
]
```

No client-supplied `id`, `status`, or `created_at` — all three came from
the table's own defaults, exactly as they would from a plain `INSERT`
missing those columns. `Prefer: return=representation` is what makes
PostgREST hand the created row back at all; without it, a successful
`POST` returns `201` with an empty body and a `Location` header instead.
This job now sits in the same `jobs` table Chapter 3's `FOR UPDATE SKIP
LOCKED` workers claim from — the web request and the queue worker never
have to know about each other.

---

### Exercise 4 — Limited Privileges, Enforced by the Database

**4.1 — The grant from Exercise 3 is looser than it looks**

`GRANT INSERT ON api.jobs` gave `web_anon` permission to set *every*
column in the view — including `status`. Nothing stops a client from
walking straight past "submitted" and declaring their own application
already approved:

```bash
curl -si -X POST "http://localhost:3000/jobs" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"job_type": "sign_permit", "priority": 5, "payload": {"application_id": "SP-2024-0008"}, "status": "completed"}'
```

```
HTTP/1.1 201 Created

[{ "id": 47, "job_type": "sign_permit", "priority": 5, "payload": {...}, "status": "completed", "created_at": "..." }]
```

That succeeded, and it shouldn't have — a permit that was never reviewed
now reads as `completed`, indistinguishable in the queue from one
Chapter 3's worker actually finished. Nothing in PostgREST's
configuration causes this; it's a plain over-broad `GRANT`, the same
mistake it would be in any hand-written backend.

**4.2 — Fix it with a column-level grant**

```sql
REVOKE INSERT ON api.jobs FROM web_anon;
GRANT INSERT (job_type, payload, priority) ON api.jobs TO web_anon;
```

PostgreSQL's `INSERT` privilege can be scoped to specific columns, not
just the whole table. `web_anon` can now insert a row, but only by
supplying values for these three columns — every other column must come
from its default.

**4.3 — The same malicious request, after the grant change**

```bash
curl -si -X POST "http://localhost:3000/jobs" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "sign_permit", "priority": 5, "payload": {"application_id": "SP-2024-0009"}, "status": "completed"}'
```

```
HTTP/1.1 401 Unauthorized
Content-Type: application/json; charset=utf-8

{"code":"42501","details":null,"hint":null,"message":"permission denied for table jobs"}
```

`401`, not `403` — PostgREST reserves `403` for a request that
authenticated as *someone* and was still refused; an unauthenticated
request denied by the database gets `401`, the same "you may need to
log in for this" signal a browser would show for any other protected
resource. No PostgREST config changed between 4.1 and 4.3, and the
server was never restarted — only a database `GRANT` changed, and the
API's behavior changed the instant that transaction committed, because
PostgREST never cached a decision about it in the first place.

**4.4 — The legitimate request still works**

```bash
curl -si -X POST "http://localhost:3000/jobs" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"job_type": "sign_permit", "priority": 5, "payload": {"application_id": "SP-2024-0009", "applicant_name": "Old Town Hardware", "fee_due": 95.00}}'
```

```
HTTP/1.1 201 Created

[{ "id": 48, "job_type": "sign_permit", "priority": 5, "payload": {...}, "status": "queued", "created_at": "..." }]
```

Omit `status` entirely and the table's own `DEFAULT 'queued'` fills it
in, exactly like Exercise 3 — the column-level grant didn't break the
honest use case, it just closed off the dishonest one.

---

### Exercise 5 — Row Level Security on `residents`

**5.1 — Expose residents, but to nobody yet**

```sql
CREATE VIEW api.residents WITH (security_invoker = true) AS
SELECT id, full_name, neighbourhood
FROM   residents;
```

`true_duplicate_of` — Chapter 5's ground-truth column for grading the
fuzzy-matching exercises — is deliberately left out. It's exactly the
kind of internal bookkeeping column a curated view exists to hide from
the outside world.

`security_invoker = true` is not optional here, and skipping it is the
kind of mistake that only shows up once you're testing with two
different JWTs and notice neither one got filtered. By default, a view
runs with the privileges of whoever *owns* it, not whoever is querying
it — including, critically, for deciding which row security policies
apply. That default is normally a feature: it's exactly what lets
`web_anon`, which has no direct grant on `businesses` at all, read
anything through `api.businesses`. But every object in this chapter was
created from the `sudo -u postgres psql` session back in Exercise 1.1,
which makes `postgres` — a superuser — the owner of `api.residents`.
Superusers bypass row level security unconditionally, no exceptions. Left
at its default, this view would evaluate Exercise 5.2's policy as
`postgres` on every single request, regardless of which role or JWT
actually called it, and a bypassed policy filters nothing — every
resident would see every row. `security_invoker = true` makes the view
check privileges and RLS as the real caller instead: `web_resident`,
after PostgREST's per-request `SET ROLE`, exactly as Exercise 5.2's
policy expects.

<img src="imgs/ch10_security_invoker.svg" alt="Two request flows through api.residents compared: with security_invoker off, the view is evaluated as its owner postgres, a superuser, so the RLS policy is checked against postgres and bypassed unconditionally, returning all 58 rows; with security_invoker on, the view is evaluated as the actual invoker web_resident, so the RLS policy correctly filters to the one row matching the JWT's resident_id claim"/>

(If you're changing an *existing* view rather than creating this one
fresh, reach for `ALTER VIEW api.residents SET (security_invoker =
true);` instead of dropping and recreating it — `DROP VIEW` followed by
`CREATE VIEW` makes a brand-new object with none of the original's
grants, so Exercise 5.2's `GRANT SELECT ON api.residents TO
web_resident` would silently need to be re-run, and the endpoint would
403 with `permission denied for view residents` until it is.)

```sql
NOTIFY pgrst, 'reload schema';
```

No `GRANT` yet, on purpose — not even to `web_resident`. RLS goes on
before any role can read a single row.

**5.2 — Enable RLS and add a self-only policy**

```sql
ALTER TABLE residents ENABLE ROW LEVEL SECURITY;

CREATE POLICY resident_self_only ON residents
    FOR SELECT
    USING (id = (current_setting('request.jwt.claims', true)::json ->> 'resident_id')::int);

GRANT SELECT ON api.residents TO web_resident;
GRANT SELECT (id, full_name, neighbourhood) ON residents TO web_resident;
```

`current_setting('request.jwt.claims', true)` reads the JSON claims
object PostgREST sets, per request, from the caller's verified JWT — the
`true` second argument means "return NULL instead of erroring if it's
unset," which matters because `web_anon` requests never carry one at
all. The policy compares the row's own `id` against whatever
`resident_id` claim a valid, signed JWT presents.

Both `GRANT`s are required, and it's easy to stop at the first one and
not notice. `security_invoker = true` from Exercise 5.1 means
`api.residents` no longer borrows its owner's privileges to read the
underlying table — the invoking role needs real privileges of its own on
`residents`, not just on the view sitting in front of it. Skip the
second `GRANT` and every request fails with `permission denied for table
residents`, even though the role clearly has `SELECT` on the view; the
view-level check passes, and the query still dies one level down, on the
base table it was never given access to. The column list
(`id, full_name, neighbourhood`) matters too, not just the table name:
granting only these three columns — matching exactly what
`api.residents` selects — keeps `true_duplicate_of` unreachable even if
`web_resident` were ever queried against directly instead of through the
view, which a bare `GRANT SELECT ON residents` (no column list) would
not.

**5.3 — Mint a JWT per resident**

```python
#!/usr/bin/env python3.12
# mint_jwt.py — issue a dev-only resident session token
import sys
import jwt

SECRET = "portsmith-lab-book-dev-secret-do-not-use-in-production"

resident_id = int(sys.argv[1])
token = jwt.encode(
    {"role": "web_resident", "resident_id": resident_id},
    SECRET,
    algorithm="HS256",
)
print(token)
```

The `role` claim is what PostgREST uses to decide which role to `SET
ROLE` to for this request — it has to be a role `authenticator` was
granted membership in back in Exercise 1.1, or PostgREST refuses the
token outright.

**5.4 — Two residents, two different answers from the same endpoint**

```bash
TOKEN_1=$(python mint_jwt.py 1)   # Adrian Foscolo
TOKEN_2=$(python mint_jwt.py 2)   # Marisol Quintero

curl -s "http://localhost:3000/residents" -H "Authorization: Bearer $TOKEN_1" | jq
curl -s "http://localhost:3000/residents" -H "Authorization: Bearer $TOKEN_2" | jq
```

```json
[ { "id": 1, "full_name": "Adrian Foscolo", "neighbourhood": "Old Town" } ]
```
```json
[ { "id": 2, "full_name": "Marisol Quintero", "neighbourhood": "Riverside" } ]
```

Identical request, identical route, identical `GRANT` — the only
difference is which JWT signed it, and RLS silently rewrote each query's
effective `WHERE` clause to match.

**5.5 — The gotcha: RLS filters, it doesn't refuse**

```bash
curl -s "http://localhost:3000/residents?id=eq.2" -H "Authorization: Bearer $TOKEN_1" | jq
```

```json
[]
```

Resident 1, asking directly for resident 2's row by id, does **not** get
a `403` — they get `200 OK` and an empty array. This is a meaningfully
different failure mode from Exercise 4's column-privilege denial: a
`GRANT` violation is an error, loud and explicit; an RLS mismatch is
just a `WHERE` clause that happens to match nothing, indistinguishable
at the HTTP layer from "that id doesn't exist." Compare with no
credentials at all:

```bash
curl -si "http://localhost:3000/residents"
```

```
HTTP/1.1 401 Unauthorized

{"code":"42501","details":null,"hint":null,"message":"permission denied for table residents"}
```

*This* one errors, the same way Exercise 4.3 did — `web_anon` was never
granted `SELECT` on `api.residents` at all, so it never gets far enough
to run into the RLS policy in the first place. Two different denials,
two different HTTP shapes, and the difference between them is worth
being able to explain: a missing `GRANT` is a wall; RLS is a filter.

---

### Exercise 6 — An RPC Endpoint for Fuzzy Search

**6.1 — Wrap Chapter 5's trigram search as a function**

```sql
CREATE OR REPLACE FUNCTION api.search_businesses(search_term text)
RETURNS TABLE (business_id integer, name text, similarity numeric)
LANGUAGE sql STABLE AS $$
    SELECT business_id, name, round(similarity(name, search_term)::numeric, 3) AS similarity
    FROM   business_names
    ORDER  BY name <-> search_term
    LIMIT  5;
$$;

GRANT EXECUTE ON FUNCTION api.search_businesses(text) TO web_anon;
GRANT SELECT ON business_names TO web_anon;
```

```sql
NOTIFY pgrst, 'reload schema';
```

The function body is Chapter 5, Exercise 5's exact "did you mean?"
query, verbatim — `name <-> search_term` ordering by trigram distance,
backed by the `idx_business_names_trgm_gist` GiST index that chapter
built. PostgREST doesn't need to know anything about trigrams; it just
sees a function in the `api` schema and exposes it at `/rpc/`.

Both `GRANT`s are required, for the same reason Exercise 5.2 needed two
of them. SQL functions default to `SECURITY INVOKER` — this one was
never told otherwise — so `api.search_businesses()` runs its `SELECT ...
FROM business_names` as whichever role actually called it, `web_anon`
here, not as the function's owner. `EXECUTE` only grants permission to
*call* the function; it says nothing about what the function is allowed
to touch once it's running. Skip the second `GRANT` and 6.2 fails with
`permission denied for table business_names`, `EXECUTE` privilege
notwithstanding — the same wall Exercise 5.2 hit with `residents`, just
one function-call away instead of one view away.

**6.2 — Call it**

```bash
curl -s -X POST "http://localhost:3000/rpc/search_businesses" \
  -H "Content-Type: application/json" \
  -d '{"search_term": "Ironsyde Auto"}' | jq
```

```json
[
  { "business_id": 45, "name": "Ironside Auto",      "similarity": 0.647 },
  { "business_id": 21, "name": "AutoFix Portsmith",  "similarity": 0.143 },
  { "business_id": 4,  "name": "Harbour Inn",        "similarity": 0.040 },
  { "business_id": 36, "name": "The Art Depot",      "similarity": 0.037 },
  { "business_id": 34, "name": "Riverside Cinema",   "similarity": 0.033 }
]
```

Same misspelling, same top match, same scores as Chapter 5's own
`psql` session — this endpoint is that query, not a reimplementation of
it.

**6.3 — `GET` works too, because the function is `STABLE`**

```bash
curl -s "http://localhost:3000/rpc/search_businesses?search_term=Ironsyde+Auto" | jq -c '.[0]'
```

```json
{"business_id":45,"name":"Ironside Auto","similarity":0.647}
```

PostgREST maps a function's SQL volatility onto which HTTP verbs it will
accept: `VOLATILE` functions — anything that could plausibly write data
— are reachable only by `POST`, on the theory that a `GET` should always
be safe to retry, cache, or prefetch without side effects. `STABLE` and
`IMMUTABLE` functions, like this one, are exposed under both `GET` and
`POST`, because Postgres itself already promises they don't change
anything. Declaring `LANGUAGE sql STABLE` back in 6.1 wasn't just
documentation — it's the line that decided whether a browser could ever
call this endpoint from a plain link.

Every real failure in this chapter — Exercise 3's `jobs_id_seq`,
Exercise 5's `residents` columns, this exercise's `business_names` —
turned out to be the same shape: one grant in place, a second,
independent one missing, one layer further in than the error first
suggests:

<img src="imgs/ch10_grant_layers.svg" alt="Flowchart of the layers a PostgREST request must clear: first a grant on the view or function itself (SELECT, INSERT, or EXECUTE), then a grant on the underlying object the view or function actually touches (a sequence, specific columns, or another table), then an RLS policy if one is enabled. Missing either of the first two grants produces a 42501 permission-denied error at that exact layer; failing the RLS check is not an error at all, just a 200 with an empty result"/>

---

## Summary — What You Should Now Know

| Tool | What it does |
|------|---------------|
| `authenticator` role, `NOINHERIT` | The one role PostgREST logs in as; switches per-request via `SET ROLE` |
| `db-anon-role` | The role a request without a valid JWT runs as |
| `api` schema of views | Decouples the public API shape from the internal table shape |
| `NOTIFY pgrst, 'reload schema'` | Tells a running PostgREST server about new tables/views/functions without a restart |
| `?col=eq.x`, `?order=`, `?select=`, `?limit=`/`?offset=` | Query-parameter syntax mapping directly onto `WHERE`/`ORDER BY`/`SELECT`/`LIMIT` |
| `Prefer: return=representation` | Get the affected row(s) back in the response body |
| `Prefer: count=exact` / `Content-Range` | Ask for, and read, the total row count behind a paginated result |
| Column-level `GRANT`/`REVOKE` | Restrict which fields a client can set on `INSERT`, enforced by Postgres itself |
| `GRANT USAGE ON SEQUENCE ...` | Needed alongside `INSERT` for any `SERIAL`/`BIGSERIAL`/`IDENTITY` column's default `nextval()` to succeed — table privileges don't imply sequence privileges |
| `401` vs. `403` | `401` = denied and unauthenticated (or bad JWT); `403` = denied despite valid credentials |
| RLS policy vs. missing `GRANT` | RLS silently filters rows (still `200`, possibly empty); a missing grant is a hard error |
| `security_invoker = true` on a view | Makes the view check privileges *and* RLS as the querying role, not the view's owner — required for RLS to mean anything through a view owned by a superuser or the table owner |
| `/rpc/<function>` | A SQL function exposed as an endpoint; `GET`-eligible only if `STABLE`/`IMMUTABLE` |

**The key design insight** from this chapter is that every access-control
decision PostgREST makes was already something PostgreSQL could do —
this chapter never introduced a new authorization concept, only a new
transport for reaching decisions the database was always capable of
making. `GRANT`/`REVOKE` from Exercise 4 and row level security from
Exercise 5 aren't PostgREST features with database-flavored names; they
are exactly the `GRANT` and `CREATE POLICY` you'd write for any other
purpose, and PostgREST's only job was to authenticate a request, pick a
role, and get out of the way. That's also this chapter's sharpest
limitation, in the same sentence: anything that can't be expressed as
one role running one SQL statement — multi-step workflows, calling
another API mid-request, anything genuinely procedural — is out of
scope by design, not by oversight.

---

*Going further: Chapter 13's `LISTEN`/`NOTIFY` is the same primitive this
chapter used for schema-reload notifications, applied to application
data instead — a natural next step once `NOTIFY pgrst, 'reload schema'`
feels familiar. Chapter 14's advisory locks are worth knowing about if
an RPC function like `api.search_businesses()` ever needs to serialize
access to a shared resource instead of just reading one. And the
column-level `GRANT` from Exercise 4 generalizes: PostgreSQL's full
privilege system — `SELECT`, `UPDATE`, and `REFERENCES` privileges can
all be scoped per-column the same way `INSERT` was here — is worth a
deliberate read through the `GRANT` documentation before exposing any
table this way for real, well beyond what one chapter's exercises can
cover.*
