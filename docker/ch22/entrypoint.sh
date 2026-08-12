#!/bin/bash
set -euo pipefail

PG_BIN=/usr/lib/postgresql/18/bin

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL 18 cluster at $PGDATA ..."

    PWFILE=$(mktemp)
    echo "$POSTGRES_PASSWORD" > "$PWFILE"
    "$PG_BIN/initdb" --username="$POSTGRES_USER" --pwfile="$PWFILE" \
        --auth-local=trust --auth-host=md5
    rm -f "$PWFILE"

    # pg_ripple needs to be in shared_preload_libraries from the very first
    # start -- without it, SPARQL/load_turtle still work, but its HTAP merge
    # worker, CONSTRUCT writeback, and dictionary cache stay disabled (a
    # real WARNING it prints at startup otherwise). Written before the
    # first pg_ctl start so it's in effect from that point on, not added
    # after the fact.
    echo "shared_preload_libraries = 'pg_ripple'" >> "$PGDATA/postgresql.conf"

    "$PG_BIN/pg_ctl" -D "$PGDATA" -o "-c listen_addresses=''" -w start
    "$PG_BIN/createdb" -U "$POSTGRES_USER" "$POSTGRES_DB"
    "$PG_BIN/psql" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION pg_ripple;"
    "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast -w stop

    echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"
    echo "listen_addresses = '*'" >> "$PGDATA/postgresql.conf"
fi

exec "$PG_BIN/postgres" -D "$PGDATA"
