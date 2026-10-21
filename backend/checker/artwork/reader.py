"""Reading an artwork PDF into an Artwork: positioned text lines, panels and barcodes.

    art = read_artwork("carton.pdf")
    art.lines[0].text, art.lines[0].panel, art.lines[0].hidden

Text is read live from the PDF, with its position on the dieline. A page with
no live text (a scan, a photo, outlined type) is read by OCR instead (ocr.py),
and the Artwork says so. ``ArtworkReader`` adds what a plain text dump loses:
the panel each line sits on, whether it is a dieline mark or real copy, and
whether it is hidden under a shape.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import zxingcpp
from PIL import Image

from ..models import Artwork, BBox, TextLine
from .guides import is_guide_line, is_guide_text
from .hidden_text import HiddenTextDetector
from .ocr import ocr_available, ocr_lines
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
        raw_lines, all_raw, source = text.lines, text.raw, "live"
        if not raw_lines:  # a scan, a photo or outlined type: read the page image instead
            raw_lines = all_raw = self._ocr_lines()
            source = "ocr"
        elif invisible_share(self.page) >= INVISIBLE_LAYER_SHARE:
            source = "ocr_layer"  # a searchable scan: its "live" text is the scanner's OCR guess, not the artwork
        guide_lines = [(line.text, line.box) for line in raw_lines if is_guide_text(line.text)]
        panels = PanelFinder(self.pdf, self.page_no, guide_lines, all_raw).find()
        lines = self._text_lines(raw_lines, panels)
        return Artwork(
            file_name=self.name,
            path=str(self.path) if self.path else "",
            width=self.page.rect.width,
            height=self.page.rect.height,
            panels=panels,
            content_panels=content_panels(self.page, panels, lines),
            page_count=self.pdf.page_count,
            text_source=source,
            lines=lines,
            barcodes=read_barcodes(self.page, panels),
        )

    def _ocr_lines(self) -> list[RawLine]:
        """The page's text by OCR, when the PDF has none. Text on another page means the wrong page was
        exported, which is more useful to say than to OCR the empty one."""
        with_text = [i + 1 for i in range(self.pdf.page_count)
                     if i != self.page_no and self.pdf.page(i).get_text("text").strip()]
        if with_text:
            raise ArtworkError(f"Page {self.page_no + 1} of {self.name} has no live text, but page {with_text[0]} does. "
                               "Only the first page is checked: export the artwork page on its own and upload that.")
        if not ocr_available():
            raise ArtworkError(f"{self.name} has no live text, and OCR is not installed "
                               "(pip install -r requirements.txt adds it).")
        try:
            lines = ocr_lines(self.page)
        except Exception as exc:  # an OCR failure must be an error the user sees, never an empty review
            raise ArtworkError(f"OCR could not read {self.name} ({type(exc).__name__}). "
                               "Upload the print PDF, or a different scan.") from exc
        if not lines:
            raise ArtworkError(f"{self.name} has no live text, and OCR found no readable text on it either. "
                               "Upload the print PDF, or a sharper scan (300 dpi or more).")
        return lines

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
                confidence=raw.confidence,
            ))
        return lines


INVISIBLE_LAYER_SHARE = 0.5  # more than half the characters invisible: a searchable scan, not artwork


def invisible_share(page: pymupdf.Page) -> float:
    """Share of the page's characters drawn invisibly (PDF text render mode 3). Scanning software
    puts its OCR text on the page this way, over the scanned picture, so the file can be searched."""
    spans = page.get_texttrace()
    total = sum(len(span["chars"]) for span in spans)
    invisible = sum(len(span["chars"]) for span in spans if span.get("type") == 3)
    return invisible / total if total else 0.0


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
