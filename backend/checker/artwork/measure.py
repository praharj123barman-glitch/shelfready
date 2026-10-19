"""Measuring printed type, for minimum-size rules.

Text boxes come from font metrics, which are taller than the letters, so a
"type at least 1/16 inch" check must measure the ink itself.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pymupdf

from ..models import BBox
from .pdf_file import PdfFile, to_bbox
from .text_lines import squash

INK_CONTRAST = 90  # grey levels away from the background that count as ink


def ink_height(pdf_path: str | Path, bbox: BBox, dpi: int = 1200, page_no: int = 0) -> float | None:
    """Height in points of the printed ink inside a box (e.g. one glyph).
    Ink is any pixel clearly different from the box's most common (background) colour."""
    page = PdfFile.open(pdf_path).page(page_no)
    pix = page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1), colorspace=pymupdf.csGRAY)
    width, height, pixels = pix.width, pix.height, pix.samples
    if not width or not height:
        return None
    background = Counter(pixels).most_common(1)[0][0]
    # map every grey level to 1 (ink) or 0 (background) once, then count per row at C speed
    ink_map = bytes(1 if abs(v - background) > INK_CONTRAST else 0 for v in range(256))
    mask = pixels.translate(ink_map)
    inked_rows = []
    for y in range(height):
        inked = mask.count(1, y * width, (y + 1) * width)
        # a row inked edge to edge is a rule line (e.g. Nutrition Facts bars), never part of a letter
        if 0 < inked < 0.9 * width:
            inked_rows.append(y)
    return (inked_rows[-1] - inked_rows[0] + 1) * 72 / dpi if inked_rows else None


def glyph_boxes(pdf_path: str | Path, line_bbox: BBox, chars: str, page_no: int = 0, text: str | None = None) -> list[BBox]:
    """Boxes of the given characters in one text line (x from the font, y from the line).

    Pass the line's text so characters from other text in the same spot
    (hidden layers, overlapping copy) are not measured by mistake.
    """
    out = []
    for block in PdfFile.open(pdf_path).glyphs(page_no):
        for line in block.get("lines", []):
            if not line_bbox.contains(to_bbox(line["bbox"]), tol=max(line_bbox.y1 - line_bbox.y0, 20)):
                continue
            line_text = "".join(c["c"] for span in line["spans"] for c in span["chars"])
            if text and squash(text) not in squash(line_text) and squash(line_text) not in squash(text):
                continue
            for span in line["spans"]:
                for ch in span["chars"]:
                    box = to_bbox(ch["bbox"])
                    if ch["c"] in chars and line_bbox.contains(box, tol=1.5):
                        # middle 60% only: kerned neighbours ("To") overlap the outer edges
                        inset = (box.x1 - box.x0) * 0.2
                        out.append(BBox(x0=box.x0 + inset, y0=box.y0, x1=box.x1 - inset, y1=box.y1))
    return out
