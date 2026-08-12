FROM debian:bookworm-slim

ENV PGDATA=/var/lib/postgresql/18/main \
    POSTGRES_USER=chris \
    POSTGRES_PASSWORD=ch22-scratch \
    POSTGRES_DB=portsmith22 \
    PATH="/root/.cargo/bin:${PATH}"

# --- PostgreSQL 18 (GA, unlike Chapter 21's PG19 beta -- plain PGDG main
# component, no "main <version>" beta dance needed here). -----------------
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
    # Same gotcha Chapter 21 hit: Debian's package auto-creates a cluster
    # that splits config (/etc/postgresql) from data (/var/lib/postgresql).
    # Drop it so our own from-scratch initdb in entrypoint.sh has a clean,
    # single-directory layout to work with.
    && pg_dropcluster --stop 18 main \
    && rm -rf /var/lib/apt/lists/*

# --- Build toolchain: pg-ripple is a Rust extension built via pgrx, not
# an apt package -- this is the genuinely heavy part of this image. -------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config git \
        libssl-dev libreadline-dev zlib1g-dev \
        clang libclang-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable

# cargo-pgrx enforces that its own version exactly matches the pgrx
# library version pinned in pg-ripple's Cargo.toml (0.18.0) -- a loose
# "^0.18" match resolved to the newer 0.18.1 and cargo-pgrx itself
# rejected that mismatch at install time, so this has to be exact.
RUN cargo install --locked cargo-pgrx --version "0.18.0"

RUN cargo pgrx init --pg18 "$(which pg_config)"

RUN git clone --depth 1 https://github.com/trickle-labs/pg-ripple.git /usr/src/pg-ripple
WORKDIR /usr/src/pg-ripple
RUN cargo pgrx install --release --pg-config "$(which pg_config)"

RUN mkdir -p "$PGDATA" \
    && chown -R postgres:postgres /var/lib/postgresql

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER postgres
EXPOSE 5432
ENTRYPOINT ["/entrypoint.sh"]
