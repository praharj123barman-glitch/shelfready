"""Rendering the artwork to PNG: the whole page, the print-only view, and panel crops."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from ..models import BBox
from .guides import is_structural_layer
from .pdf_file import PdfFile

LAYER_OFF = 2  # PyMuPDF set_layer_ui_config action


def render_png(pdf_path: str | Path, out_path: str | Path, dpi: int = 110, page_no: int = 0) -> tuple[int, int]:
    """The page as drawn, guides included. Returns the image size in pixels."""
    pix = PdfFile.open(pdf_path).page(page_no).get_pixmap(dpi=dpi)
    pix.save(str(out_path))
    return pix.width, pix.height


def render_panel_png(pdf_path: str | Path, bbox: BBox, dpi: int = 110, page_no: int = 0) -> bytes:
    """One area of the page as PNG bytes (used to show panels to the AI)."""
    page = PdfFile.open(pdf_path).page(page_no)
    return page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)).tobytes("png")


def render_print_png(pdf_path: str | Path, out_path: str | Path, dpi: int = 110, page_no: int = 0) -> bool:
    """Render only what prints: dieline layers (cut, crease, dimensions, guides) switched off.
    Returns False when the file has no layers to switch off (the normal render is then the print view)."""
    # a private copy of the document: switching layers off must not affect the shared one
    doc = pymupdf.open(stream=Path(pdf_path).read_bytes(), filetype="pdf")
    configs = doc.layer_ui_configs()
    # the viewer's layer switches (UI configs) are what rendering honours; the safe-area
    # outline ("Artwork panel") does not print either
    off = {c["number"] for c in configs if is_structural_layer(c["text"]) or c["text"].strip().lower() == "artwork panel"}
    if not off:
        return False
    # switching children off is not enough when their top-level group stays on, so also switch
    # off every top-level group that contains a dieline layer (the DESIGN group has none)
    group = None
    for c in configs:
        if c["depth"] == 0:
            group = c["number"]
        elif c["number"] in off and group is not None:
            off.add(group)
    for number in off:
        doc.set_layer_ui_config(number, LAYER_OFF)
    doc[page_no].get_pixmap(dpi=dpi).save(str(out_path))
    return True
