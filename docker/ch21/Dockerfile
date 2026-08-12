FROM debian:bookworm-slim

ENV PGDATA=/var/lib/postgresql/19/main \
    POSTGRES_USER=chris \
    POSTGRES_PASSWORD=ch21-scratch \
    POSTGRES_DB=portsmith19

# PostgreSQL 19 is still beta as of this Dockerfile's writing. PGDG publishes
# pre-release major versions in a "main <version>" component of the normal
# -pgdg suite, not a separate suite -- but that component only carries the
# version-specific packages (postgresql-19, postgresql-client-19, ...). The
# plain "main" component is still needed alongside it for the shared
# postgresql-common/libpq5 packages those depend on.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg lsb-release \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
        https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
        https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main 19" \
        >> /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-19 postgresql-client-19 \
    && pg_dropcluster --stop 19 main \
    && apt-get purge -y curl gnupg lsb-release \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p "$PGDATA" \
    && chown -R postgres:postgres /var/lib/postgresql

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER postgres
EXPOSE 5432
ENTRYPOINT ["/entrypoint.sh"]
