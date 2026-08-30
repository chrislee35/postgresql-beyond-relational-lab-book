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

    # pgcolumnar must be in shared_preload_libraries from the very first
    # start -- the host PG16 install hit a real ALTER SYSTEM SET bug
    # appending it to an existing list live (a stray pair of quotes ended up
    # wrapping the whole comma-joined value as one identifier, and the
    # server refused to start at all). Writing it directly into
    # postgresql.conf before the first pg_ctl start sidesteps that path
    # entirely -- same lesson as Chapter 19's shared_preload_libraries note.
    echo "shared_preload_libraries = 'pgcolumnar'" >> "$PGDATA/postgresql.conf"

    "$PG_BIN/pg_ctl" -D "$PGDATA" -o "-c listen_addresses=''" -w start
    "$PG_BIN/createdb" -U "$POSTGRES_USER" "$POSTGRES_DB"
    "$PG_BIN/psql" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION pgcolumnar;"
    "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast -w stop

    echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"
    echo "listen_addresses = '*'" >> "$PGDATA/postgresql.conf"
fi

exec "$PG_BIN/postgres" -D "$PGDATA"
