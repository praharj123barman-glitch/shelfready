"""Read a packaging artwork PDF into positioned text lines, panels and barcodes.

Packaging PDFs exported from design tools keep their text live, so we read it
exactly (no OCR guessing) together with its position on the dieline. On top of
that we recover three things a plain text dump loses:

* which panel each line sits on (front / back / left / right ...),
* whether a line is a dieline print mark rather than real copy,
* whether a line is hidden under an opaque shape drawn after it.
"""

from __future__ import annotations

import functools
import re
import statistics
from collections import Counter
from pathlib import Path

import pymupdf
import zxingcpp
from PIL import Image

from .models import Artwork, BBox, TextLine

GUIDE_PATTERNS = [
    r"\bpanel\b",
    r"\borientation\b",
    r"^copy free$",
    r"^principal display panel$",
    r"^gl\d+$",
    r"^\d,\d[A-Z0-9 ]+$",  # registration/plate codes in the slug area
]
STRUCTURAL_LAYER_WORDS = ["dimension", "cut", "crease", "glue", "bleed", "coating", "3d assist", "inkfree"]


def _bbox(r) -> BBox:
    return BBox(x0=float(r[0]), y0=float(r[1]), x1=float(r[2]), y1=float(r[3]))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _is_guide(text: str) -> bool:
    t = text.strip().lower()
    return any(re.search(p, t, re.I) for p in GUIDE_PATTERNS)


def _is_structural_layer(layer: str | None) -> bool:
    return bool(layer) and any(k in layer.lower() for k in STRUCTURAL_LAYER_WORDS)


def _is_guide_line(text: str, layer: str | None) -> bool:
    """Prefer the PDF layer (dieline tools put marks on structural layers);
    fall back to text patterns when the file has no layers."""
    if layer:
        return _is_structural_layer(layer)
    return _is_guide(text)


def _rebuild_spacing(chars: list[dict], size: float) -> str:
    """Rebuild words for letter-spaced text using real glyph gaps.

    "H I G H - G R A I N" style tracking makes PDF text come out as single
    letters separated by spaces, which breaks matching. Word gaps are wider
    than letter gaps, so we cut words where the gap is clearly larger.
    """
    glyphs = [c for c in chars if c["c"].strip()]
    if len(glyphs) < 3:
        return "".join(c["c"] for c in chars).strip()
    gaps = [glyphs[i + 1]["bbox"][0] - glyphs[i]["bbox"][2] for i in range(len(glyphs) - 1)]
    base = statistics.median(gaps)
    out = glyphs[0]["c"]
    for gap, g in zip(gaps, glyphs[1:]):
        if gap > base + 0.18 * size:
            out += " "
        out += g["c"]
    return out


def _looks_letter_spaced(text: str) -> bool:
    tokens = text.split()
    if len(tokens) < 2:
        return False
    singles = sum(1 for t in tokens if len(t) == 1)
    return singles / len(tokens) >= 0.5


def dieline_segments(page: pymupdf.Page, layer_word: str) -> list[tuple[float, float, float, float]]:
    """Straight line segments drawn on dieline layers whose name contains `layer_word` ('crease', 'cut', ...)."""
    segs = []
    for d in page.get_drawings():
        if layer_word not in (d.get("layer") or "").lower():
            continue
        for it in d["items"]:
            if it[0] == "l":
                segs.append((it[1].x, it[1].y, it[2].x, it[2].y))
            elif it[0] == "re":
                r = it[1]
                segs += [(r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1), (r.x0, r.y1, r.x1, r.y1), (r.x0, r.y0, r.x0, r.y1)]
    return segs


def _panels_from_creases(page: pymupdf.Page, guide_lines: list[tuple[str, BBox]]) -> dict[str, BBox] | None:
    """Faces are the cells between fold lines: the long horizontal creases bound
    the body, the vertical creases split it into faces, and what lies above or
    below each face is that face's top or bottom flap."""
    creases = dieline_segments(page, "crease")
    cuts = dieline_segments(page, "cut")
    if not creases:
        return None
    W, H = page.rect.width, page.rect.height
    # a body fold may be drawn as one long line or as one segment per face,
    # so sum the horizontal crease length at each height
    length_at: dict[int, float] = {}
    for x0, y0, x1, y1 in creases:
        if abs(y0 - y1) < 1:
            length_at[round(y0)] = length_at.get(round(y0), 0) + abs(x1 - x0)
    horiz = sorted(y for y, total in length_at.items() if total > W * 0.5)
    if len(horiz) < 2:
        return None
    top, bottom = horiz[0], horiz[-1]
    xs = sorted({round(x0) for x0, y0, x1, y1 in creases + cuts if abs(x0 - x1) < 1 and min(y0, y1) <= top + 1 and max(y0, y1) >= bottom - 1})
    cols = [(a, b) for a, b in zip(xs, xs[1:]) if b - a > 60]
    panels: dict[str, BBox] = {}
    for x0, x1 in cols:
        name = next(
            (m.group(1).lower() for text, bb in guide_lines
             if (m := re.match(r"(front|back|left|right) panel", text.strip(), re.I)) and x0 <= bb.cx <= x1 and top <= bb.cy <= bottom),
            None,
        )
        if not name or name in panels:
            continue
        panels[name] = BBox(x0=x0, y0=top, x1=x1, y1=bottom)
        panels[f"{name} top flap"] = BBox(x0=x0, y0=0, x1=x1, y1=top)
        panels[f"{name} bottom flap"] = BBox(x0=x0, y0=bottom, x1=x1, y1=H)
    if not panels:
        return None
    first = min(p.x0 for p in panels.values())
    if first > 5:
        panels["glue flap"] = BBox(x0=0, y0=top, x1=first, y1=bottom)
    return panels


def _detect_panels(page: pymupdf.Page, guide_lines: list[tuple[str, BBox]]) -> dict[str, BBox]:
    """Use the dieline fold lines when the file has them; otherwise fall back
    to the large filled panel shapes."""
    return _panels_from_creases(page, guide_lines) or _panels_from_fills(page, guide_lines)


def _panels_from_fills(page: pymupdf.Page, guide_lines: list[tuple[str, BBox]]) -> dict[str, BBox]:
    """Find panels from the large filled shapes of the dieline.

    Panel faces are drawn as big filled rectangles; their edges give the
    column and row grid. Each column is named from the guide label inside it
    ("Front panel", "Back panel", ...).
    """
    fills = [
        d["rect"]
        for d in page.get_drawings()
        if d.get("fill") is not None and d["rect"].width > 150 and d["rect"].height > 150
    ]
    tall = [r for r in fills if r.height > page.rect.height * 0.45]
    if not tall:
        return {"page": _bbox(page.rect)}
    top = min(r.y0 for r in tall)
    bottom = statistics.median(r.y1 for r in tall)
    xs = sorted({round(v) for r in fills for v in (r.x0, r.x1)})
    cols = [(a, b) for a, b in zip(xs, xs[1:]) if b - a > 120]

    panels: dict[str, BBox] = {}
    for x0, x1 in cols:
        name = None
        for text, bb in guide_lines:
            m = re.match(r"(front|back|left|right) panel", text.strip(), re.I)
            if m and x0 <= bb.cx <= x1 and top <= bb.cy <= bottom:
                name = m.group(1).lower()
                break
        if name and name not in panels:
            panels[name] = BBox(x0=x0, y0=top, x1=x1, y1=bottom)
    panels["top"] = BBox(x0=0, y0=0, x1=page.rect.width, y1=top)
    panels["bottom"] = BBox(x0=0, y0=bottom, x1=page.rect.width, y1=page.rect.height)
    return panels


def _content_panels(page: pymupdf.Page, panels: dict[str, BBox], lines: list[TextLine]) -> list[str]:
    """Faces always count; a flap counts when design-layer text or graphics sit inside it."""
    design = [
        _bbox(d["rect"]) for d in page.get_drawings()
        if not _is_structural_layer(d.get("layer")) and d["rect"].width < page.rect.width * 0.5
    ] + [
        _bbox(img["bbox"]) for img in page.get_image_info()
    ]
    out = []
    for name, p in panels.items():
        has_text = any(ln.panel == name and ln.role == "copy" for ln in lines)
        has_art = any(p.x0 <= b.cx <= p.x1 and p.y0 <= b.cy <= p.y1 for b in design)
        if " " not in name or has_text or has_art:
            out.append(name)
    return out


def _panel_for(bb: BBox, panels: dict[str, BBox]) -> str:
    """Panel containing the box centre; faces win over flaps on shared edges."""
    for name, p in sorted(panels.items(), key=lambda kv: " " in kv[0]):
        if p.x0 <= bb.cx <= p.x1 and p.y0 <= bb.cy <= p.y1:
            return name
    return "other"


def _merge_curved(raw: list[dict]) -> list[dict]:
    """Join single-letter lines of text set on a curve into one line.

    Curved headlines ("PACKED WITH GOODNESS") are exported one glyph per line.
    Consecutive single glyphs with the same font and size are joined, with a
    space where the gap between glyph centres is clearly larger than usual.
    """
    out: list[dict] = []
    run: list[dict] = []

    def flush():
        if not run:
            return
        if len(run) < 3:
            out.extend(run)
        else:
            centers = [((r["bbox"][0] + r["bbox"][2]) / 2, (r["bbox"][1] + r["bbox"][3]) / 2) for r in run]
            dists = [
                ((centers[i + 1][0] - centers[i][0]) ** 2 + (centers[i + 1][1] - centers[i][1]) ** 2) ** 0.5
                for i in range(len(run) - 1)
            ]
            base = statistics.median(dists)
            text = run[0]["text"]
            for d, r in zip(dists, run[1:]):
                text += (" " if d > base * 1.45 else "") + r["text"]
            xs0, ys0, xs1, ys1 = zip(*(r["bbox"] for r in run))
            out.append({**run[0], "text": text, "bbox": (min(xs0), min(ys0), max(xs1), max(ys1))})
        run.clear()

    seen_in_run: set[tuple] = set()
    for r in raw:
        single = len(r["text"].strip()) == 1
        key = (r["text"], tuple(round(v) for v in r["bbox"]))
        if single and run and r["font"] == run[-1]["font"] and abs(r["size"] - run[-1]["size"]) < 0.3:
            # a glyph we already saw in this run means a stroke/shadow copy started over
            if key in seen_in_run:
                flush()
                seen_in_run.clear()
            run.append(r)
            seen_in_run.add(key)
        elif single:
            flush()
            seen_in_run.clear()
            run.append(r)
            seen_in_run.add(key)
        else:
            flush()
            seen_in_run.clear()
            out.append(r)
    flush()
    return out


class ArtworkError(ValueError):
    """The artwork file is missing, unreadable or has no live text."""


def _open_page(pdf_path: Path, page_no: int) -> pymupdf.Page:
    if not pdf_path.exists():
        raise ArtworkError(f"Artwork file not found: {pdf_path.name}")
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:  # pymupdf raises several internal types
        raise ArtworkError(f"Could not open {pdf_path.name} as a PDF: {exc}") from exc
    if page_no >= len(doc):
        raise ArtworkError(f"{pdf_path.name} has {len(doc)} page(s), page {page_no + 1} requested")
    return doc[page_no]


def _raw_lines(page: pymupdf.Page) -> list[dict]:
    raw: list[dict] = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            chars = [ch for sp in line["spans"] for ch in sp["chars"]]
            text = "".join(ch["c"] for ch in chars).strip()
            if not text:
                continue
            size = max(sp["size"] for sp in line["spans"])
            if _looks_letter_spaced(text):
                text = _rebuild_spacing(chars, size)
            text = re.sub(r"\s{2,}", " ", text)
            raw.append({"text": text, "bbox": tuple(line["bbox"]), "size": size, "font": line["spans"][0]["font"]})
    return raw


def _dedupe(raw: list[dict]) -> list[dict]:
    """Drop exact duplicates: stroke and shadow copies of the same text."""
    seen: set[tuple] = set()
    unique: list[dict] = []
    for r in raw:
        key = (r["text"], tuple(round(v) for v in r["bbox"]))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _hidden_checker(page: pymupdf.Page):
    """Return a function telling whether a text box is covered by a later opaque fill.

    Text spans and vector fills share one drawing sequence number, so a fill
    with a higher number that fully contains the text was painted over it.
    Returns (seqno, hidden, layer) for a bbox.
    """
    trace = [
        (s["seqno"], _bbox(s["bbox"]), _squash("".join(chr(c[0]) for c in s["chars"])), s.get("layer"))
        for s in page.get_texttrace()
    ]
    opaque = [
        (d["seqno"], _bbox(d["rect"]))
        for d in page.get_drawings()
        if d.get("fill") is not None and (d.get("fill_opacity") or 1.0) >= 0.99
    ]

    def check(bb: BBox, text: str) -> tuple[int, bool, str | None]:
        # match spans by position AND content: different text can share a spot
        # (that is exactly what hidden text looks like)
        own = _squash(text)
        inside = [
            (abs(len(t) - len(own)), seq, layer)
            for seq, tb, t, layer in trace
            if len(t) >= min(3, len(own))  # one-letter spans match anything
            and (t in own or own in t)
            # overlap, not centre-inside: one span can hold a whole paragraph
            and tb.x0 < bb.x1 and tb.x1 > bb.x0
            and tb.y0 < bb.y1 and tb.y1 > bb.y0
        ]
        if not inside:
            # curved / tracked text: one glyph per span, all inside the line box
            inside = [(0, seq, layer) for seq, tb, t, layer in trace if t and bb.contains(tb, tol=1.0)]
        if not inside:
            return -1, False, None
        # closest text match wins ("Carbohydrate" vs the "Total Carbohydrate" on top of it)
        _, seq, layer = min(inside, key=lambda t: (t[0], t[1]))
        return seq, any(fs > seq and fb.contains(bb, tol=0.5) for fs, fb in opaque), layer

    return check


def read_artwork(pdf_path: str | Path, page_no: int = 0) -> Artwork:
    pdf_path = Path(pdf_path)
    page = _open_page(pdf_path, page_no)
    unique = _dedupe(_merge_curved(_raw_lines(page)))
    if not unique:
        raise ArtworkError(
            f"{pdf_path.name} has no live text. Outlined or scanned artwork needs OCR, which this prototype does not do yet."
        )

    guide_lines = [(r["text"], _bbox(r["bbox"])) for r in unique if _is_guide(r["text"])]
    panels = _detect_panels(page, guide_lines)
    is_hidden = _hidden_checker(page)

    lines: list[TextLine] = []
    for i, r in enumerate(unique):
        bb = _bbox(r["bbox"])
        seq, hidden, layer = is_hidden(bb, r["text"])
        lines.append(
            TextLine(
                id=f"L{i:03d}",
                text=r["text"],
                bbox=bb,
                size=round(r["size"], 1),
                font=r["font"],
                panel=_panel_for(bb, panels),
                role="guide" if _is_guide_line(r["text"], layer) else "copy",
                hidden=hidden,
                seqno=seq,
                layer=layer,
            )
        )

    return Artwork(
        file_name=pdf_path.name,
        path=str(pdf_path),
        width=page.rect.width,
        height=page.rect.height,
        panels=panels,
        content_panels=_content_panels(page, panels, lines),
        lines=lines,
        barcodes=read_barcodes(page, panels),
    )


def read_barcodes(page: pymupdf.Page, panels: dict[str, BBox], dpi: int = 300) -> list[dict]:
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    scale = 72 / dpi
    found = []
    for r in zxingcpp.read_barcodes(img):
        pos = r.position
        xs = [pos.top_left.x, pos.top_right.x, pos.bottom_left.x, pos.bottom_right.x]
        ys = [pos.top_left.y, pos.top_right.y, pos.bottom_left.y, pos.bottom_right.y]
        bb = BBox(x0=min(xs) * scale, y0=min(ys) * scale, x1=max(xs) * scale, y1=max(ys) * scale)
        found.append({"format": str(r.format).split(".")[-1], "text": r.text, "bbox": bb.model_dump(), "panel": _panel_for(bb, panels)})
    return found


@functools.lru_cache(maxsize=4)
def _page(pdf_path: str, page_no: int = 0) -> pymupdf.Page:
    """One open document per file: measuring dozens of glyphs must not re-open it each time."""
    return pymupdf.open(pdf_path)[page_no]


@functools.lru_cache(maxsize=4)
def _rawdict(pdf_path: str, page_no: int = 0) -> list:
    """Glyph-level text of the page, parsed once per file (parsing is the slow part)."""
    return _page(pdf_path, page_no).get_text("rawdict")["blocks"]


def ink_height(pdf_path: str | Path, bbox: BBox, dpi: int = 1200, page_no: int = 0) -> float | None:
    """Height in points of the printed ink inside a box (e.g. one glyph).

    Text boxes come from font metrics, which are taller than the letters, so
    real size checks measure rendered pixels instead. Ink is any pixel clearly
    different from the box's most common (background) colour.
    """
    page = _page(str(pdf_path), page_no)
    pix = page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1), colorspace=pymupdf.csGRAY)
    w, h, s = pix.width, pix.height, pix.samples
    if not w or not h:
        return None
    bg = Counter(s).most_common(1)[0][0]
    # map every grey level to 1 (ink) or 0 (background) once, then count per row at C speed
    ink_map = bytes(1 if abs(v - bg) > 90 else 0 for v in range(256))
    mask = s.translate(ink_map)
    rows = []
    for y in range(h):
        inked = mask.count(1, y * w, (y + 1) * w)
        # a row inked edge to edge is a rule line (e.g. Nutrition Facts bars), never part of a letter
        if 0 < inked < 0.9 * w:
            rows.append(y)
    return (rows[-1] - rows[0] + 1) * 72 / dpi if rows else None


def glyph_boxes(pdf_path: str | Path, line_bbox: BBox, chars: str, page_no: int = 0, text: str | None = None) -> list[BBox]:
    """Boxes of the given characters in one text line (x from the font, y from the line).

    Pass the line's text so characters from other text in the same spot
    (hidden layers, overlapping copy) are not measured by mistake.
    """
    out = []
    for block in _rawdict(str(pdf_path), page_no):
        for line in block.get("lines", []):
            if not line_bbox.contains(_bbox(line["bbox"]), tol=max(line_bbox.y1 - line_bbox.y0, 20)):
                continue
            line_text = "".join(c["c"] for sp in line["spans"] for c in sp["chars"])
            if text and _squash(text) not in _squash(line_text) and _squash(line_text) not in _squash(text):
                continue
            for span in line["spans"]:
                for ch in span["chars"]:
                    b = _bbox(ch["bbox"])
                    if ch["c"] in chars and line_bbox.contains(b, tol=1.5):
                        # middle 60% only: kerned neighbours ("To") overlap the outer edges
                        inset = (b.x1 - b.x0) * 0.2
                        out.append(BBox(x0=b.x0 + inset, y0=b.y0, x1=b.x1 - inset, y1=b.y1))
    return out


def render_panel_png(pdf_path: str | Path, bbox: BBox, dpi: int = 110, page_no: int = 0) -> bytes:
    page = pymupdf.open(pdf_path)[page_no]
    return page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)).tobytes("png")


def render_png(pdf_path: str | Path, out_path: str | Path, dpi: int = 110, page_no: int = 0) -> tuple[int, int]:
    page = pymupdf.open(pdf_path)[page_no]
    pix = page.get_pixmap(dpi=dpi)
    pix.save(str(out_path))
    return pix.width, pix.height
