# Appendix G — Acknowledgments

Twenty-four chapters of a fictional city rest on a very real stack of
software this book didn't write a line of. PostgreSQL itself, every
extension bolted onto it, the languages and libraries that generated
Portsmith's synthetic data, and the tools that turned two dozen
Markdown files into the HTML, PDF, and EPUB you're reading — none of
it was built for this book, and all of it made this book possible.
This page is a plain, direct thank-you to the people and projects
behind that stack.

---

## PostgreSQL

<img src="imgs/logo_postgresql.svg" alt="PostgreSQL elephant logo" width="90" style="width:90px;height:auto;"/>

Every chapter in this book is, at bottom, a chapter about
**PostgreSQL** — free, open-source, and developed by a global group of
volunteers and companies coordinated through the PostgreSQL Global
Development Group. Thirty years of that work is the reason a single
database can hold JSON documents, geospatial polygons, vector
embeddings, RDF triples, and a columnar table side by side, and still
feel like one coherent system. [postgresql.org](https://www.postgresql.org/)

---

## Extensions and Companion Databases

Nearly every chapter after the first turned on one extension or
another. In the order this book met them:

- **PostGIS** <img src="imgs/logo_postgis.png" alt="PostGIS logo" width="28" style="width:28px;height:auto;"/> — geospatial types and operators (Chapter 2), maintained by the PostGIS Project Steering Committee. [postgis.net](https://postgis.net/)
- **`pg_trgm`** — trigram fuzzy matching (Chapter 5), bundled with PostgreSQL core.
- **pgvector** — vector similarity search (Chapter 6), created by Andrew Kane and maintained with the broader pgvector community. [github.com/pgvector/pgvector](https://github.com/pgvector/pgvector)
- **`ip4r`** — IPv4/IPv6 range and CIDR types (Chapter 7), maintained by Andrew Gierth (RhodiumToad). [github.com/RhodiumToad/ip4r](https://github.com/RhodiumToad/ip4r)
- **`postgres_fdw`** and **`file_fdw`** — foreign data wrappers (Chapter 17), bundled with PostgreSQL core.
- **`parquet_s3_fdw`** — the Parquet-over-S3 foreign data wrapper Chapter 17 discussed honestly rather than pretending to have finished building.
- **`pg_cron`** — in-database job scheduling (Chapter 19), originally created at Citus Data, now maintained under `citusdata/pg_cron`. [github.com/citusdata/pg_cron](https://github.com/citusdata/pg_cron)
- **`pg_stat_statements`** and **`auto_explain`** — query statistics and automatic plan logging (Chapter 20), bundled with PostgreSQL core.
- **`pg-ripple`** — RDF triples, SPARQL, and SHACL inside PostgreSQL (Chapters 22–23), from Trickle Labs. [github.com/trickle-labs/pg-ripple](https://github.com/trickle-labs/pg-ripple)
- **`pgColumnar`** — columnar table storage (Chapter 24), from CommandPrompt, Inc. [github.com/commandprompt/pgcolumnar](https://github.com/commandprompt/pgcolumnar). Particular thanks to **OffgridwithJD**, one of the project's developers, for real, direct help while this book was working through Chapter 24.

Chapter 21's `CREATE PROPERTY GRAPH` and `GRAPH_TABLE` needed no
extension at all — thanks there go to the PostgreSQL contributors who
landed SQL/PGQ in core.

---

## Tools Built Around PostgreSQL

- **PostgREST** — turns a PostgreSQL schema into a REST API (Chapter 10), created by Joe Nelson and maintained by the PostgREST community. [postgrest.org](https://postgrest.org/)
- **DuckDB** <img src="imgs/logo_duckdb.svg" alt="DuckDB logo" width="70" style="width:70px;height:auto;"/> — the independent, in-process analytical engine used to verify Chapter 17's Parquet export actually worked. [duckdb.org](https://duckdb.org/)
- **MinIO** <img src="imgs/logo_minio.svg" alt="MinIO logo" width="70" style="width:70px;height:auto;"/> — the self-hosted, S3-compatible object storage Chapter 17's Parquet files lived in. [min.io](https://min.io/)

---

## Python and Its Libraries

<img src="imgs/logo_python.svg" alt="Python logo" width="45" style="width:45px;height:auto;"/>

Every synthetic data generator, migration script, and RAG demo in this
book is **Python** — created by Guido van Rossum and maintained by the
Python Software Foundation. [python.org](https://www.python.org/)

The libraries doing the real work underneath those scripts: **psycopg**
(the PostgreSQL driver every script in this book connects through),
**pyarrow** and **boto3** (Chapter 17's Parquet export and S3 upload),
**pgvector**'s Python client and **sentence-transformers** (Chapter 6),
**duckdb**'s Python bindings (Chapter 17's independent verification),
**PyJWT** (Chapter 10's token minting), **NumPy**, **Pillow**, and
**requests**. Thank you to every maintainer of every one of them —
this book leaned on all of it without a second thought, which is
exactly what good infrastructure earns.

**Ollama**, used in Chapter 6's bonus local RAG section to run an
open-weight model entirely on-device, deserves its own mention —
[ollama.com](https://ollama.com/).

---

## Building This Book Itself

None of the above gets read without a second stack, the one that turns
Markdown source into the book in your hands:

- **Markdown**, the plain-text format every chapter is written in, designed by John Gruber with Aaron Swartz.
- **Pandoc**, the "universal document converter" that turns this book's Markdown into HTML, PDF, and EPUB in one pass — created by John MacFarlane. [pandoc.org](https://pandoc.org/)
- **Mermaid.js**, which renders every diagram in this book — flowcharts, sequence diagrams, the graph contrasts in Chapters 17 through 24 — from plain text descriptions, created by Knut Sveidqvist and maintained by the Mermaid team. Reached in this book's build through **`mermaidx`**, a CLI wrapper around it. [mermaid.js.org](https://mermaid.js.org/)
- **GNU Make** <img src="imgs/logo_gnu.svg" alt="GNU logo" width="45" style="width:45px;height:auto;"/> — the build tool coordinating every step above, part of the GNU Project. [gnu.org/software/make](https://www.gnu.org/software/make/)
- **WeasyPrint**, which lays out this book's PDF from styled HTML. [weasyprint.org](https://weasyprint.org/)
- **Inkscape**, converting hand-made diagrams to the PNGs the PDF build needs.
- **Debian** <img src="imgs/logo_debian.svg" alt="Debian logo" width="45" style="width:45px;height:auto;"/> and **Docker** <img src="imgs/logo_docker.svg" alt="Docker logo" width="70" style="width:70px;height:auto;"/> — the operating system and containerization underneath every isolated environment in Chapters 21, 22, and 24, letting three different PostgreSQL majors coexist on one machine without touching each other. [debian.org](https://www.debian.org/), [docker.com](https://www.docker.com/)

---

## Specifications and Open Standards

<img src="imgs/logo_apache.svg" alt="Apache feather logo" width="40" style="width:40px;height:auto;"/>

**Apache Arrow** and **Apache Parquet**, the in-memory and on-disk
columnar formats behind Chapters 17 and 24, both projects of the
Apache Software Foundation. [arrow.apache.org](https://arrow.apache.org/),
[parquet.apache.org](https://parquet.apache.org/)

Chapters 22 and 23 rest on a stack of World Wide Web Consortium
standards — **SPARQL**, **Turtle**, **SHACL**, **RDF Schema**, and
**OWL 2** — the product of years of working-group effort to make data
meaning machine-checkable, long before "AI-ready data" was a phrase
anyone used.

---

## AI Assistance

<img src="imgs/logo_anthropic.svg" alt="Anthropic logo" width="140" style="width:140px;height:auto;"/>

This book was written with **Claude Code**, from **Anthropic**, as a
genuine collaborator throughout — drafting exercises, standing up and
tearing down disposable PostgreSQL environments, running the real
queries whose output fills these pages, and, more than once, finding
and diagnosing the book's own mistakes (a broken build script, a
mis-set config value that took down the working cluster mid-chapter)
before they became someone else's problem. [anthropic.com](https://www.anthropic.com/)

---

*If you maintain something on this page and think it deserves more
than a line here, that's fair — open an issue or a pull request. This
list exists because none of Portsmith's twenty-four chapters would
have been possible without every project named on it. I am deeply
grateful for the years of dedicated effort into all these foundational
tools.*
