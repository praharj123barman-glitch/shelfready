"""Rendering the artwork to PNG: the whole page, the print-only view, and panel crops.

Renders are kept on the shared PdfFile (one per distinct file content), so
reviewing the same artwork again, comparing proofs, or showing panels to the
AI twice does not draw the page again.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from ..models import BBox
from .guides import is_structural_layer
from .pdf_file import PdfFile

LAYER_OFF = 2  # PyMuPDF set_layer_ui_config action


def render_png(pdf_path: str | Path, out_path: str | Path, dpi: int = 110, page_no: int = 0) -> tuple[int, int]:
    """The page as drawn, guides included. Returns the image size in pixels."""
    pdf = PdfFile.open(pdf_path)
    key = ("page", dpi, page_no)
    if key not in pdf.renders:
        pix = pdf.page(page_no).get_pixmap(dpi=dpi)
        pdf.renders[key] = (pix.tobytes("png"), pix.width, pix.height)
    png, width, height = pdf.renders[key]
    Path(out_path).write_bytes(png)
    return width, height


def render_panel_png(pdf_path: str | Path, bbox: BBox, dpi: int = 110, page_no: int = 0) -> bytes:
    """One area of the page as PNG bytes (used to show panels to the AI)."""
    pdf = PdfFile.open(pdf_path)
    key = ("area", dpi, page_no, bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    if key not in pdf.renders:
        clip = pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
        pdf.renders[key] = (pdf.page(page_no).get_pixmap(dpi=dpi, clip=clip).tobytes("png"), 0, 0)
    return pdf.renders[key][0]


def render_print_png(pdf_path: str | Path, out_path: str | Path, dpi: int = 110, page_no: int = 0) -> bool:
    """Render only what prints: dieline layers (cut, crease, dimensions, guides) switched off.
    Returns False when the file has no layers to switch off (the normal render is then the print view)."""
    pdf = PdfFile.open(pdf_path)
    key = ("print", dpi, page_no)
    if key not in pdf.renders:
        pdf.renders[key] = (_print_view(Path(pdf_path), dpi, page_no), 0, 0)
    png = pdf.renders[key][0]
    if png is None:
        return False
    Path(out_path).write_bytes(png)
    return True


def _print_view(pdf_path: Path, dpi: int, page_no: int) -> bytes | None:
    # a private copy of the document: switching layers off must not affect the shared one
    doc = pymupdf.open(stream=pdf_path.read_bytes(), filetype="pdf")
    configs = doc.layer_ui_configs()
    # the viewer's layer switches (UI configs) are what rendering honours; the safe-area
    # outline ("Artwork panel") does not print either
    off = {c["number"] for c in configs if is_structural_layer(c["text"]) or c["text"].strip().lower() == "artwork panel"}
    if not off:
        return None
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
    return doc[page_no].get_pixmap(dpi=dpi).tobytes("png")
