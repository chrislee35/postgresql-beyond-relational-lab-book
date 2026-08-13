# Appendix A — Environment Setup

This book does not run on one PostgreSQL installation. It runs on
**three**, and that split is itself a real finding worth understanding
before you set anything up, not an accident of how the book was
written: Chapters 1–20 share one long-lived cluster; Chapters 21–23
each needed a separate, disposable one, for reasons specific to what
each chapter was testing.

| Environment | Chapters | Version | Where |
|---|---|---|---|
| Main cluster | 1–20 | PostgreSQL 16 | Installed directly on the host (`apt`) |
| SQL/PGQ container | 21 | PostgreSQL 19 beta2 | `docker/ch21/` |
| `pg-ripple` container | 22–23 | PostgreSQL 18 | `docker/ch22/` |

## Why three, not one

The main cluster accumulates real, cumulative state across twenty
chapters — roles, grants, two databases, rows mutated by earlier
exercises that later chapters depend on. Chapter 21 needed PostgreSQL
19, which was still in beta at the time of writing; Chapters 22–23
needed a Rust extension (`pg-ripple`) built from source against
PostgreSQL 18. Running either of those against the main cluster would
have meant either upgrading a host carrying real state onto beta
software, or bolting a from-source Rust build onto an installation
everything else depends on staying stable. Both risks were judged not
worth it for two chapters' worth of exercises — isolate instead, and
throw the container away if something goes wrong. This turned out to
matter in practice: Chapter 21's PostgreSQL 19 needed rebuilding from
scratch after a packaging misconfiguration, and Chapter 22's container
was restarted mid-chapter to fix a `shared_preload_libraries` setting.
Neither touched the main cluster at all.

## The main cluster (Chapters 1–20)

Installed directly, not in a container — every extension in the table
below is a plain `apt install` against a single PostgreSQL 16 server.

```bash
sudo apt install -y postgresql-16 postgresql-client-16
```

Two databases exist on it by the end of Chapter 20:

- `portsmith` — the primary database essentially every chapter uses.
- `portsmith_legacy` — introduced in Chapter 17 as a genuinely separate
  `postgres_fdw` target, reused in Chapter 18 as the logical-replication
  subscriber.

The full extension list, required `postgresql.conf` settings, and the
role/grant history this cluster accumulated chapter by chapter are in
**Appendix C**, not repeated here — that appendix is the canonical
reference for "what needs to be installed," this one is about the
overall shape of the setup.

## The PostgreSQL 19 beta2 container (Chapter 21)

`docker/ch21/` — `Dockerfile`, `entrypoint.sh`, `docker-compose.yml`.
Bring it up:

```bash
cd docker/ch21
docker compose up --build
```

Listens on host port **5433** (5432 is the main cluster). Two real
build problems, both explained in full in Chapter 21's own Environment
Setup section, worth knowing before you rebuild this yourself:

1. PGDG publishes pre-release major versions as an additional
   `main <version>` **component** inside the normal `-pgdg` suite, not
   a separate suite — and that component alone isn't sufficient; the
   plain `main` component is also needed, for `postgresql-common`/
   `libpq5`.
2. Debian's `postgresql-19` package auto-creates a cluster on install
   via `pg_createcluster`, splitting config (`/etc/postgresql/`) from
   data (`/var/lib/postgresql/`) — incompatible with this image's
   hand-rolled `initdb`, fixed with `pg_dropcluster --stop 19 main`
   before `initdb` runs.

## The PostgreSQL 18 / `pg-ripple` container (Chapters 22–23)

`docker/ch22/` — same three-file shape as Chapter 21's container, built
on PostgreSQL 18 (GA, not 19 — `pg-ripple`'s own documentation targets
18, and there was no reason to stack PostgreSQL 19's own beta
uncertainty on top of an already-real-risk Rust build).

```bash
cd docker/ch22
docker compose up --build
```

Listens on host port **5434**. `pg-ripple` is compiled from source via
Rust/`pgrx`, not installed as a package — the real, non-obvious trap
here: `cargo-pgrx`'s own version must **exactly** match the `pgrx`
library version an extension's `Cargo.toml` pins (`0.18.0` for
`pg-ripple`), not just satisfy a semver range. `cargo install
cargo-pgrx --version "^0.18"` resolves to whatever the newest `0.18.x`
happens to be, and `cargo-pgrx` refuses to build against a mismatched
version with a clear, specific error — the fix is pinning the exact
version:

```dockerfile
RUN cargo install --locked cargo-pgrx --version "0.18.0"
```

Chapter 22's environment setup covers the rest, including the
`shared_preload_libraries = 'pg_ripple'` setting this container needs
from its very first start to get `pg-ripple`'s background workers
running (the same class of gotcha Chapters 19–20's `pg_cron`/
`pg_stat_statements` needed on the main cluster).

## Connecting to all three

```bash
psql portsmith                                                       # main cluster, PG16
psql -h localhost -p 5433 -U chris -d portsmith19                    # Chapter 21, PG19 beta2
psql -h localhost -p 5434 -U chris -d portsmith22                    # Chapters 22-23, PG18
```

Both container passwords are set directly in their respective
`docker-compose.yml` files (`ch21-scratch`, `ch22-scratch`) — these are
throwaway scratch instances, not meant to hold anything you'd mind
losing to a `docker compose down -v`.

## A note for anyone continuing this book

If you're picking Chapters 22–23's container back up, one thing is
worth knowing before you run anything against it: Chapter 23 found that
`pg_ripple.infer()`, run with a built-in rule set, does not behave as a
safe read-only reasoning query — it was verified, twice, to overwrite
real classification data with incorrect facts. Don't run it against
data in that container you haven't already exported, and see Chapter
23 Exercise 2 for the full, reproduced finding before relying on it for
anything.
