FROM debian:bookworm-slim

ENV PGDATA=/var/lib/postgresql/18/main \
    POSTGRES_USER=chris \
    POSTGRES_PASSWORD=ch24-scratch \
    POSTGRES_DB=portsmith24

# --- PostgreSQL 18 (GA -- plain PGDG main component, same as Chapter 22's
# pg-ripple container, no beta-suite dance needed here). -------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg lsb-release \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
        https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-18 postgresql-client-18 postgresql-server-dev-18 \
    # Same gotcha Chapters 21/22 hit: Debian's package auto-creates a cluster
    # that splits config (/etc/postgresql) from data (/var/lib/postgresql).
    # Drop it so our own from-scratch initdb in entrypoint.sh has a clean,
    # single-directory layout to work with.
    && pg_dropcluster --stop 18 main \
    && rm -rf /var/lib/apt/lists/*

# --- pgColumnar build toolchain. Unlike Chapter 22's pg-ripple, this is a
# plain C extension built via PGXS -- no Rust/cargo, just gcc/make/pkg-config
# and the optional compression codec dev libraries the build probes for. ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config git \
        liblz4-dev libzstd-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# pgColumnar 1.0-alpha3 (MIT-licensed, github.com/commandprompt/pgcolumnar).
# Builds from one source tree against PG15 through 18 (19 validated against
# 19beta2/beta3 -- see Chapter 21's own beta-retest discipline). We're on 18
# here specifically to rule out the PG17+-gated code paths (MERGE's
# WHEN NOT MATCHED BY SOURCE, read_stream prefetch, partitioned-table
# ALTER ... SET ACCESS METHOD) as an explanation for what looked like a
# non-functional Parquet-FDW row-group skip when tested against the host's
# PostgreSQL 16.
RUN git clone --depth 1 https://github.com/commandprompt/pgcolumnar.git /usr/src/pgcolumnar
WORKDIR /usr/src/pgcolumnar
RUN make PG_CONFIG=/usr/lib/postgresql/18/bin/pg_config \
    && make install PG_CONFIG=/usr/lib/postgresql/18/bin/pg_config

RUN mkdir -p "$PGDATA" \
    && chown -R postgres:postgres /var/lib/postgresql

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER postgres
EXPOSE 5432
ENTRYPOINT ["/entrypoint.sh"]
