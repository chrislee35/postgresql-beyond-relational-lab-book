#!/bin/bash
set -euo pipefail

PG_BIN=/usr/lib/postgresql/19/bin

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL 19 cluster at $PGDATA ..."

    PWFILE=$(mktemp)
    echo "$POSTGRES_PASSWORD" > "$PWFILE"
    "$PG_BIN/initdb" --username="$POSTGRES_USER" --pwfile="$PWFILE" \
        --auth-local=trust --auth-host=md5
    rm -f "$PWFILE"

    "$PG_BIN/pg_ctl" -D "$PGDATA" -o "-c listen_addresses=''" -w start
    "$PG_BIN/createdb" -U "$POSTGRES_USER" "$POSTGRES_DB"
    "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast -w stop

    echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"
    echo "listen_addresses = '*'" >> "$PGDATA/postgresql.conf"
fi

exec "$PG_BIN/postgres" -D "$PGDATA"
