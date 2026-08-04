#!/usr/bin/env python3.12
"""
Render Chapter 12's road graph (Exercise 5) as SVG, from live PostGIS data.

Draws all 19 `road_segments` edges using their *real* along-road geometry
(via ST_LineSubstring against Chapter 2's actual city_infrastructure
LINESTRINGs, the same source data/ch12_seed.py derived the edges from —
not straight lines between intersection dots, which would misrepresent
Ring Road's bend), then highlights the two candidate routes Exercise 5
finds between "Fisherman's Row & Market Street" and "Bay Street & Ring
Road (East)": the fewest-hops route (4 hops, follows Ring Road's long
bend) and the shortest-distance route (5 hops, cuts through Bay Street).

Usage:
    python utils/render_ch12_road_graph.py imgs/ch12_road_graph.svg
"""

import json
import sys
import xml.etree.ElementTree as ET

import psycopg

DSN = "dbname=portsmith"
OUT = sys.argv[1] if len(sys.argv) > 1 else "imgs/ch12_road_graph.svg"

# ---------------------------------------------------------------------------
# The two routes Exercise 5 finds, as road_segments.id sets. Both share
# their first three hops (Market Street, Lighthouse Avenue, then onto Ring
# Road) and diverge only in how they cross from "Bay Street & Ring Road
# (West)" to "Bay Street & Ring Road (East)".
# ---------------------------------------------------------------------------

SHARED_EDGE_IDS = {8, 7, 12}       # Market St -> Lighthouse Ave -> onto Ring Road
FEWEST_HOPS_ONLY = {13}            # Ring Road direct (4 hops total, 15,379.5 m)
SHORTEST_DIST_ONLY = {2, 3}        # via Bay Street & Canal Road (5 hops, 10,485.2 m)

START_NAME = "Fisherman's Row & Market Street"
END_NAME = "Bay Street & Ring Road (East)"

# ---------------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------------

with psycopg.connect(DSN) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, ST_X(geom), ST_Y(geom) FROM intersections")
        intersections = {row[0]: {"name": row[1], "lon": row[2], "lat": row[3]} for row in cur.fetchall()}

        cur.execute("""
            SELECT rs.id, rs.road_name, rs.length_m,
                   CASE WHEN f.frac1 <= f.frac2
                        THEN ST_AsGeoJSON(ST_LineSubstring(ci.geom, f.frac1, f.frac2))
                        ELSE ST_AsGeoJSON(ST_LineMerge(ST_Union(
                                 ST_LineSubstring(ci.geom, f.frac1, 1.0),
                                 ST_LineSubstring(ci.geom, 0.0, f.frac2)
                             )))
                   END AS path_geojson
            FROM   road_segments rs
            JOIN   intersections i1 ON i1.id = rs.from_intersection
            JOIN   intersections i2 ON i2.id = rs.to_intersection
            JOIN   city_infrastructure ci ON ci.name = rs.road_name
            CROSS JOIN LATERAL (
                SELECT ST_LineLocatePoint(ci.geom, i1.geom) AS frac1,
                       ST_LineLocatePoint(ci.geom, i2.geom) AS frac2
            ) f
            ORDER BY rs.id
        """)
        edges = []
        for edge_id, road_name, length_m, gj in cur.fetchall():
            coords = json.loads(gj)["coordinates"]
            edges.append({"id": edge_id, "road_name": road_name, "length_m": float(length_m), "coords": coords})

start_id = next(i for i, v in intersections.items() if v["name"] == START_NAME)
end_id = next(i for i, v in intersections.items() if v["name"] == END_NAME)

# ---------------------------------------------------------------------------
# Canvas and coordinate transform — bounds computed from the *actual*
# geometry being drawn (edges bulge well beyond the intersection points
# themselves, e.g. Ring Road's northward bend), not guessed.
# ---------------------------------------------------------------------------

W, H = 980, 760
PAD = 190

all_lons = [lon for e in edges for lon, lat in e["coords"]]
all_lats = [lat for e in edges for lon, lat in e["coords"]]
lon_span = max(all_lons) - min(all_lons)
lat_span = max(all_lats) - min(all_lats)
MARGIN = 0.06  # fraction of span, extra breathing room for labels

LON_MIN, LON_MAX = min(all_lons) - MARGIN * lon_span, max(all_lons) + MARGIN * lon_span
LAT_MIN, LAT_MAX = min(all_lats) - MARGIN * lat_span, max(all_lats) + MARGIN * lat_span

DRAW_W = W - 2 * PAD
DRAW_H = H - 2 * PAD


def tx(lon: float) -> float:
    return PAD + (lon - LON_MIN) / (LON_MAX - LON_MIN) * DRAW_W


def ty(lat: float) -> float:
    return H - PAD - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * DRAW_H


def coords_to_polyline(coords: list) -> str:
    return " ".join(f"{tx(lon):.2f},{ty(lat):.2f}" for lon, lat in coords)


# ---------------------------------------------------------------------------
# Build SVG
# ---------------------------------------------------------------------------

svg = ET.Element("svg", {
    "xmlns": "http://www.w3.org/2000/svg",
    "width": str(W), "height": str(H), "viewBox": f"0 0 {W} {H}",
})

ET.SubElement(svg, "rect", {"x": "0", "y": "0", "width": str(W), "height": str(H), "fill": "#faf7f0"})

COLOR_BASE = "#b8b0a0"
COLOR_SHARED = "#3a3a3a"
COLOR_HOPS = "#c0392b"     # fewest-hops-only route
COLOR_DIST = "#1a7a8a"     # shortest-distance-only route

# ── Base network, drawn first so highlights sit on top ─────────────────────
road_group = ET.SubElement(svg, "g", {"id": "roads"})
for e in edges:
    if e["id"] in SHARED_EDGE_IDS or e["id"] in FEWEST_HOPS_ONLY or e["id"] in SHORTEST_DIST_ONLY:
        continue
    ET.SubElement(road_group, "polyline", {
        "points": coords_to_polyline(e["coords"]),
        "fill": "none", "stroke": COLOR_BASE, "stroke-width": "2",
        "stroke-linecap": "round", "stroke-linejoin": "round",
    })

# ── Shared prefix of both routes ────────────────────────────────────────────
for e in edges:
    if e["id"] in SHARED_EDGE_IDS:
        ET.SubElement(road_group, "polyline", {
            "points": coords_to_polyline(e["coords"]),
            "fill": "none", "stroke": COLOR_SHARED, "stroke-width": "5",
            "stroke-linecap": "round", "stroke-linejoin": "round",
        })

# ── The two diverging routes ────────────────────────────────────────────────
for e in edges:
    if e["id"] in FEWEST_HOPS_ONLY:
        ET.SubElement(road_group, "polyline", {
            "points": coords_to_polyline(e["coords"]),
            "fill": "none", "stroke": COLOR_HOPS, "stroke-width": "5",
            "stroke-linecap": "round", "stroke-linejoin": "round",
        })
    if e["id"] in SHORTEST_DIST_ONLY:
        ET.SubElement(road_group, "polyline", {
            "points": coords_to_polyline(e["coords"]),
            "fill": "none", "stroke": COLOR_DIST, "stroke-width": "5",
            "stroke-linecap": "round", "stroke-linejoin": "round",
        })

# ── Intersections ────────────────────────────────────────────────────────
ON_ROUTE_IDS = {9, 12, 11, 3, 4, 5}
label_group = ET.SubElement(svg, "g", {"font-family": "Georgia, serif", "font-size": "11"})
dot_group = ET.SubElement(svg, "g", {"id": "intersections"})

# (dx, dy, anchor) per on-route intersection id — hand-tuned so labels clear
# both the route markers (START/END) and each other.
LABEL_OFFSETS = {
    9:  (-10, 20, "end"),
    12: (34, -16, "start"),
    11: (-12, -8, "end"),
    3:  (-12, -12, "end"),
    4:  (0, 24, "middle"),
    5:  (-12, -12, "end"),
}

for iid, info in intersections.items():
    cx, cy = tx(info["lon"]), ty(info["lat"])
    on_route = iid in ON_ROUTE_IDS
    ET.SubElement(dot_group, "circle", {
        "cx": f"{cx:.2f}", "cy": f"{cy:.2f}",
        "r": "6" if on_route else "3.2",
        "fill": "#222" if on_route else "#999",
        "stroke": "white", "stroke-width": "1.2" if on_route else "0.6",
    })
    if iid in LABEL_OFFSETS:
        dx, dy, anchor = LABEL_OFFSETS[iid]
        ET.SubElement(label_group, "text", {
            "x": f"{cx + dx:.1f}", "y": f"{cy + dy:.1f}",
            "text-anchor": anchor, "fill": "#1a1a1a", "font-weight": "600",
        }).text = info["name"]

# ── Start / end markers ────────────────────────────────────────────────────
start_info, end_info = intersections[start_id], intersections[end_id]
ET.SubElement(svg, "text", {
    "x": f"{tx(start_info['lon']):.1f}", "y": f"{ty(start_info['lat']) - 24:.1f}",
    "text-anchor": "middle", "font-family": "Georgia, serif", "font-size": "12",
    "font-weight": "bold", "fill": "#1e6b1e",
}).text = "START"
ET.SubElement(svg, "text", {
    "x": f"{tx(end_info['lon']):.1f}", "y": f"{ty(end_info['lat']) - 16:.1f}",
    "text-anchor": "middle", "font-family": "Georgia, serif", "font-size": "12",
    "font-weight": "bold", "fill": "#7a1e1e",
}).text = "END"

# ── Title ────────────────────────────────────────────────────────────────
ET.SubElement(svg, "text", {
    "x": str(W // 2), "y": "30", "text-anchor": "middle",
    "font-family": "Georgia, serif", "font-size": "19", "font-weight": "bold", "fill": "#222",
}).text = "Fewest Hops vs. Shortest Distance"
ET.SubElement(svg, "text", {
    "x": str(W // 2), "y": "50", "text-anchor": "middle",
    "font-family": '"Comic Neue", "Trebuchet MS", serif', "font-size": "12.5", "fill": "#555",
}).text = "Portsmith road graph · Chapter 12, Exercise 5"

# ── Legend ────────────────────────────────────────────────────────────────
leg_x, leg_y = PAD - 55, H - PAD + 30
legend_items = [
    (COLOR_BASE, 2, "Other roads (not on either route)"),
    (COLOR_SHARED, 5, "Shared first 3 hops (both routes)"),
    (COLOR_HOPS, 5, "Fewest hops: 4 hops, 15,379.5 m (via Ring Road)"),
    (COLOR_DIST, 5, "Shortest distance: 5 hops, 10,485.2 m (via Bay Street)"),
]
for i, (color, width, text) in enumerate(legend_items):
    ly = leg_y + i * 18
    ET.SubElement(svg, "line", {
        "x1": str(leg_x), "y1": str(ly), "x2": str(leg_x + 28), "y2": str(ly),
        "stroke": color, "stroke-width": str(width), "stroke-linecap": "round",
    })
    ET.SubElement(svg, "text", {
        "x": str(leg_x + 36), "y": str(ly + 4),
        "font-family": "Georgia, serif", "font-size": "11", "fill": "#333",
    }).text = text

# ── Border ──────────────────────────────────────────────────────────────
ET.SubElement(svg, "rect", {
    "x": "3", "y": "3", "width": str(W - 6), "height": str(H - 6),
    "fill": "none", "stroke": "#445566", "stroke-width": "2", "rx": "5",
})

# ---------------------------------------------------------------------------
# Serialise
# ---------------------------------------------------------------------------

ET.indent(svg, space="  ")
svg_str = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(svg, encoding="unicode")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write(svg_str)
print(f"Written {len(svg_str):,} chars -> {OUT}", file=sys.stderr)
