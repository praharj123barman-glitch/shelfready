"""Print readiness from the dieline geometry and measured type sizes.

Fold lines and safe areas come from the PDF's own dieline layers; type sizes
are measured from rendered ink, not font metrics. Everything here is geometry
or measurement, so verdicts are DEFINITE or LIKELY with the numbers shown.
"""

from __future__ import annotations

import statistics

from ..artwork import PdfFile, glyph_boxes, ink_height
from ..artwork.pdf_file import Segment
from ..models import BBox, Finding, TextLine, Verdict
from ..sections import net_quantity_lines
from .registry import check
from .base import CheckContext, art_evidence, computed, fmt

PT_PER_INCH = 72.0
MIN_O_HEIGHT_IN = 1 / 16  # 21 CFR 101.2(c)
SAMPLES_PER_BLOCK = 3  # glyphs measured per copy block; the median is reported
FOLD_TOLERANCE = 1.0  # pt: a line must enter the text box by more than this to count as crossing
# 21 CFR 101.105(i): (max PDP area in sq in, minimum numeral height in inches)
NET_QTY_HEIGHTS = [(5, 1 / 16), (25, 1 / 8), (100, 3 / 16), (400, 1 / 4), (float("inf"), 1 / 2)]


def _segments(ctx: CheckContext, layer: str) -> list[Segment]:
    """Dieline lines on layers named like `layer` ('crease', 'cut'); PdfFile caches them per file version."""
    return PdfFile.open(ctx.art.path).dieline_segments(layer) if ctx.art.path else []


def _crosses(seg, bb: BBox, tol: float = FOLD_TOLERANCE) -> bool:
    """True when a straight segment passes through the inside of the box."""
    x0, y0, x1, y1 = seg
    inner = BBox(x0=bb.x0 + tol, y0=bb.y0 + tol, x1=bb.x1 - tol, y1=bb.y1 - tol)
    if inner.x0 >= inner.x1 or inner.y0 >= inner.y1:
        return False
    if abs(y0 - y1) < 0.5:  # horizontal
        return inner.y0 < y0 < inner.y1 and min(x0, x1) < inner.x1 and max(x0, x1) > inner.x0
    if abs(x0 - x1) < 0.5:  # vertical
        return inner.x0 < x0 < inner.x1 and min(y0, y1) < inner.y1 and max(y0, y1) > inner.y0
    # diagonal fold (dust flaps): sample points along it
    return any(inner.x0 < x0 + (x1 - x0) * t < inner.x1 and inner.y0 < y0 + (y1 - y0) * t < inner.y1 for t in (i / 40 for i in range(41)))


@check("DF-11")
def check_folds(ctx: CheckContext) -> list[Finding]:
    creases = _segments(ctx, "crease")
    if not creases:
        return [ctx.finding("folds", "print_readiness", Verdict.REVIEW, "No fold lines found in the file",
                            "The PDF has no crease layer, so copy crossing folds cannot be checked.", rule_id="DF-11")]
    crossing = [ln for ln in ctx.art.copy_lines() if any(_crosses(s, ln.bbox) for s in creases)]
    if not crossing:
        return [ctx.finding("folds", "print_readiness", Verdict.PASS, "No copy crosses a fold line",
                            f"Checked {len(ctx.art.copy_lines())} text lines against {len(creases)} fold segments.", rule_id="DF-11")]
    names = sorted({ln.text for ln in crossing})
    return [ctx.finding(
        "folds", "print_readiness", Verdict.DEFINITE, f"Copy crosses a fold line: {', '.join(repr(n) for n in names[:3])}",
        f"{len(crossing)} text line(s) run across a crease on the dieline, so the words will wrap around the edge of "
        f"the carton when it is folded: {', '.join(f'{ln.text!r} ({ln.panel})' for ln in crossing[:5])}.",
        rule_id="DF-11", evidence=[art_evidence([ln]) for ln in crossing[:6]],
        fix="Move or scale the text so it sits inside one face, clear of the fold.",
    )]


def _safe_areas(ctx: CheckContext) -> dict[str, BBox]:
    """Each panel's safe area is the box around the dashed artwork-panel lines inside it."""
    segs = _segments(ctx, "artwork panel")
    areas: dict[str, BBox] = {}
    for name, p in ctx.art.panels.items():
        inside = [s for s in segs if p.x0 - 1 <= (s[0] + s[2]) / 2 <= p.x1 + 1 and p.y0 - 1 <= (s[1] + s[3]) / 2 <= p.y1 + 1]
        if len(inside) >= 3:
            xs = [v for s in inside for v in (s[0], s[2])]
            ys = [v for s in inside for v in (s[1], s[3])]
            areas[name] = BBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
    return areas


@check("DF-11")
def check_safe_area(ctx: CheckContext) -> list[Finding]:
    areas = _safe_areas(ctx)
    if not areas:
        return []
    creases = _segments(ctx, "crease")
    outside: list[tuple[TextLine, float]] = []
    for ln in ctx.art.copy_lines():
        area = areas.get(ln.panel)
        if area is None or any(_crosses(s, ln.bbox) for s in creases):  # fold crossings are reported separately
            continue
        overshoot = max(area.x0 - ln.bbox.x0, ln.bbox.x1 - area.x1, area.y0 - ln.bbox.y0, ln.bbox.y1 - area.y1)
        if overshoot > 1.0:
            outside.append((ln, overshoot))
    if not outside:
        return [ctx.finding("safe_area", "print_readiness", Verdict.PASS, "All copy is inside the safe areas",
                            f"Safe areas found for {len(areas)} panels.", rule_id="DF-11")]
    return [ctx.finding(
        "safe_area", "print_readiness", Verdict.LIKELY, f"{len(outside)} text line(s) extend past the safe area",
        "Text outside the dashed safe-area line risks being trimmed or folded: "
        + "; ".join(f"{ln.text!r} ({ln.panel}, {o:.1f} pt over)" for ln, o in outside[:5]) + ".",
        rule_id="DF-11", evidence=[art_evidence([ln]) for ln, _ in outside[:6]],
    )]


def _mandatory_lines(ctx: CheckContext) -> list[tuple[str, TextLine]]:
    """Required information panel copy. The Nutrition Facts panel has its own
    point-size rules (101.9(d)), so it is not measured against 101.2(c) here."""
    out = []
    for name in ("ingredients", "allergen_information", "dietary_information"):
        if b := ctx.blocks.get(name):
            out += [(name.replace("_", " "), ln) for ln in b.lines]
    return out


@check("FDA-101.2-TYPE")
def check_min_type_size(ctx: CheckContext) -> list[Finding]:
    if not ctx.art.path:
        return []
    by_block: dict[str, list[tuple[TextLine, float]]] = {}
    for block, ln in _mandatory_lines(ctx):
        if len(by_block.get(block, [])) >= SAMPLES_PER_BLOCK:
            continue
        for g in glyph_boxes(ctx.art.path, ln.bbox, "o", text=ln.text)[:SAMPLES_PER_BLOCK]:
            if h := ink_height(ctx.art.path, g):
                by_block.setdefault(block, []).append((ln, h))
    if not by_block:
        return [ctx.finding("type_size", "print_readiness", Verdict.REVIEW, "Could not measure type size",
                            "No lowercase 'o' was found in the required copy to measure.", rule_id="FDA-101.2-TYPE")]
    minimum = MIN_O_HEIGHT_IN * PT_PER_INCH
    rows, small_lines = [], []
    for block, samples in by_block.items():
        h = statistics.median(s[1] for s in samples)
        rows.append({"copy": block, "o height": f"{h / PT_PER_INCH:.3f} in ({h * 25.4 / 72:.2f} mm)",
                     "minimum": f"{MIN_O_HEIGHT_IN:.4f} in (1.59 mm)", "ok": "yes" if h >= minimum else "no"})
        if h < minimum:
            small_lines.append(samples[0][0])
    if not small_lines:
        return [ctx.finding("type_size", "print_readiness", Verdict.PASS, "Required copy meets the 1/16 inch minimum",
                            "Measured on the lowercase 'o'.", rule_id="FDA-101.2-TYPE", details=rows)]
    return [ctx.finding(
        "type_size", "print_readiness", Verdict.LIKELY, "Required copy is smaller than 1/16 inch",
        "Measured from the printed ink of the lowercase 'o': "
        + "; ".join(f"{r['copy']} {r['o height']}" for r in rows if r["ok"] == "no")
        + ". FDA's minimum is 1/16 inch unless a small-package exemption applies, which a carton this size does not obviously qualify for.",
        rule_id="FDA-101.2-TYPE", details=rows, evidence=[art_evidence([ln]) for ln in small_lines],
        fix="Enlarge the ingredient and allergen copy until the lowercase 'o' is at least 1.6 mm tall.",
    )]


@check("FDA-101.105-HEIGHT")
def check_net_quantity_height(ctx: CheckContext) -> list[Finding]:
    front = ctx.art.panels.get("front")
    # best first: a NET WT line on the front panel is the one the law measures
    candidates = net_quantity_lines(ctx.art)
    qty = candidates[0] if candidates else None
    if front is None or qty is None or not ctx.art.path:
        return []
    area = (front.x1 - front.x0) * (front.y1 - front.y0) / PT_PER_INCH**2
    need_in = next(h for limit, h in NET_QTY_HEIGHTS if area <= limit)
    digits = [h for g in glyph_boxes(ctx.art.path, qty.bbox, "0123456789", text=qty.text) if (h := ink_height(ctx.art.path, g))]
    if not digits:
        return []
    got_in = max(digits) / PT_PER_INCH
    ev = [art_evidence([qty]), computed(f"Front panel {(front.x1 - front.x0) / 72:.2f} x {(front.y1 - front.y0) / 72:.2f} in = {area:.1f} sq in; "
                                        f"numerals measured {got_in:.3f} in tall")]
    if got_in >= need_in:
        return [ctx.finding("net_qty_height", "mandatory", Verdict.PASS, "Net quantity numerals are tall enough",
                            f"{got_in:.3f} in against {need_in:.4f} in required.", rule_id="FDA-101.105-HEIGHT", evidence=ev)]
    # measurement is within ~0.005 in, so only a clear shortfall is called definite
    verdict = Verdict.DEFINITE if got_in < need_in * 0.9 else Verdict.LIKELY
    return [ctx.finding(
        "net_qty_height", "mandatory", verdict, f"Net quantity numerals are {got_in:.2f} in tall, {need_in:.4g} in required",
        f"The front panel is {area:.0f} sq in, so FDA requires net quantity numbers at least {fmt(round(need_in * 16))}/16 inch "
        f"({need_in * 25.4:.1f} mm) tall. '{qty.text}' measures {got_in:.3f} in ({got_in * 25.4:.1f} mm).",
        rule_id="FDA-101.105-HEIGHT", expected=f"at least {need_in:.4g} in", found=f"{got_in:.3f} in", evidence=ev,
        fix=f"Set the net quantity at least {need_in * 25.4:.1f} mm tall on the front panel.",
    )]

