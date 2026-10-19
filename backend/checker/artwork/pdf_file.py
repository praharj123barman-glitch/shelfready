"""Opening an artwork PDF, once per file version.

Every part of the checker that needs the PDF (reading text, measuring glyphs,
finding dieline lines) asks ``PdfFile.open(path)`` and gets the same shared
object, so a 40-check review parses the file once instead of 40 times.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pymupdf

from ..models import BBox

Segment = tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points


class ArtworkError(ValueError):
    """The artwork file is missing, unreadable or has no live text."""


def to_bbox(rect) -> BBox:
    """A BBox from any 4-number rectangle (PyMuPDF Rect or tuple)."""
    return BBox(x0=float(rect[0]), y0=float(rect[1]), x1=float(rect[2]), y1=float(rect[3]))


def file_version(path: Path) -> tuple[int, int]:
    """(modification time, size). It changes whenever the file is rewritten,
    so caches keyed on it never answer with an old version of the file."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


class PdfFile:
    """One artwork PDF, opened once per file version and shared.

    Use ``PdfFile.open(path)``; the constructor is for the cache. The document
    is opened from bytes, so it never holds a file lock (Windows would block
    rewriting or deleting the file while the server runs).
    """

    def __init__(self, path: Path, doc: pymupdf.Document) -> None:
        self.path = path
        self.name = path.name
        self.doc = doc
        self._glyphs: dict[int, list] = {}
        self._segments: dict[tuple[str, int], list[Segment]] = {}

    @classmethod
    def open(cls, path: str | Path) -> "PdfFile":
        path = Path(path)
        if not path.exists():
            raise ArtworkError(f"Artwork file not found: {path.name}")
        return _open_version(str(path), file_version(path))

    @property
    def page_count(self) -> int:
        return len(self.doc)

    def page(self, page_no: int = 0) -> pymupdf.Page:
        if page_no >= self.page_count:
            raise ArtworkError(f"{self.name} has {self.page_count} page(s), page {page_no + 1} requested")
        return self.doc[page_no]

    def glyphs(self, page_no: int = 0) -> list[dict]:
        """The page's text as PyMuPDF 'rawdict' blocks (one entry per glyph).
        Parsed once per page, because parsing is the slow part."""
        if page_no not in self._glyphs:
            self._glyphs[page_no] = self.page(page_no).get_text("rawdict")["blocks"]
        return self._glyphs[page_no]

    def dieline_segments(self, layer_word: str, page_no: int = 0) -> list[Segment]:
        """Straight lines drawn on layers whose name contains `layer_word` ('crease', 'cut', ...)."""
        key = (layer_word, page_no)
        if key not in self._segments:
            self._segments[key] = _segments_on_layer(self.page(page_no), layer_word)
        return self._segments[key]


@functools.lru_cache(maxsize=8)
def _open_version(path: str, version: tuple[int, int]) -> PdfFile:
    try:
        doc = pymupdf.open(stream=Path(path).read_bytes(), filetype="pdf")
    except Exception as exc:  # pymupdf raises several internal types
        # the library message contains server paths: keep it on the exception chain, not in the reply
        raise ArtworkError(f"Could not open {Path(path).name}: the file is damaged or not a PDF.") from exc
    return PdfFile(Path(path), doc)


def _segments_on_layer(page: pymupdf.Page, layer_word: str) -> list[Segment]:
    segments: list[Segment] = []
    for drawing in page.get_drawings():
        if layer_word not in (drawing.get("layer") or "").lower():
            continue
        for item in drawing["items"]:
            if item[0] == "l":  # line
                segments.append((item[1].x, item[1].y, item[2].x, item[2].y))
            elif item[0] == "re":  # rectangle: its four sides
                r = item[1]
                segments += [(r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1), (r.x0, r.y1, r.x1, r.y1), (r.x0, r.y0, r.x0, r.y1)]
    return segments
