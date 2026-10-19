"""Reading an artwork PDF into an Artwork: positioned text lines, panels and barcodes.

    art = read_artwork("carton.pdf")
    art.lines[0].text, art.lines[0].panel, art.lines[0].hidden

Text is read live from the PDF (no OCR guessing), with its position on the
dieline. ``ArtworkReader`` adds what a plain text dump loses: the panel each
line sits on, whether it is a dieline mark or real copy, and whether it is
hidden under a shape.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pymupdf
import zxingcpp
from PIL import Image

from ..models import Artwork, BBox, TextLine
from .guides import is_guide_line, is_guide_text
from .hidden_text import HiddenTextDetector
from .panels import PanelFinder, content_panels, panel_for
from .pdf_file import ArtworkError, PdfFile, file_version
from .text_lines import RawLine, TextAssembler


def read_artwork(pdf_path: str | Path, page_no: int = 0) -> Artwork:
    """Read an artwork PDF. Results are cached per file version, and each call
    returns its own copy so callers cannot change each other's data."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise ArtworkError(f"Artwork file not found: {pdf_path.name}")
    return _read_version(str(pdf_path), page_no, file_version(pdf_path)).model_copy(deep=True)


@functools.lru_cache(maxsize=8)
def _read_version(path: str, page_no: int, version: tuple[int, int]) -> Artwork:
    return ArtworkReader(PdfFile.open(path), page_no).read()


class ArtworkReader:
    def __init__(self, pdf: PdfFile, page_no: int = 0) -> None:
        self.pdf = pdf
        self.page_no = page_no
        self.page = pdf.page(page_no)

    def read(self) -> Artwork:
        text = TextAssembler(self.pdf.glyphs(self.page_no))
        if not text.lines:
            raise ArtworkError(
                f"{self.pdf.name} has no live text. Outlined or scanned artwork needs OCR, which this prototype does not do yet."
            )
        guide_lines = [(line.text, line.box) for line in text.lines if is_guide_text(line.text)]
        panels = PanelFinder(self.pdf, self.page_no, guide_lines, text.raw).find()
        lines = self._text_lines(text.lines, panels)
        return Artwork(
            file_name=self.pdf.name,
            path=str(self.pdf.path),
            width=self.page.rect.width,
            height=self.page.rect.height,
            panels=panels,
            content_panels=content_panels(self.page, panels, lines),
            page_count=self.pdf.page_count,
            lines=lines,
            barcodes=read_barcodes(self.page, panels),
        )

    def _text_lines(self, raw_lines: list[RawLine], panels: dict[str, BBox]) -> list[TextLine]:
        detector = HiddenTextDetector(self.page)
        lines = []
        for i, raw in enumerate(raw_lines):
            box = raw.box
            paint = detector.inspect(box, raw.text)
            lines.append(TextLine(
                id=f"L{i:03d}",
                text=raw.text,
                bbox=box,
                size=round(raw.size, 1),
                font=raw.font,
                panel=panel_for(box, panels),
                role="guide" if is_guide_line(raw.text, paint.layer) else "copy",
                hidden=paint.hidden,
                seqno=paint.seqno,
                layer=paint.layer,
            ))
        return lines


def read_barcodes(page: pymupdf.Page, panels: dict[str, BBox], dpi: int = 300) -> list[dict]:
    """Decode every barcode on the rendered page, with its box and panel."""
    pix = page.get_pixmap(dpi=dpi)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    points_per_pixel = 72 / dpi
    found = []
    for code in zxingcpp.read_barcodes(image):
        pos = code.position
        xs = [pos.top_left.x, pos.top_right.x, pos.bottom_left.x, pos.bottom_right.x]
        ys = [pos.top_left.y, pos.top_right.y, pos.bottom_left.y, pos.bottom_right.y]
        box = BBox(x0=min(xs) * points_per_pixel, y0=min(ys) * points_per_pixel,
                   x1=max(xs) * points_per_pixel, y1=max(ys) * points_per_pixel)
        found.append({"format": str(code.format).split(".")[-1], "text": code.text,
                      "bbox": box.model_dump(), "panel": panel_for(box, panels)})
    return found
