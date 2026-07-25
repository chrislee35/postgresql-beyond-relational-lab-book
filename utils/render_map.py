#!/usr/bin/env python3.12
"""
Render Portsmith map as SVG from PostGIS geometry data.

Usage:
    python utils/render_map.py portsmith_map.svg
"""

import json
import sys
import xml.etree.ElementTree as ET
import psycopg

DSN = "dbname=portsmith"
OUT = sys.argv[1] if len(sys.argv) > 1 else "portsmith_map.svg"

# ---------------------------------------------------------------------------
# Canvas and coordinate transform
# ---------------------------------------------------------------------------

W, H       = 920, 860
PAD        = 48
SEA_BOTTOM = 50.673

LON_MIN, LON_MAX = -1.8320, -1.7480
LAT_MIN, LAT_MAX = SEA_BOTTOM, 50.766

DRAW_W = W - 2 * PAD
DRAW_H = H - 2 * PAD


def tx(lon: float) -> float:
    return PAD + (lon - LON_MIN) / (LON_MAX - LON_MIN) * DRAW_W


def ty(lat: float) -> float:
    return H - PAD - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * DRAW_H


def ring_to_points(ring: list) -> str:
    return " ".join(f"{tx(lon):.2f},{ty(lat):.2f}" for lon, lat in ring)


def coords_to_path(coords: list) -> str:
    d = [f"M {tx(coords[0][0]):.2f} {ty(coords[0][1]):.2f}"]
    for lon, lat in coords[1:]:
        d.append(f"L {tx(lon):.2f} {ty(lat):.2f}")
    return " ".join(d)


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

NEIGHBOURHOOD_STYLE = {
    "Harbour District":   {"fill": "#c2ddf0", "label_color": "#1a4a6b"},
    "Industrial Port":    {"fill": "#d4cfc5", "label_color": "#4a3f30"},
    "Old Town":           {"fill": "#f5e4c5", "label_color": "#5a3e00"},
    "Northgate":          {"fill": "#d6ecda", "label_color": "#1e5c1e"},
    "Riverside":          {"fill": "#cae3f5", "label_color": "#1a4a6b"},
    "University Quarter": {"fill": "#e6d6f0", "label_color": "#4a1a6b"},
}

ROAD_STYLE = {
    "road_motorway":  {"stroke": "#888888", "stroke-width": "3.5",  "dash": None},
    "road_arterial":  {"stroke": "#aaaaaa", "stroke-width": "2.0",  "dash": None},
    "road_secondary": {"stroke": "#bbbbbb", "stroke-width": "1.4",  "dash": None},
    "road_local":     {"stroke": "#cccccc", "stroke-width": "0.9",  "dash": "4,3"},
}

# ---------------------------------------------------------------------------
# Representative businesses to label: name → (display text, anchor, dx, dy)
# anchor: "start" = label right of dot, "end" = label left of dot
# ---------------------------------------------------------------------------

FEATURED: dict[str, tuple[str, str, int, int]] = {
    # Harbour District
    "The Gilded Clam":           ("The Gilded Clam",     "start",   7,  3),
    "Harbour View Theater":      ("Harbour View Theatre","end",     -7,  3),
    # Old Town
    "Old Town Hardware":         ("Old Town Hardware",   "end",     -7,  3),
    "The Clocktower Pub":        ("Clocktower Pub",      "start",    7,  3),
    # Northgate
    "Northgate Grocers":         ("Northgate Grocers",   "end",     -7,  3),
    "The Grand Hotel Portsmith": ("Grand Hotel",         "start",    7,  3),
    # Riverside
    "Riverside Cinema":          ("Riverside Cinema",    "end",     -7, -3),
    "Dr. Chen Dentistry":        ("Dr. Chen Dentistry",  "end",     -7,  3),
    # University Quarter
    "The Hungry Scholar":        ("Hungry Scholar",      "start",    7,  3),
    "Quarter Note Jazz Club":    ("Quarter Note Jazz",   "start",    7,  3),
    # Industrial Port
    "Old Brewery Tap":           ("Old Brewery Tap",     "start",    7,  3),
    "Ironside Auto":             ("Ironside Auto",       "start",    7,  3),
}

# ---------------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------------

with psycopg.connect(DSN) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 'neighborhood'          AS layer, name AS label,
                   ST_AsGeoJSON(geom)      AS gj
            FROM   neighborhoods
            UNION ALL
            SELECT 'park',       name, ST_AsGeoJSON(geom) FROM parks
            UNION ALL
            SELECT 'road_' || road_type, name, ST_AsGeoJSON(geom)
            FROM   city_infrastructure
            UNION ALL
            SELECT 'business',   name, ST_AsGeoJSON(geom)
            FROM   businesses WHERE geom IS NOT NULL
            UNION ALL
            SELECT 'nb_centroid', name,
                   ST_AsGeoJSON(ST_Centroid(geom))
            FROM   neighborhoods
        """)
        rows = cur.fetchall()

features: dict[str, list] = {}
for layer, label, gj in rows:
    geo = json.loads(gj)
    features.setdefault(layer, []).append({"label": label, "geo": geo})

# ---------------------------------------------------------------------------
# Build SVG
# ---------------------------------------------------------------------------

svg = ET.Element("svg", {
    "xmlns":   "http://www.w3.org/2000/svg",
    "width":   str(W),
    "height":  str(H),
    "viewBox": f"0 0 {W} {H}",
})

defs = ET.SubElement(svg, "defs")

# ── Organic-border displacement filter ─────────────────────────────────────
# Applied to the entire neighborhoods group so shared borders stay coherent:
# both sides of every boundary are displaced by exactly the same pixel map,
# leaving no gaps or overlaps.
org = ET.SubElement(defs, "filter", {
    "id":          "organic",
    "x":           "0", "y": "0",
    "width":       str(W), "height": str(H),
    "filterUnits": "userSpaceOnUse",
    "color-interpolation-filters": "linearRGB",
})
ET.SubElement(org, "feTurbulence", {
    "type":          "fractalNoise",
    "baseFrequency": "0.018",
    "numOctaves":    "3",
    "seed":          "17",
    "result":        "noise",
})
ET.SubElement(org, "feDisplacementMap", {
    "in":             "SourceGraphic",
    "in2":            "noise",
    "scale":          "13",
    "xChannelSelector": "R",
    "yChannelSelector": "G",
})

# ── Drop-shadow filter for labels ──────────────────────────────────────────
filt = ET.SubElement(defs, "filter", {
    "id": "lbl-shadow",
    "x": "-10%", "y": "-20%", "width": "120%", "height": "140%",
})
ET.SubElement(filt, "feFlood",     {"flood-color": "white", "flood-opacity": "0.72", "result": "bg"})
ET.SubElement(filt, "feComposite", {"in": "bg", "in2": "SourceGraphic", "operator": "over"})

# ── Sea background (full canvas) ───────────────────────────────────────────
ET.SubElement(svg, "rect", {
    "x": "0", "y": "0", "width": str(W), "height": str(H),
    "fill": "#a8d4f0",
})

# Subtle gradient darkening toward the waterfront
sea_top_y = ty(50.690)
grad = ET.SubElement(defs, "linearGradient", {
    "id": "sea-grad", "x1": "0", "y1": "0", "x2": "0", "y2": "1",
    "gradientUnits": "userSpaceOnUse",
    "y1": "0", "y2": str(sea_top_y),
})
ET.SubElement(grad, "stop", {"offset": "0%",   "stop-color": "#6aade0", "stop-opacity": "0.5"})
ET.SubElement(grad, "stop", {"offset": "100%", "stop-color": "#a8d4f0", "stop-opacity": "0"})
ET.SubElement(svg, "rect", {
    "x": "0", "y": "0", "width": str(W), "height": str(sea_top_y),
    "fill": "url(#sea-grad)",
})

# ── Land background (outside city boundary) ────────────────────────────────
ET.SubElement(svg, "rect", {
    "x": str(PAD), "y": str(PAD),
    "width":  str(DRAW_W),
    "height": str(ty(LAT_MIN) - PAD),   # only the land portion
    "fill": "#e8e4dc",
})

# ── Neighbourhood fills — entire group gets organic displacement ────────────
nb_group = ET.SubElement(svg, "g", {"id": "neighborhoods", "filter": "url(#organic)"})
for f in features.get("neighborhood", []):
    ring = f["geo"]["coordinates"][0]
    style = NEIGHBOURHOOD_STYLE.get(f["label"], {"fill": "#eeeeee"})
    ET.SubElement(nb_group, "polygon", {
        "points":          ring_to_points(ring),
        "fill":            style["fill"],
        "stroke":          "#7a9ab0",
        "stroke-width":    "1.4",
        "stroke-linejoin": "round",
    })

# ── Parks (on top of displaced neighbourhoods, own edges stay sharp) ────────
park_group = ET.SubElement(svg, "g", {"id": "parks"})
for f in features.get("park", []):
    ring = f["geo"]["coordinates"][0]
    ET.SubElement(park_group, "polygon", {
        "points":       ring_to_points(ring),
        "fill":         "#7ec87e",
        "stroke":       "#3a8a3a",
        "stroke-width": "0.9",
        "opacity":      "0.88",
    })

# ── Roads ──────────────────────────────────────────────────────────────────
road_group = ET.SubElement(svg, "g", {"id": "roads"})
for layer in ("road_motorway", "road_arterial", "road_secondary", "road_local"):
    s = ROAD_STYLE[layer]
    for f in features.get(layer, []):
        el = ET.SubElement(road_group, "path", {
            "d":               coords_to_path(f["geo"]["coordinates"]),
            "fill":            "none",
            "stroke":          s["stroke"],
            "stroke-width":    s["stroke-width"],
            "stroke-linecap":  "round",
            "stroke-linejoin": "round",
        })
        if s["dash"]:
            el.set("stroke-dasharray", s["dash"])

# ── Business dots ──────────────────────────────────────────────────────────
biz_group = ET.SubElement(svg, "g", {"id": "businesses"})
for f in features.get("business", []):
    lon, lat = f["geo"]["coordinates"]
    is_featured = f["label"] in FEATURED
    ET.SubElement(biz_group, "circle", {
        "cx":           f"{tx(lon):.2f}",
        "cy":           f"{ty(lat):.2f}",
        "r":            "3.8" if is_featured else "2.8",
        "fill":         "#c0392b" if is_featured else "#d35400",
        "fill-opacity": "0.85",
        "stroke":       "white",
        "stroke-width": "1.0" if is_featured else "0.7",
    })

# ── Business labels (featured only) ───────────────────────────────────────
biz_label_group = ET.SubElement(svg, "g", {
    "id":          "business-labels",
    "font-family": "Arial, Helvetica, sans-serif",
    "font-size":   "7.5",
})
for f in features.get("business", []):
    if f["label"] not in FEATURED:
        continue
    lon, lat   = f["geo"]["coordinates"]
    disp, anchor, dx, dy = FEATURED[f["label"]]
    cx, cy = tx(lon), ty(lat)

    # White halo then coloured text (paint-order trick)
    ET.SubElement(biz_label_group, "text", {
        "x":            f"{cx + dx:.1f}",
        "y":            f"{cy + dy:.1f}",
        "text-anchor":  anchor,
        "fill":         "#1a1a2e",
        "stroke":       "white",
        "stroke-width": "2.8",
        "paint-order":  "stroke fill",
        "font-weight":  "600",
    }).text = disp

# ── Neighbourhood labels ───────────────────────────────────────────────────
lbl_group = ET.SubElement(svg, "g", {
    "id":          "nb-labels",
    "font-family": "Georgia, serif",
})
for f in features.get("nb_centroid", []):
    lon, lat = f["geo"]["coordinates"]
    style    = NEIGHBOURHOOD_STYLE.get(f["label"], {"label_color": "#333"})
    cx, cy   = tx(lon), ty(lat)

    words = f["label"].split()
    # Single line for short names, two lines for three-word names
    if len(words) <= 2:
        lines = [f["label"]]
    else:
        mid    = (len(words) + 1) // 2
        lines  = [" ".join(words[:mid]), " ".join(words[mid:])]

    text_el = ET.SubElement(lbl_group, "text", {
        "x":            f"{cx:.1f}",
        "y":            f"{cy:.1f}",
        "text-anchor":  "middle",
        "font-size":    "9.5",
        "font-weight":  "700",
        "fill":         style["label_color"],
        "filter":       "url(#lbl-shadow)",
        "letter-spacing": "0.5",
    })
    total_lines = len(lines)
    for i, line in enumerate(lines):
        dy_val = (i - (total_lines - 1) / 2) * 13   # vertically centre multi-line
        ET.SubElement(text_el, "tspan", {
            "x":  f"{cx:.1f}",
            "dy": f"{dy_val:.1f}" if i == 0 else "13",
        }).text = line.upper()

# ── Park labels ────────────────────────────────────────────────────────────
for f in features.get("park", []):
    ring = f["geo"]["coordinates"][0]
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    cx   = tx(sum(lons) / len(lons))
    cy   = ty(sum(lats) / len(lats))
    ET.SubElement(lbl_group, "text", {
        "x": f"{cx:.1f}", "y": f"{cy:.1f}",
        "text-anchor": "middle",
        "font-size":   "6",
        "fill":        "#1e6b1e",
        "font-style":  "italic",
    }).text = f["label"]

# ── "Portsmith Harbour" sea label ─────────────────────────────────────────
ET.SubElement(lbl_group, "text", {
    "x":            str(W // 2),
    "y":            str(int(ty(50.679))),
    "text-anchor":  "middle",
    "font-size":    "13",
    "font-style":   "italic",
    "fill":         "#1a4a7a",
    "opacity":      "0.82",
    "letter-spacing": "2",
}).text = "Portsmith Harbour"

# ── Title ─────────────────────────────────────────────────────────────────
ET.SubElement(svg, "text", {
    "x": str(W // 2), "y": "28",
    "text-anchor":  "middle",
    "font-family":  "Georgia, serif",
    "font-size":    "16",
    "font-weight":  "bold",
    "fill":         "#222233",
    "letter-spacing": "1",
}).text = "PORTSMITH"

ET.SubElement(svg, "text", {
    "x": str(W // 2), "y": "42",
    "text-anchor":  "middle",
    "font-family":  "Georgia, serif",
    "font-size":    "8.5",
    "fill":         "#555566",
    "letter-spacing": "2",
}).text = "neighbourhood map  ·  PostGIS chapter 2"

# ── Border ────────────────────────────────────────────────────────────────
ET.SubElement(svg, "rect", {
    "x": "1", "y": "1",
    "width": str(W - 2), "height": str(H - 2),
    "fill": "none", "stroke": "#445566", "stroke-width": "2", "rx": "4",
})

# ── Legend ────────────────────────────────────────────────────────────────
leg_x, leg_y = W - PAD - 144, PAD + 8
leg_h = len(NEIGHBOURHOOD_STYLE) * 16 + 52
ET.SubElement(svg, "rect", {
    "x": str(leg_x - 8), "y": str(leg_y - 8),
    "width": "154", "height": str(leg_h),
    "fill": "white", "fill-opacity": "0.84",
    "stroke": "#aaa", "stroke-width": "0.8", "rx": "3",
})
ET.SubElement(svg, "text", {
    "x": str(leg_x + 69), "y": str(leg_y + 5),
    "text-anchor":  "middle",
    "font-family":  "Georgia, serif",
    "font-size":    "8", "font-weight": "bold", "fill": "#333",
}).text = "NEIGHBOURHOODS"

for i, (name, style) in enumerate(NEIGHBOURHOOD_STYLE.items()):
    ry = leg_y + 18 + i * 16
    ET.SubElement(svg, "rect", {
        "x": str(leg_x), "y": str(ry),
        "width": "12", "height": "10",
        "fill": style["fill"], "stroke": "#7a9ab0", "stroke-width": "0.8",
    })
    ET.SubElement(svg, "text", {
        "x": str(leg_x + 17), "y": str(ry + 8),
        "font-family": "Georgia, serif",
        "font-size": "8", "fill": "#333",
    }).text = name

dot_y = leg_y + 18 + len(NEIGHBOURHOOD_STYLE) * 16 + 8
ET.SubElement(svg, "circle", {
    "cx": str(leg_x + 6), "cy": str(dot_y + 4),
    "r": "4", "fill": "#c0392b", "fill-opacity": "0.85",
    "stroke": "white", "stroke-width": "0.8",
})
ET.SubElement(svg, "text", {
    "x": str(leg_x + 17), "y": str(dot_y + 8),
    "font-family": "Georgia, serif",
    "font-size": "8", "fill": "#333",
}).text = "Business (labelled = featured)"

# ---------------------------------------------------------------------------
# Serialise
# ---------------------------------------------------------------------------

ET.indent(svg, space="  ")
svg_str = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(svg, encoding="unicode")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(svg_str)
print(f"Written {len(svg_str):,} chars → {OUT}", file=sys.stderr)
