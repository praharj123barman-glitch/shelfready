"""Reading an artwork PDF into an Artwork: positioned text lines, panels and barcodes.

    art = read_artwork("carton.pdf")
    art.lines[0].text, art.lines[0].panel, art.lines[0].hidden

Text is read live from the PDF (no OCR guessing), with its position on the
dieline. ``ArtworkReader`` adds what a plain text dump loses: the panel each
line sits on, whether it is a dieline mark or real copy, and whether it is
hidden under a shape.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import zxingcpp
from PIL import Image

from ..models import Artwork, BBox, TextLine
from .guides import is_guide_line, is_guide_text
from .hidden_text import HiddenTextDetector
from .panels import PanelFinder, content_panels, panel_for
from .pdf_file import ArtworkError, PdfFile
from .text_lines import RawLine, TextAssembler


def read_artwork(pdf_path: str | Path, page_no: int = 0) -> Artwork:
    """Read an artwork PDF. Results are cached per file content (the same bytes
    at another path, e.g. a new run folder, are not parsed again), and each call
    returns its own copy, stamped with the path it was asked for."""
    pdf_path = Path(pdf_path)
    pdf = PdfFile.open(pdf_path)
    if page_no not in pdf.artworks:
        pdf.artworks[page_no] = ArtworkReader(pdf, page_no, pdf_path).read()
    return pdf.artworks[page_no].model_copy(deep=True, update={"file_name": pdf_path.name, "path": str(pdf_path)})


class ArtworkReader:
    def __init__(self, pdf: PdfFile, page_no: int = 0, path: Path | None = None) -> None:
        self.pdf = pdf
        self.page_no = page_no
        self.page = pdf.page(page_no)
        self.path = path  # the path this reading was asked for (names in messages and in the Artwork)
        self.name = path.name if path else pdf.name

    def read(self) -> Artwork:
        text = TextAssembler(self.pdf.glyphs(self.page_no))
        if not text.lines:
            raise ArtworkError(self._no_text_message())
        guide_lines = [(line.text, line.box) for line in text.lines if is_guide_text(line.text)]
        panels = PanelFinder(self.pdf, self.page_no, guide_lines, text.raw).find()
        lines = self._text_lines(text.lines, panels)
        return Artwork(
            file_name=self.name,
            path=str(self.path) if self.path else "",
            width=self.page.rect.width,
            height=self.page.rect.height,
            panels=panels,
            content_panels=content_panels(self.page, panels, lines),
            page_count=self.pdf.page_count,
            lines=lines,
            barcodes=read_barcodes(self.page, panels),
        )

    def _no_text_message(self) -> str:
        """Why there is nothing to check: the file has no text at all, or its text is on another page."""
        with_text = [i + 1 for i in range(self.pdf.page_count)
                     if i != self.page_no and self.pdf.page(i).get_text("text").strip()]
        if with_text:
            return (f"Page {self.page_no + 1} of {self.name} has no live text, but page {with_text[0]} does. "
                    "Only the first page is checked: export the artwork page on its own and upload that.")
        return f"{self.name} has no live text. Outlined or scanned artwork needs OCR, which this prototype does not do yet."

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
    # greyscale: zxing decodes brightness anyway; same results on every test PDF, about 20% faster
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
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
