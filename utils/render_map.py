#!/usr/bin/env python3.12
"""
Render Portsmith map as SVG from PostGIS geometry data.

Usage:
    python utils/render_map.py portsmith_map.svg
"""

import json
import math
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
    "Old Town Hardware":         ("Old Town Hardware",   "end",     -7, -5),
    "The Clocktower Pub":        ("Clocktower Pub",      "start",    7,  3),
    # Northgate
    "Northgate Grocers":         ("Northgate Grocers",   "end",     -7,  3),
    "The Grand Hotel Portsmith": ("Grand Hotel",         "start",    7,  3),
    # Riverside
    "Riverside Cinema":          ("Riverside Cinema",    "end",     -7, -3),
    "Dr. Chen Dentistry":        ("Dr. Chen Dentistry",  "end",     -7,  3),
    # University Quarter
    "The Hungry Scholar":        ("Hungry Scholar",      "start",    7,  3),
    "Quarter Note Jazz Club":    ("Quarter Note Jazz",   "start",    7, 10),
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

# ── Paper-grain filter — turbulence noise clipped to whatever shape it's
# applied to (via feComposite ... in2="SourceAlpha"), used to give the land
# mass a faint mottled, hand-inked texture instead of a flat fill. Opacity is
# controlled on the *element* the filter is applied to (a plain SVG
# attribute) rather than inside the filter chain — feComponentTransfer's
# feFuncA table didn't come out anywhere near this faint under weasyprint's
# cairo-based SVG filter support, so the safer, more portable place to dial
# in transparency is the ordinary `opacity` attribute every renderer honours.
grain = ET.SubElement(defs, "filter", {
    "id": "paper-grain",
    "x": "-5%", "y": "-5%", "width": "110%", "height": "110%",
})
ET.SubElement(grain, "feTurbulence", {
    "type": "fractalNoise", "baseFrequency": "0.9", "numOctaves": "2",
    "seed": "42", "result": "noise",
})
ET.SubElement(grain, "feColorMatrix", {
    "in": "noise", "type": "saturate", "values": "0", "result": "gray",
})
ET.SubElement(grain, "feComposite", {"in": "gray", "in2": "SourceAlpha", "operator": "in"})

# ── Hull gradient for the little illustrated boats ─────────────────────────
hull_grad = ET.SubElement(defs, "linearGradient", {
    "id": "hull-grad", "x1": "0", "y1": "0", "x2": "0", "y2": "1",
})
ET.SubElement(hull_grad, "stop", {"offset": "0%",   "stop-color": "#c8844a"})
ET.SubElement(hull_grad, "stop", {"offset": "100%", "stop-color": "#8b5830"})

# ── Painterly water wash covering the whole canvas ─────────────────────────
water_grad = ET.SubElement(defs, "linearGradient", {
    "id": "water-grad", "x1": "0", "y1": "0", "x2": "0", "y2": str(H),
    "gradientUnits": "userSpaceOnUse",
})
ET.SubElement(water_grad, "stop", {"offset": "0%",   "stop-color": "#bcdff3"})
ET.SubElement(water_grad, "stop", {"offset": "55%",  "stop-color": "#8fc6e6"})
ET.SubElement(water_grad, "stop", {"offset": "100%", "stop-color": "#5a9dc7"})
ET.SubElement(svg, "rect", {
    "x": "0", "y": "0", "width": str(W), "height": str(H),
    "fill": "url(#water-grad)",
})


def wave_points(x0: float, x1: float, y_base: float,
                 amplitude: float, wavelength: float, phase: float,
                 step: float = 6.0) -> list[tuple[float, float]]:
    """Points along a sine wave — the hand-drawn stand-in for a coastline
    or a ripple, depending on the amplitude/wavelength it's called with."""
    pts, x = [], x0
    while x <= x1:
        y = y_base + amplitude * math.sin(2 * math.pi * (x - x0) / wavelength + phase)
        pts.append((x, y))
        x += step
    pts.append((x1, y_base + amplitude * math.sin(2 * math.pi * (x1 - x0) / wavelength + phase)))
    return pts


def points_str(pts: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)


# ── Land mass, with a hand-drawn wavy coastline along its southern
# (harbour-facing) edge instead of a ruler-straight rectangle. The other
# three edges are inland and stay straight. ─────────────────────────────────
COAST_Y = ty(LAT_MIN)   # baseline the coastline wave oscillates around
coast_pts = wave_points(PAD, W - PAD, COAST_Y, amplitude=7, wavelength=165, phase=0.6)
land_pts = [(PAD, PAD), (W - PAD, PAD)] + coast_pts[::-1]
land_poly_pts = points_str(land_pts)

ET.SubElement(svg, "polygon", {"points": land_poly_pts, "fill": "#e8e4dc"})
ET.SubElement(svg, "polygon", {
    "points": land_poly_pts, "fill": "#3a2a10",
    "filter": "url(#paper-grain)", "opacity": "0.06",
})

# A slightly darker line just inside the coastline, suggesting a tideline.
tide_pts = wave_points(PAD, W - PAD, COAST_Y - 4, amplitude=7, wavelength=165, phase=0.6)
ET.SubElement(svg, "polyline", {
    "points": points_str(tide_pts), "fill": "none",
    "stroke": "#c9bfa0", "stroke-width": "1.2", "opacity": "0.7",
})

# ── Ripples and small boats in the harbour band below the coastline ────────
ripple_group = ET.SubElement(svg, "g", {"id": "ripples", "opacity": "0.5"})
for i, (y_off, amp, wl) in enumerate([(14, 2.5, 90), (24, 2.2, 100), (34, 2.8, 80)]):
    pts = wave_points(PAD - 20, W - PAD + 20, COAST_Y + y_off, amp, wl, phase=i * 0.9)
    ET.SubElement(ripple_group, "polyline", {
        "points": points_str(pts), "fill": "none",
        "stroke": "white", "stroke-width": "1",
    })


def add_boat(cx: float, cy: float, scale: float = 1.0) -> None:
    g = ET.SubElement(svg, "g", {"transform": f"translate({cx},{cy}) scale({scale})"})
    ET.SubElement(g, "path", {   # hull
        "d": "M -10,0 Q 0,6 10,0 L 7,-3 L -7,-3 Z",
        "fill": "url(#hull-grad)", "stroke": "#5c3a1c", "stroke-width": "0.6",
    })
    ET.SubElement(g, "line", {   # mast
        "x1": "0", "y1": "-3", "x2": "0", "y2": "-16",
        "stroke": "#5c3a1c", "stroke-width": "0.8",
    })
    ET.SubElement(g, "path", {   # sail
        "d": "M 0,-15 L 0,-4 L 8,-5 Z",
        "fill": "#f5f0e6", "opacity": "0.92", "stroke": "#cfc7b0", "stroke-width": "0.4",
    })


for bx, by, scale in [(190, COAST_Y + 18, 0.9), (560, COAST_Y + 24, 1.1), (790, COAST_Y + 16, 0.8)]:
    add_boat(bx, by, scale)


def add_compass_rose(cx: float, cy: float, r: float = 15) -> None:
    g = ET.SubElement(svg, "g", {"id": "compass-rose"})
    pts = []
    for i in range(16):
        ang = math.pi / 8 * i - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.4
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    ET.SubElement(g, "polygon", {
        "points": points_str(pts), "fill": "#f5f0e6",
        "stroke": "#445566", "stroke-width": "0.8", "opacity": "0.9",
    })
    ET.SubElement(g, "circle", {"cx": str(cx), "cy": str(cy), "r": "2", "fill": "#445566"})
    ET.SubElement(g, "text", {
        "x": str(cx), "y": str(cy - r - 4), "text-anchor": "middle",
        "font-size": "9.5", "font-weight": "bold", "fill": "#445566",
        "font-family": "Georgia, serif",
    }).text = "N"


add_compass_rose(28, 430)   # centred in the quiet western water margin

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
    "font-family": '"Comic Neue", Arial, Helvetica, sans-serif',
    "font-size":   "9.5",
})
for f in features.get("business", []):
    if f["label"] not in FEATURED:
        continue
    lon, lat   = f["geo"]["coordinates"]
    disp, anchor, dx, dy = FEATURED[f["label"]]
    cx, cy = tx(lon), ty(lat)

    # White halo via the same flood-and-composite filter the neighbourhood
    # labels use. (A paint-order stroke halo was tried here first, but at
    # this font-size a stroke thick enough to read as a halo is thick enough
    # to bridge adjacent letters into a solid white blob instead.)
    ET.SubElement(biz_label_group, "text", {
        "x":            f"{cx + dx:.1f}",
        "y":            f"{cy + dy:.1f}",
        "text-anchor":  anchor,
        "fill":         "#1a1a2e",
        "font-weight":  "600",
        "filter":       "url(#lbl-shadow)",
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
        "font-size":    "11.5",
        "font-weight":  "700",
        "fill":         style["label_color"],
        "filter":       "url(#lbl-shadow)",
        "letter-spacing": "0.5",
    })
    total_lines = len(lines)
    for i, line in enumerate(lines):
        dy_val = (i - (total_lines - 1) / 2) * 15   # vertically centre multi-line
        ET.SubElement(text_el, "tspan", {
            "x":  f"{cx:.1f}",
            "dy": f"{dy_val:.1f}" if i == 0 else "15",
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
        "font-size":   "7.5",
        "fill":        "#1e6b1e",
        "font-style":  "italic",
    }).text = f["label"]

# ── "Portsmith Harbour" sea label — hand-lettered, not typeset ────────────
ET.SubElement(lbl_group, "text", {
    "x":            str(W // 2),
    "y":            str(int(ty(50.679))),
    "text-anchor":  "middle",
    "font-family":  '"Comic Neue", "Trebuchet MS", serif',
    "font-size":    "19",
    "font-weight":  "bold",
    "fill":         "#1a4a7a",
    "opacity":      "0.85",
    "letter-spacing": "1",
}).text = "Portsmith Harbour"

# ── Title ─────────────────────────────────────────────────────────────────
ET.SubElement(svg, "text", {
    "x": str(W // 2), "y": "30",
    "text-anchor":  "middle",
    "font-family":  "Georgia, serif",
    "font-size":    "19",
    "font-weight":  "bold",
    "fill":         "#222233",
    "letter-spacing": "1",
}).text = "PORTSMITH"

ET.SubElement(svg, "text", {
    "x": str(W // 2), "y": "46",
    "text-anchor":  "middle",
    "font-family":  '"Comic Neue", "Trebuchet MS", serif',
    "font-size":    "13",
    "font-weight":  "bold",
    "fill":         "#555566",
}).text = "neighbourhood map  ·  PostGIS chapter 2"

# ── Border — a double-line cartouche frame instead of a single rect ────────
ET.SubElement(svg, "rect", {
    "x": "3", "y": "3", "width": str(W - 6), "height": str(H - 6),
    "fill": "none", "stroke": "#445566", "stroke-width": "2.4", "rx": "5",
})
ET.SubElement(svg, "rect", {
    "x": "8", "y": "8", "width": str(W - 16), "height": str(H - 16),
    "fill": "none", "stroke": "#8a7a4a", "stroke-width": "0.9", "rx": "3",
})

# ── Legend ────────────────────────────────────────────────────────────────
leg_x, leg_y = W - PAD - 160, PAD + 8
leg_h = len(NEIGHBOURHOOD_STYLE) * 18 + 58
ET.SubElement(svg, "rect", {
    "x": str(leg_x - 8), "y": str(leg_y - 8),
    "width": "170", "height": str(leg_h),
    "fill": "white", "fill-opacity": "0.84",
    "stroke": "#aaa", "stroke-width": "0.8", "rx": "3",
})
ET.SubElement(svg, "text", {
    "x": str(leg_x + 77), "y": str(leg_y + 6),
    "text-anchor":  "middle",
    "font-family":  "Georgia, serif",
    "font-size":    "9.5", "font-weight": "bold", "fill": "#333",
}).text = "NEIGHBOURHOODS"

for i, (name, style) in enumerate(NEIGHBOURHOOD_STYLE.items()):
    ry = leg_y + 20 + i * 18
    ET.SubElement(svg, "rect", {
        "x": str(leg_x), "y": str(ry),
        "width": "13", "height": "11",
        "fill": style["fill"], "stroke": "#7a9ab0", "stroke-width": "0.8",
    })
    ET.SubElement(svg, "text", {
        "x": str(leg_x + 19), "y": str(ry + 9),
        "font-family": "Georgia, serif",
        "font-size": "9.5", "fill": "#333",
    }).text = name

dot_y = leg_y + 20 + len(NEIGHBOURHOOD_STYLE) * 18 + 8
ET.SubElement(svg, "circle", {
    "cx": str(leg_x + 6), "cy": str(dot_y + 4),
    "r": "4", "fill": "#c0392b", "fill-opacity": "0.85",
    "stroke": "white", "stroke-width": "0.8",
})
ET.SubElement(svg, "text", {
    "x": str(leg_x + 19), "y": str(dot_y + 8),
    "font-family": "Georgia, serif",
    "font-size": "9.5", "fill": "#333",
}).text = "Business (labelled = featured)"

# ---------------------------------------------------------------------------
# Serialise
# ---------------------------------------------------------------------------

ET.indent(svg, space="  ")
svg_str = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(svg, encoding="unicode")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(svg_str)
print(f"Written {len(svg_str):,} chars → {OUT}", file=sys.stderr)
