"""Everything that touches the artwork PDF.

    pdf_file.py     PdfFile: opens a PDF once per file version and shares it; ArtworkError
    reader.py       read_artwork(): the PDF as an Artwork (lines, panels, barcodes)
    text_lines.py   TextAssembler: glyphs -> clean lines (letter spacing, curved text, duplicates)
    guides.py       dieline print marks vs real copy
    panels.py       PanelFinder: which part of the flat sheet is the front, back, flaps ...
    hidden_text.py  HiddenTextDetector: text covered by a shape painted over it
    measure.py      ink height and glyph boxes, for minimum type size rules
    render.py       PNG renders: full page, print-only view, panel crops

The rest of the checker imports from this package, not from the modules.
"""

from .measure import glyph_boxes, ink_height
from .pdf_file import PDF_LOCK, ArtworkError, PdfFile
from .reader import read_artwork, read_barcodes
from .render import render_panel_png, render_png, render_print_png

__all__ = [
    "PDF_LOCK", "ArtworkError", "PdfFile", "glyph_boxes", "ink_height", "read_artwork", "read_barcodes",
    "render_panel_png", "render_png", "render_print_png",
]
