#!/usr/bin/env python3.12
"""
Chapter 1 seed data — Portsmith Business Directory.

Creates the `businesses` table and populates it with 48 fictional businesses
spread across six Portsmith neighbourhoods. Each business has a fixed
relational spine (id, name, address, neighbourhood) and a JSONB `details`
column whose shape varies by business category.

Usage:
    python ch01_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import json
import sys

import psycopg

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
DROP TABLE IF EXISTS businesses CASCADE;

CREATE TABLE businesses (
    id             SERIAL PRIMARY KEY,
    name           TEXT        NOT NULL,
    address        TEXT        NOT NULL,
    neighbourhood  TEXT        NOT NULL,
    details        JSONB       NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

BUSINESSES: list[dict] = [

    # ── HARBOUR DISTRICT ────────────────────────────────────────────────────

    {
        "name": "The Gilded Clam",
        "address": "4 Wharf Street",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "restaurant", "cuisine": "seafood",
            "price_range": "$$", "rating": 4.5, "review_count": 312,
            "hours": {
                "mon": {"open": "11:30", "close": "21:00"},
                "tue": {"open": "11:30", "close": "21:00"},
                "wed": {"open": "11:30", "close": "21:00"},
                "thu": {"open": "11:30", "close": "21:00"},
                "fri": {"open": "11:30", "close": "22:30"},
                "sat": {"open": "12:00", "close": "22:30"},
                "sun": {"open": "12:00", "close": "20:00"},
            },
            "tags": ["waterfront", "seafood", "romantic", "outdoor_seating"],
            "accepts_reservations": True, "outdoor_seating": True,
            "wheelchair_accessible": True,
            "social": {"instagram": "@gildedclam", "facebook": "thegildedclam"},
        },
    },
    {
        "name": "Anchor & Oar Tavern",
        "address": "12 Harbour Walk",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "restaurant", "cuisine": "pub",
            "price_range": "$", "rating": 4.1, "review_count": 529,
            "hours": {
                "mon": {"open": "11:00", "close": "23:00"},
                "tue": {"open": "11:00", "close": "23:00"},
                "wed": {"open": "11:00", "close": "23:00"},
                "thu": {"open": "11:00", "close": "23:00"},
                "fri": {"open": "11:00", "close": "01:00"},
                "sat": {"open": "11:00", "close": "01:00"},
                "sun": {"open": "12:00", "close": "22:00"},
            },
            "tags": ["waterfront", "pub", "live_music", "dog_friendly", "outdoor_seating"],
            "accepts_reservations": False, "outdoor_seating": True,
            "live_music": True, "music_nights": ["wed", "fri", "sat"],
            "wheelchair_accessible": True,
        },
    },
    {
        "name": "Portsmith Fish Market",
        "address": "1 Dock Road",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "retail", "subcategory": "specialty_food",
            "rating": 4.8, "review_count": 184,
            "hours": {
                "mon": {"open": "06:00", "close": "13:00"},
                "tue": {"open": "06:00", "close": "13:00"},
                "wed": {"open": "06:00", "close": "13:00"},
                "thu": {"open": "06:00", "close": "13:00"},
                "fri": {"open": "06:00", "close": "14:00"},
                "sat": {"open": "05:30", "close": "14:00"},
                "sun": None,
            },
            "tags": ["waterfront", "fresh_fish", "local", "wholesale_available"],
            "payment_methods": ["cash", "card"],
            "has_parking": True, "wholesale": True,
        },
    },
    {
        "name": "Harbour Inn",
        "address": "88 Anchor Lane",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "accommodation", "subcategory": "inn",
            "star_rating": 3, "rating": 4.3, "review_count": 217,
            "hours": {"reception": "07:00-23:00"},
            "tags": ["waterfront", "cozy", "breakfast_included", "family_friendly"],
            "amenities": ["wifi", "parking", "breakfast", "garden"],
            "room_types": ["single", "double", "family"],
            "pet_friendly": True,
            "price_per_night": {"low": 65, "high": 110},
        },
    },
    {
        "name": "Lighthouse Bookshop",
        "address": "7 Portside Drive",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "retail", "subcategory": "bookshop",
            "rating": 4.9, "review_count": 302,
            "hours": {
                "mon": {"open": "09:00", "close": "18:00"},
                "tue": {"open": "09:00", "close": "18:00"},
                "wed": {"open": "09:00", "close": "18:00"},
                "thu": {"open": "09:00", "close": "18:00"},
                "fri": {"open": "09:00", "close": "19:00"},
                "sat": {"open": "09:00", "close": "19:00"},
                "sun": {"open": "11:00", "close": "17:00"},
            },
            "tags": ["independent", "maritime_history", "local_authors", "secondhand"],
            "payment_methods": ["cash", "card", "contactless"],
            "has_parking": False,
            "specialties": ["maritime", "local_history", "nautical_charts"],
        },
    },
    {
        "name": "Tidal Wave Surf Shop",
        "address": "22 Harbour Walk",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "retail", "subcategory": "sporting_goods",
            "rating": 4.5, "review_count": 143,
            "hours": {
                "mon": {"open": "09:00", "close": "18:00"},
                "tue": {"open": "09:00", "close": "18:00"},
                "wed": {"open": "09:00", "close": "18:00"},
                "thu": {"open": "09:00", "close": "18:00"},
                "fri": {"open": "09:00", "close": "18:00"},
                "sat": {"open": "08:00", "close": "18:00"},
                "sun": {"open": "09:00", "close": "17:00"},
            },
            "tags": ["waterfront", "surfboards", "wetsuits", "lessons", "rental"],
            "payment_methods": ["cash", "card", "contactless"],
            "has_parking": False, "lessons": True, "rental": True,
        },
    },
    {
        "name": "Mariners Rest B&B",
        "address": "6 Anchor Lane",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "accommodation", "subcategory": "bed_and_breakfast",
            "star_rating": 3, "rating": 4.7, "review_count": 128,
            "hours": {"reception": "08:00-22:00"},
            "tags": ["waterfront", "cozy", "breakfast_included", "sea_views", "adults_only"],
            "amenities": ["wifi", "breakfast", "sea_view_rooms", "garden"],
            "room_types": ["double", "king"],
            "pet_friendly": False, "adults_only": True,
            "price_per_night": {"low": 85, "high": 140},
        },
    },
    {
        "name": "Saltbox Gallery",
        "address": "18 Portside Drive",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "retail", "subcategory": "gallery",
            "rating": 4.7, "review_count": 94,
            "hours": {
                "mon": None,
                "tue": {"open": "10:00", "close": "17:00"},
                "wed": {"open": "10:00", "close": "17:00"},
                "thu": {"open": "10:00", "close": "17:00"},
                "fri": {"open": "10:00", "close": "18:00"},
                "sat": {"open": "10:00", "close": "18:00"},
                "sun": {"open": "11:00", "close": "16:00"},
            },
            "tags": ["waterfront", "local_artists", "maritime_art", "prints", "sculpture"],
            "payment_methods": ["cash", "card", "contactless"],
            "has_parking": False,
            "commission_work": True, "rotating_exhibitions": True,
        },
    },
    {
        "name": "Harbour View Theater",
        "address": "30 Portside Drive",
        "neighbourhood": "Harbour District",
        "details": {
            "category": "entertainment", "subcategory": "theater",
            "rating": 4.6, "review_count": 512,
            "hours": {
                "mon": None,
                "tue": {"open": "10:00", "close": "22:30"},
                "wed": {"open": "10:00", "close": "22:30"},
                "thu": {"open": "10:00", "close": "22:30"},
                "fri": {"open": "10:00", "close": "23:00"},
                "sat": {"open": "10:00", "close": "23:00"},
                "sun": {"open": "12:00", "close": "21:00"},
            },
            "tags": ["waterfront", "live_theater", "comedy", "drama", "music"],
            "capacity": 320, "bar": True, "accessible": True, "season_tickets": True,
        },
    },

    # ── OLD TOWN ─────────────────────────────────────────────────────────────

    {
        "name": "Bella Napoli",
        "address": "23 Market Square",
        "neighbourhood": "Old Town",
        "details": {
            "category": "restaurant", "cuisine": "italian",
            "price_range": "$$", "rating": 4.6, "review_count": 408,
            "hours": {
                "mon": None,
                "tue": {"open": "12:00", "close": "22:00"},
                "wed": {"open": "12:00", "close": "22:00"},
                "thu": {"open": "12:00", "close": "22:00"},
                "fri": {"open": "12:00", "close": "23:00"},
                "sat": {"open": "12:00", "close": "23:00"},
                "sun": {"open": "13:00", "close": "21:00"},
            },
            "tags": ["italian", "pizza", "pasta", "romantic", "family_friendly"],
            "accepts_reservations": True, "outdoor_seating": False,
            "wheelchair_accessible": True,
            "social": {"instagram": "@bellanapoli_portsmith"},
        },
    },
    {
        "name": "Le Petit Bistro",
        "address": "3 Market Square",
        "neighbourhood": "Old Town",
        "details": {
            "category": "restaurant", "cuisine": "french",
            "price_range": "$$$", "rating": 4.7, "review_count": 229,
            "hours": {
                "mon": None, "tue": None,
                "wed": {"open": "12:00", "close": "14:30"},
                "thu": {"open": "12:00", "close": "14:30"},
                "fri": {"open": "12:00", "close": "14:30"},
                "sat": {"open": "12:00", "close": "15:00"},
                "sun": None,
                "dinner": {
                    "wed": {"open": "19:00", "close": "22:00"},
                    "thu": {"open": "19:00", "close": "22:00"},
                    "fri": {"open": "19:00", "close": "22:30"},
                    "sat": {"open": "19:00", "close": "22:30"},
                },
            },
            "tags": ["fine_dining", "french", "wine", "romantic", "tasting_menu"],
            "accepts_reservations": True, "outdoor_seating": False,
            "dress_code": "smart_casual",
            "social": {"instagram": "@lepetitbistro"},
        },
    },
    {
        "name": "Old Town Hardware",
        "address": "55 Fisherman's Row",
        "neighbourhood": "Old Town",
        "details": {
            "category": "retail", "subcategory": "hardware",
            "rating": 4.2, "review_count": 91,
            "hours": {
                "mon": {"open": "08:00", "close": "17:30"},
                "tue": {"open": "08:00", "close": "17:30"},
                "wed": {"open": "08:00", "close": "17:30"},
                "thu": {"open": "08:00", "close": "17:30"},
                "fri": {"open": "08:00", "close": "17:30"},
                "sat": {"open": "09:00", "close": "16:00"},
                "sun": None,
            },
            "tags": ["family_owned", "tools", "local", "trade_accounts"],
            "payment_methods": ["cash", "card", "trade_account"],
            "has_parking": True, "trade_accounts": True,
        },
    },
    {
        "name": "Finch & Sons Barbers",
        "address": "9 Quay Street",
        "neighbourhood": "Old Town",
        "details": {
            "category": "service", "subcategory": "barber",
            "rating": 4.9, "review_count": 556,
            "hours": {
                "mon": None,
                "tue": {"open": "09:00", "close": "17:30"},
                "wed": {"open": "09:00", "close": "17:30"},
                "thu": {"open": "09:00", "close": "17:30"},
                "fri": {"open": "09:00", "close": "18:00"},
                "sat": {"open": "08:30", "close": "16:00"},
                "sun": None,
            },
            "tags": ["traditional", "walk_ins_welcome", "hot_shave", "family_owned"],
            "appointment_required": False,
            "specialties": ["hot_shave", "beard_trim", "classic_cuts", "kids_cuts"],
            "established": 1987,
        },
    },
    {
        "name": "The Clocktower Pub",
        "address": "1 Market Square",
        "neighbourhood": "Old Town",
        "details": {
            "category": "entertainment", "subcategory": "pub",
            "rating": 4.4, "review_count": 713,
            "hours": {
                "mon": {"open": "12:00", "close": "23:00"},
                "tue": {"open": "12:00", "close": "23:00"},
                "wed": {"open": "12:00", "close": "23:00"},
                "thu": {"open": "12:00", "close": "23:00"},
                "fri": {"open": "12:00", "close": "01:00"},
                "sat": {"open": "11:00", "close": "01:00"},
                "sun": {"open": "12:00", "close": "22:30"},
            },
            "tags": ["historic", "real_ale", "dog_friendly", "quiz_night", "family_friendly"],
            "live_music": False, "quiz_nights": ["thu"],
            "outdoor_seating": True, "age_restriction": 18,
            "wheelchair_accessible": True,
        },
    },
    {
        "name": "Portsmith Legal Group",
        "address": "14 Lighthouse Ave",
        "neighbourhood": "Old Town",
        "details": {
            "category": "service", "subcategory": "legal",
            "rating": 4.1, "review_count": 44,
            "hours": {
                "mon": {"open": "09:00", "close": "17:00"},
                "tue": {"open": "09:00", "close": "17:00"},
                "wed": {"open": "09:00", "close": "17:00"},
                "thu": {"open": "09:00", "close": "17:00"},
                "fri": {"open": "09:00", "close": "16:00"},
                "sat": None, "sun": None,
            },
            "tags": ["solicitors", "conveyancing", "family_law", "commercial"],
            "appointment_required": True,
            "specialties": ["property", "family_law", "commercial", "wills"],
            "established": 2001,
        },
    },
    {
        "name": "Portsmith Arms Hotel",
        "address": "50 Lighthouse Ave",
        "neighbourhood": "Old Town",
        "details": {
            "category": "accommodation", "subcategory": "hotel",
            "star_rating": 3, "rating": 3.8, "review_count": 445,
            "hours": {"reception": "24/7"},
            "tags": ["central", "budget_friendly", "bar", "breakfast_available"],
            "amenities": ["wifi", "bar", "breakfast", "parking_nearby"],
            "room_types": ["single", "double", "twin"],
            "pet_friendly": False,
            "price_per_night": {"low": 55, "high": 95},
        },
    },
    {
        "name": "Portsmith Accountancy Ltd.",
        "address": "20 Lighthouse Ave",
        "neighbourhood": "Old Town",
        "details": {
            "category": "service", "subcategory": "accountant",
            "rating": 4.3, "review_count": 52,
            "hours": {
                "mon": {"open": "09:00", "close": "17:00"},
                "tue": {"open": "09:00", "close": "17:00"},
                "wed": {"open": "09:00", "close": "17:00"},
                "thu": {"open": "09:00", "close": "17:00"},
                "fri": {"open": "09:00", "close": "16:30"},
                "sat": None, "sun": None,
            },
            "tags": ["accountancy", "tax", "small_business", "payroll", "vat"],
            "appointment_required": True,
            "specialties": ["self_assessment", "corporation_tax", "vat", "payroll", "bookkeeping"],
            "established": 1998,
        },
    },
    {
        "name": "Portsmith Tailors",
        "address": "11 Fisherman's Row",
        "neighbourhood": "Old Town",
        "details": {
            "category": "service", "subcategory": "tailor",
            "rating": 4.8, "review_count": 76,
            "hours": {
                "mon": {"open": "09:30", "close": "17:30"},
                "tue": {"open": "09:30", "close": "17:30"},
                "wed": {"open": "09:30", "close": "17:30"},
                "thu": {"open": "09:30", "close": "17:30"},
                "fri": {"open": "09:30", "close": "17:00"},
                "sat": {"open": "10:00", "close": "15:00"},
                "sun": None,
            },
            "tags": ["bespoke", "alterations", "suits", "traditional", "family_owned"],
            "appointment_required": True,
            "specialties": ["bespoke_suits", "alterations", "wedding_attire", "uniform_alterations"],
            "established": 1963,
        },
    },

    # ── NORTHGATE ────────────────────────────────────────────────────────────

    {
        "name": "Dragon Palace",
        "address": "88 Bay Street",
        "neighbourhood": "Northgate",
        "details": {
            "category": "restaurant", "cuisine": "chinese",
            "price_range": "$", "rating": 4.0, "review_count": 632,
            "hours": {
                "mon": {"open": "12:00", "close": "22:00"},
                "tue": {"open": "12:00", "close": "22:00"},
                "wed": {"open": "12:00", "close": "22:00"},
                "thu": {"open": "12:00", "close": "22:00"},
                "fri": {"open": "12:00", "close": "23:00"},
                "sat": {"open": "11:00", "close": "23:00"},
                "sun": {"open": "11:00", "close": "22:00"},
            },
            "tags": ["chinese", "dim_sum", "takeaway", "family_friendly", "large_groups"],
            "accepts_reservations": True, "outdoor_seating": False,
            "takeaway": True, "delivery": True,
        },
    },
    {
        "name": "Northgate Grocers",
        "address": "120 Canal Road",
        "neighbourhood": "Northgate",
        "details": {
            "category": "retail", "subcategory": "grocery",
            "rating": 3.9, "review_count": 229,
            "hours": {
                "mon": {"open": "07:00", "close": "21:00"},
                "tue": {"open": "07:00", "close": "21:00"},
                "wed": {"open": "07:00", "close": "21:00"},
                "thu": {"open": "07:00", "close": "21:00"},
                "fri": {"open": "07:00", "close": "21:00"},
                "sat": {"open": "07:00", "close": "21:00"},
                "sun": {"open": "09:00", "close": "18:00"},
            },
            "tags": ["grocery", "local_produce", "organic", "deli"],
            "payment_methods": ["cash", "card", "contactless", "vouchers"],
            "has_parking": True, "delivery": True,
        },
    },
    {
        "name": "AutoFix Portsmith",
        "address": "45 Tidewater Lane",
        "neighbourhood": "Northgate",
        "details": {
            "category": "service", "subcategory": "auto_repair",
            "rating": 4.5, "review_count": 187,
            "hours": {
                "mon": {"open": "08:00", "close": "17:30"},
                "tue": {"open": "08:00", "close": "17:30"},
                "wed": {"open": "08:00", "close": "17:30"},
                "thu": {"open": "08:00", "close": "17:30"},
                "fri": {"open": "08:00", "close": "17:00"},
                "sat": {"open": "09:00", "close": "13:00"},
                "sun": None,
            },
            "tags": ["mot", "servicing", "diagnostics", "tyres", "family_owned"],
            "appointment_required": True,
            "specialties": ["mot", "full_service", "diagnostics", "electric_vehicles"],
            "approved_brands": ["Ford", "Vauxhall", "Honda", "Toyota", "Nissan"],
        },
    },
    {
        "name": "The Grand Hotel Portsmith",
        "address": "1 Bay Street",
        "neighbourhood": "Northgate",
        "details": {
            "category": "accommodation", "subcategory": "hotel",
            "star_rating": 4, "rating": 4.2, "review_count": 891,
            "hours": {"reception": "24/7"},
            "tags": ["business_friendly", "conference_facilities", "bar", "restaurant", "spa"],
            "amenities": ["pool", "gym", "spa", "wifi", "parking", "restaurant", "bar",
                          "conference_rooms", "valet"],
            "room_types": ["single", "double", "executive", "suite"],
            "pet_friendly": False,
            "price_per_night": {"low": 120, "high": 340},
        },
    },
    {
        "name": "Lotus Spa & Wellness",
        "address": "78 Canal Road",
        "neighbourhood": "Northgate",
        "details": {
            "category": "service", "subcategory": "spa",
            "rating": 4.7, "review_count": 263,
            "hours": {
                "mon": {"open": "10:00", "close": "20:00"},
                "tue": {"open": "10:00", "close": "20:00"},
                "wed": {"open": "10:00", "close": "20:00"},
                "thu": {"open": "10:00", "close": "20:00"},
                "fri": {"open": "10:00", "close": "20:00"},
                "sat": {"open": "09:00", "close": "19:00"},
                "sun": {"open": "10:00", "close": "18:00"},
            },
            "tags": ["massage", "facials", "relaxation", "couples_treatments"],
            "appointment_required": True,
            "specialties": ["hot_stone", "deep_tissue", "aromatherapy", "reflexology"],
            "gender_policy": "all_welcome",
        },
    },
    {
        "name": "Spice Garden",
        "address": "67 Bay Street",
        "neighbourhood": "Northgate",
        "details": {
            "category": "restaurant", "cuisine": "indian",
            "price_range": "$$", "rating": 4.6, "review_count": 487,
            "hours": {
                "mon": {"open": "12:00", "close": "22:00"},
                "tue": {"open": "12:00", "close": "22:00"},
                "wed": {"open": "12:00", "close": "22:00"},
                "thu": {"open": "12:00", "close": "22:00"},
                "fri": {"open": "12:00", "close": "23:00"},
                "sat": {"open": "12:00", "close": "23:00"},
                "sun": {"open": "13:00", "close": "22:00"},
            },
            "tags": ["indian", "curry", "tandoor", "takeaway", "vegetarian_options"],
            "accepts_reservations": True, "outdoor_seating": False,
            "takeaway": True, "delivery": True,
            "social": {"instagram": "@spicegarden_portsmith"},
        },
    },
    {
        "name": "Sol y Mar",
        "address": "77 Bay Street",
        "neighbourhood": "Northgate",
        "details": {
            "category": "restaurant", "cuisine": "mexican",
            "price_range": "$", "rating": 4.3, "review_count": 291,
            "hours": {
                "mon": {"open": "12:00", "close": "22:00"},
                "tue": {"open": "12:00", "close": "22:00"},
                "wed": {"open": "12:00", "close": "22:00"},
                "thu": {"open": "12:00", "close": "22:00"},
                "fri": {"open": "12:00", "close": "23:00"},
                "sat": {"open": "12:00", "close": "23:00"},
                "sun": {"open": "12:00", "close": "21:00"},
            },
            "tags": ["mexican", "tacos", "margaritas", "vegan_options", "takeaway", "lively"],
            "accepts_reservations": False, "outdoor_seating": True,
            "takeaway": True,
            "happy_hour": {"days": ["mon", "tue", "wed", "thu"], "time": "17:00-19:00"},
        },
    },
    {
        "name": "Mango Bay Caribbean",
        "address": "56 Bay Street",
        "neighbourhood": "Northgate",
        "details": {
            "category": "restaurant", "cuisine": "caribbean",
            "price_range": "$$", "rating": 4.5, "review_count": 178,
            "hours": {
                "mon": None,
                "tue": {"open": "12:00", "close": "21:00"},
                "wed": {"open": "12:00", "close": "21:00"},
                "thu": {"open": "12:00", "close": "22:00"},
                "fri": {"open": "12:00", "close": "22:30"},
                "sat": {"open": "12:00", "close": "22:30"},
                "sun": {"open": "13:00", "close": "20:00"},
            },
            "tags": ["caribbean", "jerk", "rum_cocktails", "vegan_options", "lively"],
            "accepts_reservations": True, "outdoor_seating": True,
            "live_music": True, "music_nights": ["fri", "sat"],
        },
    },
    {
        "name": "Bay Street Electronics",
        "address": "99 Bay Street",
        "neighbourhood": "Northgate",
        "details": {
            "category": "retail", "subcategory": "electronics",
            "rating": 3.8, "review_count": 344,
            "hours": {
                "mon": {"open": "09:00", "close": "18:00"},
                "tue": {"open": "09:00", "close": "18:00"},
                "wed": {"open": "09:00", "close": "18:00"},
                "thu": {"open": "09:00", "close": "18:00"},
                "fri": {"open": "09:00", "close": "19:00"},
                "sat": {"open": "09:00", "close": "18:00"},
                "sun": {"open": "10:00", "close": "16:00"},
            },
            "tags": ["electronics", "repairs", "accessories", "phones", "laptops"],
            "payment_methods": ["cash", "card", "contactless", "finance"],
            "has_parking": True, "repair_service": True, "trade_in": True,
        },
    },

    # ── RIVERSIDE ─────────────────────────────────────────────────────────────

    {
        "name": "River Bend Bakery",
        "address": "33 Quay Street",
        "neighbourhood": "Riverside",
        "details": {
            "category": "restaurant", "cuisine": "bakery",
            "price_range": "$", "rating": 4.8, "review_count": 441,
            "hours": {
                "mon": {"open": "07:00", "close": "16:00"},
                "tue": {"open": "07:00", "close": "16:00"},
                "wed": {"open": "07:00", "close": "16:00"},
                "thu": {"open": "07:00", "close": "16:00"},
                "fri": {"open": "07:00", "close": "17:00"},
                "sat": {"open": "07:00", "close": "17:00"},
                "sun": {"open": "08:00", "close": "14:00"},
            },
            "tags": ["artisan", "sourdough", "pastries", "vegan_options", "gluten_free_available"],
            "accepts_reservations": False, "outdoor_seating": True,
            "allergen_info": True, "weekly_specials": True,
        },
    },
    {
        "name": "The Riverside Vegan",
        "address": "41 Quay Street",
        "neighbourhood": "Riverside",
        "details": {
            "category": "restaurant", "cuisine": "vegan",
            "price_range": "$$", "rating": 4.5, "review_count": 318,
            "hours": {
                "mon": None,
                "tue": {"open": "11:00", "close": "21:00"},
                "wed": {"open": "11:00", "close": "21:00"},
                "thu": {"open": "11:00", "close": "21:00"},
                "fri": {"open": "11:00", "close": "22:00"},
                "sat": {"open": "10:00", "close": "22:00"},
                "sun": {"open": "10:00", "close": "20:00"},
            },
            "tags": ["vegan", "plant_based", "organic", "gluten_free_available", "cozy"],
            "accepts_reservations": True, "outdoor_seating": False,
            "fully_vegan": True,
            "social": {"instagram": "@riverside_vegan"},
        },
    },
    {
        "name": "Thai Orchid",
        "address": "34 Canal Road",
        "neighbourhood": "Riverside",
        "details": {
            "category": "restaurant", "cuisine": "thai",
            "price_range": "$$", "rating": 4.5, "review_count": 356,
            "hours": {
                "mon": None,
                "tue": {"open": "12:00", "close": "21:30"},
                "wed": {"open": "12:00", "close": "21:30"},
                "thu": {"open": "12:00", "close": "21:30"},
                "fri": {"open": "12:00", "close": "22:00"},
                "sat": {"open": "12:00", "close": "22:00"},
                "sun": {"open": "13:00", "close": "21:00"},
            },
            "tags": ["thai", "authentic", "vegetarian_options", "takeaway", "byo_wine"],
            "accepts_reservations": True, "outdoor_seating": False,
            "takeaway": True, "byo": True,
        },
    },
    {
        "name": "Quay Street Deli",
        "address": "8 Quay Street",
        "neighbourhood": "Riverside",
        "details": {
            "category": "restaurant", "cuisine": "deli",
            "price_range": "$", "rating": 4.6, "review_count": 203,
            "hours": {
                "mon": {"open": "07:30", "close": "16:00"},
                "tue": {"open": "07:30", "close": "16:00"},
                "wed": {"open": "07:30", "close": "16:00"},
                "thu": {"open": "07:30", "close": "16:00"},
                "fri": {"open": "07:30", "close": "16:00"},
                "sat": {"open": "08:00", "close": "15:00"},
                "sun": None,
            },
            "tags": ["deli", "sandwiches", "local_produce", "takeaway", "catering"],
            "accepts_reservations": False, "outdoor_seating": False,
            "catering": True,
            "specialty_items": ["smoked_fish", "local_cheese", "charcuterie"],
        },
    },
    {
        "name": "Portsmith Pharmacy",
        "address": "12 Tidewater Lane",
        "neighbourhood": "Riverside",
        "details": {
            "category": "retail", "subcategory": "pharmacy",
            "rating": 4.3, "review_count": 156,
            "hours": {
                "mon": {"open": "08:30", "close": "18:30"},
                "tue": {"open": "08:30", "close": "18:30"},
                "wed": {"open": "08:30", "close": "18:30"},
                "thu": {"open": "08:30", "close": "18:30"},
                "fri": {"open": "08:30", "close": "18:30"},
                "sat": {"open": "09:00", "close": "17:00"},
                "sun": {"open": "10:00", "close": "14:00"},
            },
            "tags": ["nhs", "prescriptions", "travel_health", "consultations"],
            "payment_methods": ["cash", "card", "contactless"],
            "services": ["prescriptions", "travel_vaccinations", "blood_pressure", "diabetes_check"],
        },
    },
    {
        "name": "Dr. Chen Dentistry",
        "address": "5 Canal Road",
        "neighbourhood": "Riverside",
        "details": {
            "category": "service", "subcategory": "dentist",
            "rating": 4.7, "review_count": 192,
            "hours": {
                "mon": {"open": "08:30", "close": "17:00"},
                "tue": {"open": "08:30", "close": "17:00"},
                "wed": {"open": "08:30", "close": "17:00"},
                "thu": {"open": "08:30", "close": "19:00"},
                "fri": {"open": "08:30", "close": "16:00"},
                "sat": {"open": "09:00", "close": "13:00"},
                "sun": None,
            },
            "tags": ["nhs", "private", "cosmetic", "emergency_appointments"],
            "appointment_required": True,
            "specialties": ["implants", "whitening", "orthodontics", "emergency"],
            "nhs_accepting": True,
        },
    },
    {
        "name": "Riverside Cinema",
        "address": "100 Quay Street",
        "neighbourhood": "Riverside",
        "details": {
            "category": "entertainment", "subcategory": "cinema",
            "rating": 4.4, "review_count": 1204,
            "hours": {
                "mon": {"open": "13:00", "close": "23:00"},
                "tue": {"open": "13:00", "close": "23:00"},
                "wed": {"open": "13:00", "close": "23:00"},
                "thu": {"open": "13:00", "close": "23:00"},
                "fri": {"open": "13:00", "close": "00:00"},
                "sat": {"open": "11:00", "close": "00:00"},
                "sun": {"open": "11:00", "close": "22:00"},
            },
            "tags": ["multiplex", "imax", "3d", "accessible", "parking"],
            "screens": 6, "imax": True, "has_parking": True,
            "concessions": ["popcorn", "hotdogs", "nachos", "ice_cream", "bar"],
        },
    },
    {
        "name": "Portsmith Veterinary Clinic",
        "address": "90 Tidewater Lane",
        "neighbourhood": "Riverside",
        "details": {
            "category": "service", "subcategory": "veterinarian",
            "rating": 4.8, "review_count": 341,
            "hours": {
                "mon": {"open": "08:30", "close": "18:30"},
                "tue": {"open": "08:30", "close": "18:30"},
                "wed": {"open": "08:30", "close": "18:30"},
                "thu": {"open": "08:30", "close": "18:30"},
                "fri": {"open": "08:30", "close": "18:00"},
                "sat": {"open": "09:00", "close": "13:00"},
                "sun": None,
            },
            "tags": ["small_animals", "emergency", "surgery", "vaccinations", "microchipping"],
            "appointment_required": True,
            "specialties": ["small_animals", "exotic_pets", "surgery", "dental"],
            "emergency_line": True, "out_of_hours": True,
        },
    },
    {
        "name": "The Art Depot",
        "address": "15 Quay Street",
        "neighbourhood": "Riverside",
        "details": {
            "category": "retail", "subcategory": "art_supplies",
            "rating": 4.6, "review_count": 88,
            "hours": {
                "mon": {"open": "09:30", "close": "17:30"},
                "tue": {"open": "09:30", "close": "17:30"},
                "wed": {"open": "09:30", "close": "17:30"},
                "thu": {"open": "09:30", "close": "17:30"},
                "fri": {"open": "09:30", "close": "17:30"},
                "sat": {"open": "10:00", "close": "16:00"},
                "sun": None,
            },
            "tags": ["art_supplies", "framing", "classes", "independent", "local_artists"],
            "payment_methods": ["cash", "card"],
            "has_parking": False, "workshops": True, "framing_service": True,
        },
    },

    # ── UNIVERSITY QUARTER ────────────────────────────────────────────────────

    {
        "name": "The Hungry Scholar",
        "address": "3 Lighthouse Ave",
        "neighbourhood": "University Quarter",
        "details": {
            "category": "restaurant", "cuisine": "american",
            "price_range": "$", "rating": 3.9, "review_count": 887,
            "hours": {
                "mon": {"open": "08:00", "close": "22:00"},
                "tue": {"open": "08:00", "close": "22:00"},
                "wed": {"open": "08:00", "close": "22:00"},
                "thu": {"open": "08:00", "close": "22:00"},
                "fri": {"open": "08:00", "close": "23:00"},
                "sat": {"open": "09:00", "close": "23:00"},
                "sun": {"open": "10:00", "close": "21:00"},
            },
            "tags": ["student_discount", "burgers", "all_day_breakfast", "wifi", "large_portions"],
            "accepts_reservations": False, "outdoor_seating": True,
            "student_discount": True, "wifi": True,
        },
    },
    {
        "name": "Quarter Note Jazz Club",
        "address": "22 Lighthouse Ave",
        "neighbourhood": "University Quarter",
        "details": {
            "category": "entertainment", "subcategory": "live_music",
            "rating": 4.8, "review_count": 376,
            "hours": {
                "mon": None, "tue": None,
                "wed": {"open": "19:00", "close": "01:00"},
                "thu": {"open": "19:00", "close": "01:00"},
                "fri": {"open": "19:00", "close": "02:00"},
                "sat": {"open": "19:00", "close": "02:00"},
                "sun": {"open": "18:00", "close": "23:00"},
            },
            "tags": ["jazz", "live_music", "cocktails", "intimate", "ticketed_events"],
            "live_music": True,
            "music_nights": ["wed", "thu", "fri", "sat", "sun"],
            "age_restriction": 18, "capacity": 80,
            "social": {"instagram": "@quarternote_portsmith"},
        },
    },
    {
        "name": "University Bookshop",
        "address": "University Quarter, Main Campus",
        "neighbourhood": "University Quarter",
        "details": {
            "category": "retail", "subcategory": "bookshop",
            "rating": 4.1, "review_count": 138,
            "hours": {
                "mon": {"open": "09:00", "close": "18:00"},
                "tue": {"open": "09:00", "close": "18:00"},
                "wed": {"open": "09:00", "close": "18:00"},
                "thu": {"open": "09:00", "close": "18:00"},
                "fri": {"open": "09:00", "close": "17:00"},
                "sat": {"open": "10:00", "close": "15:00"},
                "sun": None,
            },
            "tags": ["academic", "textbooks", "stationery", "student_discount"],
            "payment_methods": ["cash", "card", "contactless"],
            "has_parking": False, "student_discount": True,
            "specialties": ["academic", "textbooks", "course_materials"],
        },
    },
    {
        "name": "Campus Bike & Sports",
        "address": "18 Lighthouse Ave",
        "neighbourhood": "University Quarter",
        "details": {
            "category": "retail", "subcategory": "sporting_goods",
            "rating": 4.3, "review_count": 97,
            "hours": {
                "mon": {"open": "09:00", "close": "18:00"},
                "tue": {"open": "09:00", "close": "18:00"},
                "wed": {"open": "09:00", "close": "18:00"},
                "thu": {"open": "09:00", "close": "18:00"},
                "fri": {"open": "09:00", "close": "18:00"},
                "sat": {"open": "09:00", "close": "17:00"},
                "sun": {"open": "11:00", "close": "15:00"},
            },
            "tags": ["bikes", "repairs", "rental", "sports_equipment", "student_discount"],
            "payment_methods": ["cash", "card"],
            "has_parking": False, "bike_repair": True, "bike_rental": True,
            "student_discount": True,
        },
    },
    {
        "name": "Green Leaf Cafe",
        "address": "6 Lighthouse Ave",
        "neighbourhood": "University Quarter",
        "details": {
            "category": "restaurant", "cuisine": "vegan",
            "price_range": "$", "rating": 4.4, "review_count": 254,
            "hours": {
                "mon": {"open": "08:00", "close": "17:00"},
                "tue": {"open": "08:00", "close": "17:00"},
                "wed": {"open": "08:00", "close": "17:00"},
                "thu": {"open": "08:00", "close": "17:00"},
                "fri": {"open": "08:00", "close": "17:00"},
                "sat": {"open": "09:00", "close": "16:00"},
                "sun": None,
            },
            "tags": ["vegan", "organic", "smoothies", "wifi", "student_friendly"],
            "accepts_reservations": False, "outdoor_seating": False,
            "fully_vegan": True, "wifi": True,
        },
    },

    # ── INDUSTRIAL PORT ───────────────────────────────────────────────────────

    {
        "name": "Port Canteen",
        "address": "Portsmith Docks, Gate 3",
        "neighbourhood": "Industrial Port",
        "details": {
            "category": "restaurant", "cuisine": "british",
            "price_range": "$", "rating": 3.7, "review_count": 68,
            "hours": {
                "mon": {"open": "05:30", "close": "14:00"},
                "tue": {"open": "05:30", "close": "14:00"},
                "wed": {"open": "05:30", "close": "14:00"},
                "thu": {"open": "05:30", "close": "14:00"},
                "fri": {"open": "05:30", "close": "14:00"},
                "sat": {"open": "06:00", "close": "12:00"},
                "sun": None,
            },
            "tags": ["workers_canteen", "early_opening", "full_english", "cash_only"],
            "accepts_reservations": False, "outdoor_seating": False, "cash_only": True,
        },
    },
    {
        "name": "Marine Supply Co.",
        "address": "Portsmith Docks, Unit 12",
        "neighbourhood": "Industrial Port",
        "details": {
            "category": "retail", "subcategory": "marine_hardware",
            "rating": 4.6, "review_count": 112,
            "hours": {
                "mon": {"open": "07:00", "close": "17:00"},
                "tue": {"open": "07:00", "close": "17:00"},
                "wed": {"open": "07:00", "close": "17:00"},
                "thu": {"open": "07:00", "close": "17:00"},
                "fri": {"open": "07:00", "close": "17:00"},
                "sat": {"open": "08:00", "close": "13:00"},
                "sun": None,
            },
            "tags": ["marine", "rope", "fittings", "wholesale", "trade"],
            "payment_methods": ["cash", "card", "trade_account", "invoice"],
            "has_parking": True, "trade_accounts": True, "wholesale": True,
        },
    },
    {
        "name": "Port View Hostel",
        "address": "2 Dock Road",
        "neighbourhood": "Industrial Port",
        "details": {
            "category": "accommodation", "subcategory": "hostel",
            "star_rating": 1, "rating": 4.0, "review_count": 533,
            "hours": {"reception": "07:00-23:00"},
            "tags": ["budget", "backpackers", "social", "kitchen_facilities", "lockers"],
            "amenities": ["wifi", "shared_kitchen", "lockers", "common_room", "laundry"],
            "room_types": ["dorm_4", "dorm_8", "private_double"],
            "pet_friendly": False,
            "price_per_night": {"low": 18, "high": 45},
        },
    },
    {
        "name": "Ironside Auto",
        "address": "Industrial Estate, Unit 7",
        "neighbourhood": "Industrial Port",
        "details": {
            "category": "service", "subcategory": "auto_repair",
            "rating": 4.3, "review_count": 229,
            "hours": {
                "mon": {"open": "08:00", "close": "18:00"},
                "tue": {"open": "08:00", "close": "18:00"},
                "wed": {"open": "08:00", "close": "18:00"},
                "thu": {"open": "08:00", "close": "18:00"},
                "fri": {"open": "08:00", "close": "17:00"},
                "sat": {"open": "09:00", "close": "14:00"},
                "sun": None,
            },
            "tags": ["hgv", "fleet", "commercial_vehicles", "breakdown", "welding"],
            "appointment_required": False,
            "specialties": ["hgv", "fleet_maintenance", "welding", "commercial", "breakdown_recovery"],
            "approved_brands": ["Mercedes", "Volvo", "DAF", "MAN", "Iveco"],
        },
    },
    {
        "name": "The Rusty Anchor",
        "address": "Portsmith Docks, Pier 4",
        "neighbourhood": "Industrial Port",
        "details": {
            "category": "entertainment", "subcategory": "bar",
            "rating": 4.2, "review_count": 384,
            "hours": {
                "mon": {"open": "12:00", "close": "23:00"},
                "tue": {"open": "12:00", "close": "23:00"},
                "wed": {"open": "12:00", "close": "23:00"},
                "thu": {"open": "12:00", "close": "23:00"},
                "fri": {"open": "12:00", "close": "01:00"},
                "sat": {"open": "12:00", "close": "01:00"},
                "sun": {"open": "13:00", "close": "22:00"},
            },
            "tags": ["waterfront", "working_port", "real_ale", "darts", "pool_table"],
            "live_music": True, "music_nights": ["fri", "sat"],
            "outdoor_seating": True, "age_restriction": 18,
        },
    },
    {
        "name": "Portsmith Plumbing & Heating",
        "address": "Industrial Estate, Unit 2",
        "neighbourhood": "Industrial Port",
        "details": {
            "category": "service", "subcategory": "plumber",
            "rating": 4.4, "review_count": 167,
            "hours": {
                "mon": {"open": "07:30", "close": "17:30"},
                "tue": {"open": "07:30", "close": "17:30"},
                "wed": {"open": "07:30", "close": "17:30"},
                "thu": {"open": "07:30", "close": "17:30"},
                "fri": {"open": "07:30", "close": "17:00"},
                "sat": {"open": "08:00", "close": "13:00"},
                "sun": None,
            },
            "tags": ["plumbing", "heating", "gas_safe", "emergency_callout", "boilers"],
            "appointment_required": False,
            "specialties": ["boiler_installation", "underfloor_heating", "bathroom_fitting", "emergency"],
            "gas_safe_registered": True, "emergency_callout": True,
        },
    },
    {
        "name": "Old Brewery Tap",
        "address": "Portsmith Docks, Unit 1",
        "neighbourhood": "Industrial Port",
        "details": {
            "category": "entertainment", "subcategory": "bar",
            "rating": 4.5, "review_count": 623,
            "hours": {
                "mon": None, "tue": None,
                "wed": {"open": "16:00", "close": "23:00"},
                "thu": {"open": "16:00", "close": "23:00"},
                "fri": {"open": "14:00", "close": "01:00"},
                "sat": {"open": "12:00", "close": "01:00"},
                "sun": {"open": "12:00", "close": "22:00"},
            },
            "tags": ["craft_beer", "microbrewery", "waterfront", "tours_available", "outdoor_seating"],
            "live_music": True, "music_nights": ["fri", "sat"],
            "outdoor_seating": True, "tours": True, "age_restriction": 18,
        },
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

            print(f"Inserting {len(BUSINESSES)} businesses …")
            cur.executemany(
                """
                INSERT INTO businesses (name, address, neighbourhood, details)
                VALUES (%(name)s, %(address)s, %(neighbourhood)s, %(details)s)
                """,
                [
                    {**b, "details": json.dumps(b["details"])}
                    for b in BUSINESSES
                ],
            )

            cur.execute("SELECT COUNT(*) FROM businesses")
            (count,) = cur.fetchone()
            print(f"Done — {count} rows in businesses.")

        conn.commit()


if __name__ == "__main__":
    main()
