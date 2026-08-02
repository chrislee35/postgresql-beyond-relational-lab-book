#!/usr/bin/env python3.12
"""
Work around a WeasyPrint SVG-rendering bug where any <text text-anchor="middle">
(or "end") clips descenders — the tails on g, j, p, q, y, and commas — at the
baseline. Confirmed by direct experiment against WeasyPrint's actual SVG
renderer (the path psql-book.pdf goes through): text-anchor="start" always
renders full glyphs; the exact same text with text-anchor="middle" clips,
regardless of font, tspan nesting, or nested <g> transforms. mermaidx's own
resvg-based rasterizer has no such bug — this is WeasyPrint-specific.

The fix: for every centred/right-aligned <text> (mermaid uses "middle" for
essentially every label), measure the text's *actually rendered* width and
convert it to an equivalent text-anchor="start" element with x shifted by
-width/2 (or -width for "end").

That width is measured by rendering the *actual diagram itself*, once per
label, with every other label's text blanked out (so there's exactly one
unambiguous word run to extract via `pdftotext -bbox`). Two cheaper
alternatives were tried and both failed the same way: predicting width
from Comic Neue's own font file (exactly the technique mermaidx uses
internally) matches a small isolated probe render to the pixel, and a
*small isolated probe* using the real diagram's font-size/family also
matches that same prediction — but neither matches what the label actually
renders at once it's embedded in one of this book's real, multi-hundred-
element diagrams: real measurements come out consistently smaller, by a
factor that varies per diagram and didn't resolve after checking font
embedding (`pdffonts` confirms the same Comic Neue subset either way),
every transform in the ancestor chain, CSS selector mechanism,
viewBox/width="100%" handling, or bisecting the stylesheet rule by rule.
Something about WeasyPrint's layout genuinely renders smaller at that
scale than any external prediction or small-document probe agrees on.
Rendering the real document, in place, is the only measurement that held
up under testing — it doesn't need to explain the discrepancy, only ask
WeasyPrint what it will actually do.

While here, this also flattens mermaid's <tspan> label structure into plain
<text> elements (one per line), since that's a necessary precondition —
WeasyPrint clips descenders on tspan-nested text too, independent of anchor.

Usage:
    python utils/fix_svg_descenders.py path/to/diagram.svg [more.svg ...]

Requires `weasyprint` and `pdftotext` (poppler-utils) on PATH. Run this on
mermaidx's SVG output, before it's embedded in the book — the Makefile does
this automatically as part of generating imgs/*.svg from diagrams/*.mmd.
"""

import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


def resolve_length(value: str | None, font_size: float) -> float:
    """'-0.1em' -> -0.1 * font_size ; '12' -> 12.0 ; None -> 0.0"""
    if not value:
        return 0.0
    value = value.strip()
    if value.endswith("em"):
        return float(value[:-2]) * font_size
    return float(value)


def default_font_size(svg_text: str) -> float:
    """Pull the root font-size out of mermaid's own generated <style> block
    (e.g. '#gd1{font-family:...;font-size:20px;...}'), falling back to
    mermaid's own default of 16px if the pattern isn't found."""
    m = re.search(r"font-size\s*:\s*([\d.]+)px", svg_text)
    return float(m.group(1)) if m else 16.0


def flatten_text_element(text_el: ET.Element, font_size: float) -> list[ET.Element]:
    """Turn one <text> with tspan children into one or more tspan-free
    <text> elements, each holding one resolved line.

    Two different tspan conventions show up across mermaid's diagram types.
    Flowchart labels give every row its own absolute-ish 'y' (in em units),
    ignoring the parent <text>'s own 'y' entirely. Sequence diagrams instead
    give a single child tspan only a 'dy' (often "0"), meaning "continue
    from the parent's own y" — SVG's normal relative-positioning behavior.
    Blindly dropping the parent's 'y' (correct for the first convention)
    silently teleports sequence-diagram text to y=0 for the second. Handle
    both: a row with its own 'y' is absolute; a row with only 'dy' inherits
    the parent's 'y' as its base.
    """
    rows = list(text_el)
    if not rows:
        return [text_el]

    parent_y = resolve_length(text_el.get("y"), font_size)
    base_attrib = {k: v for k, v in text_el.attrib.items() if k != "y"}
    # mermaid centers virtually all label text, but node labels get that via
    # a CSS class rule (".node .label text{text-anchor:middle}") rather than
    # a literal attribute on the <text> element — so a missing attribute
    # here doesn't mean "left-aligned", it means "centered via CSS, and
    # the anchor-fixing pass below won't see it unless we make it explicit."
    base_attrib.setdefault("text-anchor", "middle")
    flat_texts = []
    for row in rows:
        if row.get("y") is not None:
            y = resolve_length(row.get("y"), font_size) + resolve_length(row.get("dy"), font_size)
        else:
            y = parent_y + resolve_length(row.get("dy"), font_size)
        content = "".join(row.itertext())
        new_el = ET.Element(f"{{{NS}}}text", dict(base_attrib))
        new_el.set("y", f"{y:.3f}")
        if row.get("x") is not None:
            new_el.set("x", row.get("x"))
        new_el.text = content
        flat_texts.append(new_el)
    return flat_texts


WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">'
)


def effective_anchor(el: ET.Element) -> str | None:
    """The text-anchor that will actually win: mermaid's sequence-diagram
    actor labels set text-anchor only inside a style="..." attribute (no
    plain text-anchor attribute at all), which the plain-attribute check
    alone would miss entirely. An inline style declaration also outranks
    the plain attribute in CSS specificity when both are present, so check
    style first."""
    style = el.get("style")
    if style:
        m = re.search(r"text-anchor\s*:\s*(\w+)", style)
        if m:
            return m.group(1)
    return el.get("text-anchor")


def measure_widths_in_context(root: ET.Element, targets: list[ET.Element]) -> list[float]:
    """Measure each target <text>'s actual rendered width by rendering the
    *entire diagram*, once per target, with every other target's text
    blanked (kept as empty <text> elements, not removed — same DOM shape,
    same CSS matches, just nothing to draw) so pdftotext -bbox has exactly
    one unambiguous word run to extract each time."""
    if not targets:
        return []

    vb = root.get("viewBox", "").split()
    vw, vh = float(vb[2]), float(vb[3])
    originals = [t.text for t in targets]
    widths = []

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        html_path, svg_path, pdf_path = td / "ctx.html", td / "ctx.svg", td / "ctx.pdf"
        html_path.write_text(
            f'<html><head><style>@page{{size:{vw}px {vh}px;margin:0}}'
            f'body{{margin:0}}img{{width:{vw}px}}</style></head>'
            f'<body><img src="ctx.svg"/></body></html>'
        )
        for i, target in enumerate(targets):
            for t, orig in zip(targets, originals):
                t.text = orig if t is target else ""
            svg_path.write_text(ET.tostring(root, encoding="unicode"))

            subprocess.run(["weasyprint", str(html_path), str(pdf_path)],
                            check=True, capture_output=True, text=True)
            result = subprocess.run(["pdftotext", "-bbox", str(pdf_path), "-"],
                                     check=True, capture_output=True, text=True)
            words = [(float(a), float(b)) for a, _, b, _ in WORD_RE.findall(result.stdout)]
            if not words:
                raise RuntimeError(
                    f"measure_widths_in_context: no rendered words found for "
                    f"target {i} ({orig!r}) — content missing or whitespace-only?"
                )
            xmin = min(w[0] for w in words)
            xmax = max(w[1] for w in words)
            widths.append((xmax - xmin) / 0.75)

    for t, orig in zip(targets, originals):
        t.text = orig
    return widths


def fix_file(path: str) -> None:
    svg_text = open(path, encoding="utf-8").read()
    font_size = default_font_size(svg_text)

    tree = ET.ElementTree(ET.fromstring(svg_text))
    root = tree.getroot()

    flattened = 0
    for parent in list(root.iter()):
        for text_el in [el for el in list(parent) if el.tag == f"{{{NS}}}text" and len(el)]:
            replacements = flatten_text_element(text_el, font_size)
            idx = list(parent).index(text_el)
            parent.remove(text_el)
            for j, new_el in enumerate(replacements):
                parent.insert(idx + j, new_el)
            flattened += 1

    to_fix = [el for el in root.iter(f"{{{NS}}}text")
              if effective_anchor(el) in ("middle", "end") and (el.text or "").strip()]
    widths = measure_widths_in_context(root, to_fix)
    for text_el, width in zip(to_fix, widths):
        anchor = effective_anchor(text_el)
        shift = width / 2 if anchor == "middle" else width
        x = float(text_el.get("x", "0"))
        text_el.set("x", f"{x - shift:.3f}")
        text_el.set("text-anchor", "start")
        # An inline style="text-anchor:middle;..." (mermaid's sequence-diagram
        # actor labels carry one alongside the plain attribute) has higher
        # CSS specificity and would silently override the attribute above,
        # leaving the element centered — and re-clipped — regardless of what
        # the attribute says. Scrub any anchor declaration from style too.
        style = text_el.get("style")
        if style:
            declarations = [d.strip() for d in style.split(";") if d.strip()
                             and not d.strip().lower().startswith("text-anchor")]
            text_el.set("style", ";".join(declarations) + (";" if declarations else ""))

    ET.indent(tree, space="  ")
    out = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"fix_svg_descenders: flattened {flattened} label(s), "
          f"re-anchored {len(to_fix)} in {path}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for p in sys.argv[1:]:
        fix_file(p)
