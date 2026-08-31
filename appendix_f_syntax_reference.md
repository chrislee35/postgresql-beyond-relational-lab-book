# Appendix F — Syntax Quick Reference

One page per chapter. Meant to be flipped to, not read start to end —
the syntax this book actually used, nothing more. Where this book
found something doesn't work as documented, it's flagged **⚠ verified
broken/unsupported** right here, not just buried in that chapter's
prose — don't copy those forms expecting them to work.

### Chapter 1 — JSONB

```sql
details -> 'key'            -- get JSON value (as jsonb)
details ->> 'key'           -- get JSON value (as text)
details #>> '{a,b}'         -- get nested value by path (as text)
details @> '{"k":"v"}'      -- containment
details ? 'key'             -- key exists
jsonb_set(details, '{k}', '"v"')
jsonb_insert(details, '{arr,0}', '"v"')
jsonb_array_elements(details -> 'tags')
jsonb_path_query(details, '$.hours[*] ? (@.day == "sun")')
CREATE INDEX ... USING GIN (details);
CREATE INDEX ... USING GIN (details jsonb_path_ops);
```

### Chapter 2 — PostGIS

```sql
ST_GeomFromText('POINT(-1.1 50.8)', 4326)
ST_DWithin(a.geom, b.geom, 500)          -- meters, if geography-cast
ST_Within(point_geom, polygon_geom)
ST_Contains(polygon_geom, point_geom)
ST_Area(geom::geography)
ST_Distance(a.geom, b.geom)
CREATE INDEX ... USING GIST (geom);
```

### Chapter 3 — Job Queues

```sql
SELECT * FROM jobs
WHERE status = 'queued'
ORDER BY priority DESC, created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

### Chapter 4 — Full-Text Search

```sql
to_tsvector('english', body)
to_tsquery('english', 'budget & housing')
plainto_tsquery('english', 'budget housing')
ts_rank(search_vector, query)
ts_rank_cd(search_vector, query)
ts_headline('english', body, query)
CREATE TEXT SEARCH CONFIGURATION portsmith (COPY = english);
CREATE INDEX ... USING GIN (search_vector);
```

### Chapter 5 — Fuzzy Matching

```sql
CREATE EXTENSION pg_trgm;
similarity('a', 'b')
word_similarity('needle', 'haystack containing needle')
'query' % column                          -- similarity above pg_trgm.similarity_threshold
CREATE INDEX ... USING GIN (name gin_trgm_ops);
CREATE INDEX ... USING GIST (name gist_trgm_ops);
```

### Chapter 6 — pgvector

```sql
CREATE EXTENSION vector;
embedding vector(384)
embedding <-> query_vec      -- L2 distance
embedding <#> query_vec      -- negative inner product
embedding <=> query_vec      -- cosine distance
CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ... USING hnsw (embedding vector_cosine_ops);
```

### Chapter 7 — IP/Network (`ip4r`)

```sql
CREATE EXTENSION ip4r;
ip '10.0.0.5' <<= cidr '10.0.0.0/24'      -- contained by
cidr >> ip                                 -- contains
network(addr), masklen(addr)
CREATE INDEX ... USING GIST (cidr_range);
```

### Chapter 8 — Partitioning & BRIN

```sql
CREATE TABLE sensor_readings (...) PARTITION BY RANGE (recorded_at);
CREATE TABLE sensor_readings_2024_01 PARTITION OF sensor_readings
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
ALTER TABLE sensor_readings DETACH PARTITION sensor_readings_2024_01;
CREATE INDEX ... USING BRIN (recorded_at);
```

### Chapter 9 — Materialized Views

```sql
CREATE MATERIALIZED VIEW mv_sensor_daily AS SELECT ...;
REFRESH MATERIALIZED VIEW mv_sensor_daily;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sensor_daily;  -- needs a unique index first
```

### Chapter 10 — PostgREST

```sql
CREATE ROLE web_anon NOLOGIN;
CREATE ROLE authenticator NOINHERIT LOGIN PASSWORD '...';
GRANT web_anon TO authenticator;
GRANT SELECT ON api.businesses TO web_anon;
CREATE POLICY resident_self_only ON residents FOR SELECT
    USING (id = current_setting('request.jwt.claims', true)::json ->> 'resident_id');
```
```bash
postgrest postgrest.conf
```

### Chapter 11 — Window Functions

```sql
SELECT sensor_id, recorded_at,
       AVG(value) OVER (PARTITION BY sensor_id ORDER BY recorded_at
                         ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS rolling_avg,
       RANK() OVER (PARTITION BY sensor_id ORDER BY value DESC) AS rnk
FROM sensor_readings;
```

### Chapter 12 — Recursive CTEs

```sql
WITH RECURSIVE reports AS (
    SELECT id, manager_id, 0 AS depth FROM city_org WHERE id = 1
    UNION ALL
    SELECT c.id, c.manager_id, r.depth + 1
    FROM city_org c JOIN reports r ON c.manager_id = r.id
)
SELECT * FROM reports;

WITH RECURSIVE walk AS (
    ...
    CYCLE id SET is_cycle USING path
)
SELECT * FROM walk;
```

### Chapter 13 — `LISTEN`/`NOTIFY`

```sql
LISTEN permit_updates;
NOTIFY permit_updates, '{"job_id": 42}';
pg_notify('permit_updates', payload);
UNLISTEN permit_updates;
```

### Chapter 14 — Advisory Locks

```sql
pg_try_advisory_lock(hashtext('demolition_permit'))
pg_advisory_lock(key)          -- session-level, must be explicitly unlocked
pg_advisory_unlock(key)
pg_advisory_xact_lock(key)     -- transaction-level, auto-released on commit/rollback
SELECT * FROM pg_locks WHERE locktype = 'advisory';
```

### Chapter 15 — Custom Types, Domains, Enums

```sql
CREATE TYPE job_status AS ENUM ('queued','on_hold','in_progress','completed','failed','cancelled');
ALTER TYPE job_status ADD VALUE 'on_hold' AFTER 'queued';
CREATE DOMAIN positive_integer AS INTEGER CHECK (VALUE > 0);
CREATE TYPE contact_info AS (phone TEXT, postcode uk_postcode);
```

### Chapter 16 — Generated Columns

```sql
ALTER TABLE sensor_readings
    ADD COLUMN reading_date DATE
    GENERATED ALWAYS AS ((recorded_at AT TIME ZONE 'UTC')::date) STORED;
-- bare ::date on a timestamptz fails: "generation expression is not immutable"
```

### Chapter 17 — Foreign Data Wrappers

```sql
CREATE EXTENSION postgres_fdw;
CREATE SERVER legacy_srv FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host 'localhost', dbname 'portsmith_legacy');
CREATE USER MAPPING FOR chris SERVER legacy_srv
    OPTIONS (user 'chris', password 'fdw-demo-password');
IMPORT FOREIGN SCHEMA public FROM SERVER legacy_srv INTO public;

CREATE EXTENSION file_fdw;
CREATE FOREIGN TABLE census_raw (...) SERVER file_srv
    OPTIONS (filename '/tmp/census.csv', format 'csv', header 'true');
```

### Chapter 18 — Logical Replication

```sql
ALTER SYSTEM SET wal_level = 'logical';  -- own -c call, needs restart
CREATE PUBLICATION portsmith_pub FOR TABLE businesses (id, name, ...) WHERE (active = true);
SELECT pg_create_logical_replication_slot('portsmith_slot', 'pgoutput');
CREATE SUBSCRIPTION portsmith_sub CONNECTION '...' PUBLICATION portsmith_pub
    WITH (create_slot = false, slot_name = 'portsmith_slot');
ALTER TABLE businesses REPLICA IDENTITY USING INDEX idx_businesses_replident;
```

### Chapter 19 — `pg_cron`

```sql
CREATE EXTENSION pg_cron;
SELECT cron.schedule('refresh-mv-sensor-daily', '0 * * * *', $$CALL refresh_and_log('mv_sensor_daily')$$);
SELECT cron.schedule_in_database('legacy-analyze', '0 4 * * *', 'ANALYZE businesses_archive', 'portsmith_legacy');
SELECT * FROM cron.job_run_details ORDER BY start_time DESC NULLS LAST;
```

### Chapter 20 — `pg_stat_statements` / `EXPLAIN`

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
SELECT query, calls, total_exec_time, mean_exec_time
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;
SELECT pg_stat_statements_reset();
ALTER SYSTEM SET auto_explain.log_min_duration = 200;
SELECT pg_reload_conf();
```

### Chapter 21 — SQL/PGQ (PostgreSQL 19 beta2)

```sql
CREATE PROPERTY GRAPH city_org_graph
    VERTEX TABLES ( city_org KEY (id) LABEL employee PROPERTIES ALL COLUMNS )
    EDGE TABLES (
        city_org AS reports_to KEY (id)
            SOURCE KEY (id) REFERENCES city_org (id)
            DESTINATION KEY (manager_id) REFERENCES city_org (id)
            LABEL reports_to NO PROPERTIES
    );

SELECT * FROM GRAPH_TABLE (city_org_graph
    MATCH (a IS employee) -[IS reports_to]-> (b IS employee)
    COLUMNS (a.name, b.name)
);
```

**⚠ verified broken/unsupported (beta2):**
```sql
-- quantified path patterns -- both forms rejected:
MATCH (a) (-[IS reports_to]->(b)){1,10} (root)     -- "unsupported element pattern kind"
MATCH (a) -[IS reports_to]->{1,10} (root)          -- "element pattern quantifier is not supported"
```
No working substitute exists in this release — use Chapter 12's
`WITH RECURSIVE` for anything of unbounded/unknown depth.

### Chapter 22 — RDF / `pg-ripple`

```sql
SELECT pg_ripple.load_turtle(turtle_text, false);
SELECT * FROM pg_ripple.sparql('SELECT ?s ?o WHERE { ?s :locatedIn ?o }');
SELECT pg_ripple.sparql_update('INSERT DATA { ... }');
SELECT pg_ripple.load_shacl(shacl_text);
SELECT pg_ripple.shacl_score('default');
SELECT pg_ripple.shacl_report_scored('default');
```
```sparql
-- property paths (these work correctly):
:a :adjacentTo+ ?n                    -- one-or-more, directed
:a (:adjacentTo|^:adjacentTo)+ ?n     -- one-or-more, either direction
```

**⚠ verified broken:** custom Datalog rules
(`pg_ripple.load_rules()`/`infer()`) — multi-atom rule bodies don't
chain correctly; a rule head's second variable binds to the wrong
value regardless of body atom order. Reproduced on an isolated
3-triple example, not just the chapter's larger dataset.

**⚠ gotcha:** `DELETE WHERE { pat1 . pat2 }` deletes *every* pattern
per matched solution, not just the one you meant — use `DELETE DATA`
with exact triples for anything you can't afford to lose collaterally.

### Chapter 23 — Ontologies

```sql
-- correct, reliable way to query a class hierarchy (no infer() needed):
SELECT * FROM pg_ripple.sparql(
  'SELECT ?super WHERE { :Category_seafood <...#subClassOf>* ?super }'
);
SELECT pg_ripple.load_rules_builtin('rdfs');   -- valid names discovered via a bogus-name error:
                                                -- rdfs, owl-rl, owl-el, owl-ql, skos, skos-transitive,
                                                -- skosxl, dcterms, dcterms-integrity, schema,
                                                -- schema-integrity, foaf, foaf-integrity
```

**⚠ verified broken, and dangerous:** `pg_ripple.infer('rdfs')` does
not correctly propagate `rdf:type` up a class hierarchy, and was
verified — twice, isolated test and full dataset — to **overwrite real
classification triples** with an incorrect self-type
(`:business_N a :business_N`) and a spurious `a rdfs:Class`. Treat any
`infer()` call with a built-in rule set as a real write against the
whole default graph, not a safe query. Back up before running it.

### Chapter 24 — `pgColumnar`

```sql
CREATE TABLE t (...) USING pgcolumnar;                        -- columnar storage, real measured wins
SELECT pgcolumnar.vacuum_sorted('t', 'col' [, 'col2', ...]);   -- physically sort, improves chunk-group skip
SELECT * FROM pgcolumnar.sort_status('t');                     -- verify a table is actually sorted
SELECT pgcolumnar.export_parquet('t', '/path/file.parquet');   -- no compression option, see note below
SELECT * FROM pgcolumnar.read_parquet('/path/file.parquet')
  AS t(col1 type1, col2 type2, ...);                           -- decodes requested columns only, see note below
```

**Note:** the storage engine above (`USING pgcolumnar` and
`vacuum_sorted`) is this extension's strength — real, measured
compression and speed wins in Chapter 24. `export_parquet()` takes no
compression argument (larger files than a deliberately compressed
export) and `read_parquet()` only saves decoding unwanted columns, not
reading unwanted rows — but a `pgcolumnar_parquet` foreign table's
row-group skipping works well: 147 of 148 groups skipped on a filtered
query in Chapter 24's own test. Worth rechecking against whatever
release you're actually running, the same as any fast-moving young
extension.
