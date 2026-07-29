#!/usr/bin/env python3.12
"""
Chapter 5 seed data — Portsmith Resident Registry and Business Name Lookup.

Creates two tables:
  - residents      : synthetic residents, including intentional near-duplicate
                      entries (typos, transpositions, variant spellings) that
                      model the kind of messy data entry fuzzy matching exists
                      to clean up.
  - business_names  : a flat (business_id, name) lookup extending the
                      `businesses` table from Chapter 1, used for "did you
                      mean?" style search over business names.

Requires: Chapter 1 seed (ch01_seed.py) to have been run first so that the
          `businesses` table exists.

Usage:
    python ch05_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

NEIGHBOURHOODS = [
    "Harbour District",
    "Industrial Port",
    "Northgate",
    "Old Town",
    "Riverside",
    "University Quarter",
]

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
DROP TABLE IF EXISTS residents CASCADE;
DROP TABLE IF EXISTS business_names CASCADE;

CREATE TABLE residents (
    id                 SERIAL PRIMARY KEY,
    full_name          TEXT NOT NULL,
    neighbourhood      TEXT NOT NULL,
    -- Ground truth for grading the exercises only — a real registry would
    -- not have this column; you would not know in advance which rows are
    -- duplicates, that is the entire problem fuzzy matching solves.
    true_duplicate_of  INTEGER REFERENCES residents (id)
);

CREATE TABLE business_names (
    business_id  INTEGER PRIMARY KEY REFERENCES businesses (id),
    name         TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Synthetic residents
#
# 30 unrelated baseline residents, 12 canonical/duplicate pairs (the same
# person entered twice with a typo, transposition, or variant spelling —
# `duplicate_of` gives the 0-based index of the canonical row below), and
# two trap pairs that are NOT marked as duplicates:
#   - a nickname pair ("Robert Ashworth" / "Bobby Ashworth"): the same person
#     in the real world, but "Robert" and "Bobby" share zero trigrams — the
#     pair only scores above the default threshold at all because of the
#     shared surname.
#   - a coincidence pair ("Nadia Kowalski" / "Nadia Kowalska"): two
#     unrelated Riverside residents who happen to share a first name and a
#     Polish surname that differs only in its masculine/feminine suffix.
#     Deliberately scored (~0.76) to land *inside* the true-duplicate
#     similarity range (~0.67-0.84) — no single threshold separates this
#     pair from the real duplicates below.
# ---------------------------------------------------------------------------

RESIDENTS: list[dict] = [
    # ── 30 unrelated baseline residents ─────────────────────────────────────
    {"full_name": "Adrian Foscolo", "neighbourhood": "Old Town"},
    {"full_name": "Marisol Quintero", "neighbourhood": "Riverside"},
    {"full_name": "Bennett Okoye", "neighbourhood": "Northgate"},
    {"full_name": "Wilhelmina Strand", "neighbourhood": "Harbour District"},
    {"full_name": "Tobias Renner", "neighbourhood": "University Quarter"},
    {"full_name": "Camille Fontaine", "neighbourhood": "Old Town"},
    {"full_name": "Emeka Anozie", "neighbourhood": "Industrial Port"},
    {"full_name": "Ingrid Solberg", "neighbourhood": "Riverside"},
    {"full_name": "Percival Duffy", "neighbourhood": "Northgate"},
    {"full_name": "Zara Al-Amin", "neighbourhood": "Harbour District"},
    {"full_name": "Konstantin Popov", "neighbourhood": "Industrial Port"},
    {"full_name": "Delphine Roussel", "neighbourhood": "Old Town"},
    {"full_name": "Nathaniel Crane", "neighbourhood": "University Quarter"},
    {"full_name": "Yolanda Mbeki", "neighbourhood": "Riverside"},
    {"full_name": "Frederik Haas", "neighbourhood": "Northgate"},
    {"full_name": "Seraphina Cole", "neighbourhood": "Harbour District"},
    {"full_name": "Dimitri Sokolov", "neighbourhood": "Industrial Port"},
    {"full_name": "Beatrix Lindqvist", "neighbourhood": "Old Town"},
    {"full_name": "Osric Whitfield", "neighbourhood": "University Quarter"},
    {"full_name": "Amara Chukwu", "neighbourhood": "Riverside"},
    {"full_name": "Cornelius Baptiste", "neighbourhood": "Northgate"},
    {"full_name": "Liesel Brandt", "neighbourhood": "Harbour District"},
    {"full_name": "Salvatore Greco", "neighbourhood": "Old Town"},
    {"full_name": "Priscilla Nakamura", "neighbourhood": "Industrial Port"},
    {"full_name": "Augustin Belanger", "neighbourhood": "Riverside"},
    {"full_name": "Odalys Vega", "neighbourhood": "University Quarter"},
    {"full_name": "Rutherford Combs", "neighbourhood": "Northgate"},
    {"full_name": "Anouk Dekker", "neighbourhood": "Harbour District"},
    {"full_name": "Isidro Pham", "neighbourhood": "Old Town"},
    {"full_name": "Guinevere Ashby", "neighbourhood": "Industrial Port"},

    # ── 12 canonical/duplicate pairs ────────────────────────────────────────
    {"full_name": "Eleanor Whitmore", "neighbourhood": "Riverside"},               # 30
    {"full_name": "Elenor Whitmore", "neighbourhood": "Riverside", "duplicate_of": 30},

    {"full_name": "Jonathan Castellano", "neighbourhood": "Old Town"},             # 32
    {"full_name": "Jonathon Castellano", "neighbourhood": "Old Town", "duplicate_of": 32},

    {"full_name": "Priyanka Deshmukh", "neighbourhood": "University Quarter"},     # 34
    {"full_name": "Priyanka Deshmuk", "neighbourhood": "University Quarter", "duplicate_of": 34},

    {"full_name": "Bartholomew Okonkwo", "neighbourhood": "Northgate"},            # 36
    {"full_name": "Bartholemew Okonkwo", "neighbourhood": "Northgate", "duplicate_of": 36},

    {"full_name": "Marguerite Delacroix", "neighbourhood": "Harbour District"},    # 38
    {"full_name": "Marguerite Delacroiux", "neighbourhood": "Harbour District", "duplicate_of": 38},

    {"full_name": "Siobhan McAllister", "neighbourhood": "Industrial Port"},       # 40
    {"full_name": "Siobhan MacAllister", "neighbourhood": "Industrial Port", "duplicate_of": 40},

    {"full_name": "Theodore Vance", "neighbourhood": "Riverside"},                 # 42
    {"full_name": "Theodor Vance", "neighbourhood": "Riverside", "duplicate_of": 42},

    {"full_name": "Anastasia Volkov", "neighbourhood": "Old Town"},                # 44
    {"full_name": "Anastassia Volkov", "neighbourhood": "Old Town", "duplicate_of": 44},

    {"full_name": "Desmond Okafor", "neighbourhood": "University Quarter"},        # 46
    {"full_name": "Desmund Okafor", "neighbourhood": "University Quarter", "duplicate_of": 46},

    {"full_name": "Genevieve Laurent", "neighbourhood": "Northgate"},              # 48
    {"full_name": "Genevieve Lorent", "neighbourhood": "Northgate", "duplicate_of": 48},

    {"full_name": "Mikhail Petrenko", "neighbourhood": "Harbour District"},        # 50
    {"full_name": "Mikail Petrenko", "neighbourhood": "Harbour District", "duplicate_of": 50},

    {"full_name": "Fitzgerald Osei", "neighbourhood": "Industrial Port"},          # 52
    {"full_name": "Fitzgerld Osei", "neighbourhood": "Industrial Port", "duplicate_of": 52},

    # ── Trap pairs — intentionally NOT marked as duplicates ─────────────────
    {"full_name": "Robert Ashworth", "neighbourhood": "Old Town"},
    {"full_name": "Bobby Ashworth", "neighbourhood": "Old Town"},

    {"full_name": "Nadia Kowalski", "neighbourhood": "Riverside"},
    {"full_name": "Nadia Kowalska", "neighbourhood": "Riverside"},
]

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('businesses')")
            (businesses_exists,) = cur.fetchone()
            if businesses_exists is None:
                sys.exit(
                    "ERROR: the 'businesses' table does not exist. "
                    "Run `python data/ch01_seed.py` first."
                )

            print("Creating schema …")
            cur.execute(DDL)

            print(f"Inserting {len(RESIDENTS)} residents …")
            ids: list[int] = []
            for row in RESIDENTS:
                cur.execute(
                    "INSERT INTO residents (full_name, neighbourhood) VALUES (%s, %s) RETURNING id",
                    (row["full_name"], row["neighbourhood"]),
                )
                ids.append(cur.fetchone()[0])

            for i, row in enumerate(RESIDENTS):
                dup_of = row.get("duplicate_of")
                if dup_of is not None:
                    cur.execute(
                        "UPDATE residents SET true_duplicate_of = %s WHERE id = %s",
                        (ids[dup_of], ids[i]),
                    )

            print("Populating business_names from businesses …")
            cur.execute(
                "INSERT INTO business_names (business_id, name) SELECT id, name FROM businesses"
            )

            cur.execute("SELECT COUNT(*) FROM residents")
            (resident_count,) = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM business_names")
            (name_count,) = cur.fetchone()
            print(
                f"Done — {resident_count} rows in residents, "
                f"{name_count} rows in business_names."
            )

        conn.commit()


if __name__ == "__main__":
    main()
