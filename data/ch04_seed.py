#!/usr/bin/env python3.12
"""
Chapter 4 seed data — Portsmith City Documents.

Creates a plain-text document archive (no extensions required — full-text
search is a core PostgreSQL feature) and seeds it with synthetic city
records: council meeting minutes, zoning ordinances, and public notices.

Usage:
    python ch04_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

# ---------------------------------------------------------------------------
# Schema
#
# Deliberately minimal at seed time — no search_vector column and no GIN
# index yet. Exercise 3 adds both; that progression is the point of the
# chapter.
# ---------------------------------------------------------------------------

DDL = """
DROP TABLE IF EXISTS city_documents CASCADE;

CREATE TABLE city_documents (
    id             SERIAL PRIMARY KEY,
    doc_type       TEXT NOT NULL
                       CHECK (doc_type IN ('council_minutes', 'zoning_ordinance', 'public_notice')),
    department     TEXT NOT NULL,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    published_date DATE NOT NULL
);

CREATE INDEX idx_city_documents_doc_type ON city_documents (doc_type);
CREATE INDEX idx_city_documents_published_date ON city_documents (published_date);
"""

# ---------------------------------------------------------------------------
# Synthetic city documents
#
# Topics deliberately recur across doc_type and across documents (the
# Riverside dog park, the Harbour District waterfront rezoning, Canal Road
# bike lanes) so that search results in the exercises return more than one
# hit and ranking has something real to differentiate. "Portsmith", "city",
# and "council" appear constantly — intentional, for Exercise 6.
# ---------------------------------------------------------------------------

DOCUMENTS: list[dict] = [
    # ── council_minutes ─────────────────────────────────────────────────────
    {
        "doc_type": "council_minutes", "department": "City Council",
        "title": "Council Minutes — Harbour District Waterfront Renovation Budget",
        "published_date": "2023-03-14",
        "body": (
            "The Portsmith City Council convened to review the proposed budget for the "
            "Harbour District waterfront renovation. The Director of Public Works presented "
            "a three-phase plan covering seawall repairs, a new pedestrian boardwalk, and "
            "lighting upgrades along the harbour. Council members discussed funding sources, "
            "including a state infrastructure grant and a bond measure. After debate over the "
            "timeline, the council voted six to one to approve the first phase of harbour "
            "renovation funding, with construction expected to begin in the fall."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "City Council",
        "title": "Council Minutes — Old Town Parking Structure Approval",
        "published_date": "2023-04-11",
        "body": (
            "The Portsmith City Council held a regular session to consider the Old Town "
            "parking structure proposal. Business owners along Market Street testified that "
            "insufficient parking was hurting foot traffic. The city's planning director "
            "presented a design for a four-level parking structure adjacent to the Old Town "
            "farmers market site. Concerns were raised about construction noise and the loss "
            "of a surface lot during building. The council voted to approve construction "
            "financing, directing staff to return with a construction schedule at the next "
            "session."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "City Council",
        "title": "Council Minutes — University Quarter Noise Ordinance Amendment",
        "published_date": "2023-05-09",
        "body": (
            "The council debated an amendment to the noise ordinance affecting bars and music "
            "venues in the University Quarter. Residents near Lighthouse Avenue reported late "
            "night noise from entertainment venues, while business owners argued that stricter "
            "hours would hurt revenue. The council reviewed a compromise ordinance limiting "
            "amplified outdoor music after eleven at night on weekdays and midnight on weekends. "
            "The amendment passed by a narrow margin, with the council agreeing to revisit "
            "enforcement data after six months."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "City Council",
        "title": "Council Minutes — Northgate Affordable Housing Incentive",
        "published_date": "2023-06-13",
        "body": (
            "Council members discussed a proposed affordable housing incentive program for "
            "developers building in Northgate. The program would waive a portion of permit "
            "fees for building projects that reserve at least twenty percent of units as "
            "affordable housing. The Northgate Housing Trust spoke in support, citing the "
            "demolition of the condemned rowhouse on Bay Street as evidence of the "
            "neighbourhood's aging housing stock. The council approved the incentive program "
            "on a unanimous vote, effective at the start of the next fiscal year."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "Public Works",
        "title": "Council Minutes — Riverside Road Resurfacing Program",
        "published_date": "2023-07-11",
        "body": (
            "The Public Works Department briefed the council on the annual road resurfacing "
            "program, with Riverside streets prioritized this cycle due to drainage damage "
            "from spring flooding. Canal Road, Quay Street, and Tidewater Lane were identified "
            "as the worst-condition segments. The council approved a contract with a paving "
            "firm and directed staff to coordinate resurfacing work with the planned Canal "
            "Road bike lane construction to avoid repaving the same street twice within a "
            "year."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "Parks & Recreation",
        "title": "Council Minutes — Riverside Dog Park Funding",
        "published_date": "2023-08-08",
        "body": (
            "The Parks & Recreation Department requested funding to convert an underused lot "
            "on Tidewater Lane into a fenced dog park serving the Riverside neighbourhood. "
            "Council members asked about maintenance costs and waste station upkeep. Several "
            "residents spoke in favor, noting the nearest existing dog park was in Northgate, "
            "a considerable distance for Riverside residents. The council approved construction "
            "funding and asked staff to plan a ribbon-cutting event once the dog park opens."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "City Council",
        "title": "Council Minutes — Business License Fee Schedule Update",
        "published_date": "2023-09-12",
        "body": (
            "The council reviewed a proposed update to the business license fee schedule, the "
            "first revision in eight years. The finance department recommended modest increases "
            "for high-impact categories such as late-night entertainment venues, while leaving "
            "fees for small retail and nonprofit workshop spaces unchanged. Council members "
            "questioned whether the increase would discourage new business license "
            "applications. The updated fee schedule passed on a five to two vote, taking effect "
            "at the start of the next calendar year."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "City Council",
        "title": "Council Minutes — Harbour District Food Truck Permits",
        "published_date": "2023-10-10",
        "body": (
            "The council considered a pilot program allowing food truck vendors to operate "
            "near the Harbour District waterfront on weekends. Existing restaurant owners "
            "raised concerns about competition and shared parking, while proponents argued "
            "food trucks would draw more visitors to the harbour overall. The council approved "
            "a six-month pilot permitting up to eight food truck vendors, with a review session "
            "scheduled to evaluate the program's impact on existing harbour businesses."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "Public Works",
        "title": "Council Minutes — Canal Road Bike Lane Expansion",
        "published_date": "2023-11-14",
        "body": (
            "The council voted on a proposal to extend the protected bike lane along Canal "
            "Road from Riverside into the University Quarter. Cycling advocates presented "
            "safety data showing a reduction in collisions on the existing Riverside segment. "
            "Some council members expressed concern about the loss of on-street parking spaces "
            "along the new segment. The council approved the bike lane expansion, funding it "
            "jointly with the Riverside road resurfacing program already underway."
        ),
    },
    {
        "doc_type": "council_minutes", "department": "City Council",
        "title": "Council Minutes — Special Session on Flood Mitigation Infrastructure",
        "published_date": "2023-12-05",
        "body": (
            "The Portsmith City Council held a special session to address flood mitigation "
            "infrastructure after spring flooding damaged Riverside roads and threatened the "
            "Northgate retaining wall that required emergency demolition earlier in the year. "
            "The city engineer presented options including upgraded storm drains, a new "
            "retention basin near the Industrial Port, and elevated roadbeds for the "
            "lowest-lying Riverside streets. The council directed staff to apply for state "
            "flood mitigation grant funding and report back within ninety days."
        ),
    },

    # ── zoning_ordinance ─────────────────────────────────────────────────────
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Industrial Port Rezoning to Mixed-Use",
        "published_date": "2023-02-01",
        "body": (
            "This ordinance rezones a twelve-acre parcel in the Industrial Port from "
            "industrial to mixed-use, permitting a combination of light manufacturing, "
            "retail, and residential development. The rezoning follows the closure of a "
            "warehouse annex and reflects the city's long-term plan to diversify Industrial "
            "Port land use. Building height is limited to six stories, and the ordinance "
            "requires a minimum setback of twenty feet from Dock Road to preserve truck "
            "loading access for remaining industrial tenants."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Harbour District Waterfront Height Variance",
        "published_date": "2023-03-01",
        "body": (
            "This ordinance establishes a height variance process for waterfront building "
            "projects in the Harbour District, allowing structures up to eight stories where "
            "the base zoning otherwise caps building height at five stories. Applicants must "
            "demonstrate that the additional height does not obstruct public views of the "
            "harbour from Anchor Lane or Portside Drive. The variance process requires a "
            "public hearing before the planning commission in addition to standard building "
            "permit review."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Northgate Residential Setback Requirements",
        "published_date": "2023-04-01",
        "body": (
            "This ordinance establishes updated setback requirements for residential "
            "construction in Northgate, increasing the required rear setback from ten to "
            "fifteen feet for new single-family building projects. The change responds to "
            "complaints following several building permit applications for rear extensions "
            "that reduced usable yard space on Bay Street and Ring Road. Existing structures "
            "are grandfathered, but any addition exceeding twenty-five percent of the existing "
            "footprint must meet the new setback standard."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Old Town Historic Preservation Overlay",
        "published_date": "2023-05-01",
        "body": (
            "This ordinance creates a historic preservation overlay district covering the "
            "commercial core of Old Town, including Market Street and Fisherman's Row. "
            "Exterior alterations to buildings within the overlay require review by the "
            "historic preservation board before a building permit is issued. The ordinance "
            "specifically protects storefront proportions, window patterns, and signage style "
            "consistent with Old Town's nineteenth-century commercial architecture, while "
            "permitting interior renovation without additional review."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Reduced Parking Minimums Near Transit Corridors",
        "published_date": "2023-06-01",
        "body": (
            "This ordinance reduces minimum off-street parking requirements for new "
            "development within a quarter mile of designated transit corridors, including "
            "Lighthouse Avenue and Canal Road. Developers of qualifying building projects may "
            "reduce required parking spaces by up to forty percent if the project includes "
            "secure bicycle parking. The ordinance is intended to lower construction costs for "
            "infill development and complements the city's ongoing bike lane expansion along "
            "Canal Road."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Riverside Short-Term Rental Restrictions",
        "published_date": "2023-07-01",
        "body": (
            "This ordinance restricts short-term rentals of fewer than thirty days in "
            "Riverside residential zones to owner-occupied properties only, with a limit of "
            "ninety rental nights per calendar year. The council cited concerns raised by "
            "Riverside residents about noise and parking associated with unrestricted "
            "short-term rentals near Quay Street and Tidewater Lane. Property owners already "
            "operating short-term rentals as of the ordinance's effective date have a one-year "
            "grace period to come into compliance."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Citywide Accessory Dwelling Unit Standards",
        "published_date": "2023-08-01",
        "body": (
            "This ordinance establishes citywide standards for accessory dwelling units, "
            "permitting one detached accessory dwelling unit per single-family lot in "
            "Northgate, Riverside, and Old Town residential zones. Accessory dwelling units "
            "are limited to eight hundred square feet and must meet the same rear setback "
            "requirements as the primary residence. The ordinance waives the building permit "
            "fee for accessory dwelling units that meet an affordable rent threshold, "
            "mirroring the Northgate affordable housing incentive program."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Entertainment Venue Hours of Operation",
        "published_date": "2023-09-01",
        "body": (
            "This ordinance sets hours-of-operation limits for entertainment venues holding a "
            "late-night music or bar license, restricting amplified outdoor sound after eleven "
            "at night on weekdays and midnight on weekends citywide. The ordinance codifies "
            "the compromise reached in the University Quarter noise ordinance amendment and "
            "extends the same standard to entertainment venues in the Harbour District and "
            "Old Town. Venues found in repeated violation may have their business license "
            "suspended by the city."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — Tree Canopy Preservation for New Subdivisions",
        "published_date": "2023-10-01",
        "body": (
            "This ordinance requires new residential subdivisions of five or more lots to "
            "preserve at least thirty percent existing tree canopy or provide equivalent "
            "replacement planting. The requirement applies primarily to undeveloped parcels in "
            "Northgate and the outer edge of Riverside, where recent building permit "
            "applications have proposed significant tree clearing. Developers must submit a "
            "tree survey and preservation plan to the planning department before building "
            "permits will be issued."
        ),
    },
    {
        "doc_type": "zoning_ordinance", "department": "Planning & Zoning",
        "title": "Zoning Ordinance — University Quarter Storefront Signage Standards",
        "published_date": "2023-11-01",
        "body": (
            "This ordinance updates signage standards for storefronts along Lighthouse Avenue "
            "in the University Quarter, limiting illuminated sign area and prohibiting "
            "flashing or animated displays. The ordinance follows several sign permit "
            "applications for oversized illuminated signage that business owners along "
            "Lighthouse Avenue argued was inconsistent with the district's character. Existing "
            "signage may remain until replacement, at which point new installations must "
            "comply with the updated standards."
        ),
    },

    # ── public_notice ────────────────────────────────────────────────────────
    {
        "doc_type": "public_notice", "department": "Public Works",
        "title": "Public Notice — Bay Street Water Main Repair Road Closure",
        "published_date": "2024-01-08",
        "body": (
            "The Portsmith Public Works Department announces an emergency water main repair "
            "on Bay Street between Ring Road and the Northgate Family Diner. Bay Street will "
            "be closed to through traffic for approximately five days while crews excavate and "
            "replace a section of aging water main. Local access for residents and businesses "
            "will be maintained. The city apologizes for the inconvenience and asks drivers to "
            "use Ring Road as an alternate route during the closure."
        ),
    },
    {
        "doc_type": "public_notice", "department": "Planning & Zoning",
        "title": "Public Notice — Public Hearing on Harbour District Waterfront Rezoning",
        "published_date": "2024-01-22",
        "body": (
            "Notice is hereby given that the Portsmith Planning Commission will hold a public "
            "hearing to consider the Harbour District waterfront height variance ordinance. "
            "The hearing will be held at City Hall and is open to all residents. Written "
            "comments on the proposed height variance may be submitted to the planning "
            "department in advance. The commission's recommendation will be forwarded to the "
            "city council for a final vote at a subsequent regular session."
        ),
    },
    {
        "doc_type": "public_notice", "department": "Public Works",
        "title": "Public Notice — Boil Water Advisory for Riverside Neighbourhood",
        "published_date": "2024-02-05",
        "body": (
            "The city of Portsmith is issuing a boil water advisory for the Riverside "
            "neighbourhood following a drop in water pressure during scheduled maintenance on "
            "Quay Street. Residents in the affected area should bring water to a rolling boil "
            "for one minute before drinking, cooking, or brushing teeth. The Public Works "
            "Department expects to lift the advisory once water quality testing confirms the "
            "system meets safety standards, and will issue a follow-up public notice at that "
            "time."
        ),
    },
    {
        "doc_type": "public_notice", "department": "Parks & Recreation",
        "title": "Public Notice — Riverside Dog Park Ribbon-Cutting Event",
        "published_date": "2024-02-19",
        "body": (
            "The Parks & Recreation Department invites Portsmith residents to a ribbon-cutting "
            "event celebrating the opening of the new Riverside dog park on Tidewater Lane. "
            "The event will include remarks from the mayor and city council members who "
            "championed the dog park funding, along with treats for dogs and their owners. "
            "The dog park will be open daily from dawn to dusk and includes separate areas for "
            "small and large dogs."
        ),
    },
    {
        "doc_type": "public_notice", "department": "City Council",
        "title": "Public Notice — City Council Special Session on Flood Mitigation",
        "published_date": "2024-03-04",
        "body": (
            "Notice is hereby given that the Portsmith City Council will convene a special "
            "session to discuss flood mitigation infrastructure for Riverside and the "
            "Northgate retaining wall area. The session is open to the public, and residents "
            "affected by spring flooding are encouraged to attend and provide comment. Staff "
            "will present the city engineer's storm drain and retention basin proposal "
            "developed in response to last year's flooding."
        ),
    },
    {
        "doc_type": "public_notice", "department": "Finance",
        "title": "Public Notice — Property Tax Assessment Appeals Deadline",
        "published_date": "2024-03-18",
        "body": (
            "The city of Portsmith reminds property owners that the deadline to file a formal "
            "appeal of the current property tax assessment is the last business day of March. "
            "Appeals must be submitted in writing to the city assessor's office and include "
            "supporting documentation such as a recent appraisal. Property owners in "
            "neighbourhoods that saw significant new building activity, including Northgate "
            "and the Industrial Port, are particularly encouraged to review their assessment "
            "for accuracy."
        ),
    },
    {
        "doc_type": "public_notice", "department": "Parks & Recreation",
        "title": "Public Notice — Old Town Farmers Market Summer Schedule",
        "published_date": "2024-04-01",
        "body": (
            "The Old Town farmers market returns for the summer season, operating every "
            "Saturday morning near Market Street and Fisherman's Row through early autumn. "
            "This year's market will operate adjacent to the new Old Town parking structure, "
            "giving visitors additional parking options. Vendors interested in a stall should "
            "contact the Parks & Recreation Department. The city reminds residents that "
            "portions of Market Street will have modified parking rules on market days."
        ),
    },
    {
        "doc_type": "public_notice", "department": "Public Works",
        "title": "Public Notice — Canal Road Bike Lane Construction Schedule",
        "published_date": "2024-04-15",
        "body": (
            "The Portsmith Public Works Department announces the construction schedule for the "
            "Canal Road bike lane expansion approved by the city council. Construction will "
            "proceed in sections from Riverside into the University Quarter over eight weeks, "
            "with lane restrictions but no full road closures expected. The work is coordinated "
            "with the ongoing Riverside road resurfacing program to minimize repeated "
            "disruption on the same streets."
        ),
    },
    {
        "doc_type": "public_notice", "department": "Planning & Zoning",
        "title": "Public Notice — Comment Period for Zoning Ordinance Amendments",
        "published_date": "2024-05-06",
        "body": (
            "The city of Portsmith is opening a thirty-day public comment period on a package "
            "of proposed zoning ordinance amendments, including updated accessory dwelling "
            "unit standards and tree canopy preservation requirements for new subdivisions. "
            "Copies of the proposed ordinance text are available at City Hall and on the "
            "planning department's public counter. Written comments will be included in the "
            "record considered by the planning commission and city council."
        ),
    },
    {
        "doc_type": "public_notice", "department": "City Council",
        "title": "Public Notice — Annual Fireworks Display and Street Closures",
        "published_date": "2024-05-20",
        "body": (
            "The city of Portsmith announces the annual fireworks display over the Harbour "
            "District waterfront, with street closures along Anchor Lane and Portside Drive "
            "beginning in the early evening. Food truck vendors will operate near the harbour "
            "under the existing pilot permit program. Residents are advised that parking near "
            "the Harbour District will be extremely limited, and the city encourages walking "
            "or biking along the Canal Road bike lane where possible."
        ),
    },
]

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            print("Creating schema …")
            cur.execute(DDL)

            print(f"Inserting {len(DOCUMENTS)} documents …")
            cur.executemany(
                """
                INSERT INTO city_documents (doc_type, department, title, body, published_date)
                VALUES (%(doc_type)s, %(department)s, %(title)s, %(body)s, %(published_date)s)
                """,
                DOCUMENTS,
            )

            cur.execute("SELECT COUNT(*) FROM city_documents")
            (count,) = cur.fetchone()
            print(f"Done — {count} rows in city_documents.")

        conn.commit()


if __name__ == "__main__":
    main()
