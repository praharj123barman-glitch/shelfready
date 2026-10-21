"""Opening an artwork PDF, once per distinct file content.

Every part of the checker that needs the PDF (reading text, measuring glyphs,
finding dieline lines) asks ``PdfFile.open(path)`` and gets the same shared
object, so a 40-check review parses the file once instead of 40 times.
"""

from __future__ import annotations

import functools
import hashlib
import io
import threading
from collections import OrderedDict
from pathlib import Path

import pymupdf

from ..models import Artwork, BBox

Segment = tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points

# PyMuPDF is not thread-safe and documents are shared, so code that may run
# alongside other requests (the API's worker threads) holds this while using it
PDF_LOCK = threading.RLock()


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


def content_digest(path: Path) -> str:
    """SHA-256 of the file's bytes, hashed once per file version (path, mtime, size)."""
    return _digest_of_version(str(path), file_version(path))


@functools.lru_cache(maxsize=64)
def _digest_of_version(path: str, version: tuple[int, int]) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PdfFile:
    """One artwork PDF, opened once per distinct content and shared.

    Shared by content, not by path: every review copies its files into a new
    run folder, so the same artwork arrives at a new path each time. Identical
    bytes are the same input, so they reuse one parsed document.

    Use ``PdfFile.open(path)``; the constructor is for the cache. The document
    is opened from bytes, so it never holds a file lock (Windows would block
    rewriting or deleting the file while the server runs).
    """

    def __init__(self, name: str, digest: str, doc: pymupdf.Document) -> None:
        self.name = name  # file name it was first opened under (for messages)
        self.digest = digest
        self.doc = doc
        self._glyphs: dict[int, list] = {}
        self._segments: dict[tuple[str, int], list[Segment]] = {}
        self.artworks: dict[int, Artwork] = {}  # page -> parsed Artwork, filled by reader.read_artwork
        self.renders: dict[tuple, tuple] = {}  # PNG renders, filled by render.py

    @classmethod
    def open(cls, path: str | Path) -> "PdfFile":
        path = Path(path)
        if not path.exists():
            raise ArtworkError(f"Artwork file not found: {path.name}")
        digest = content_digest(path)
        with _OPEN_LOCK:
            if digest in _OPEN:
                _OPEN.move_to_end(digest)
                return _OPEN[digest]
        pdf = cls(path.name, digest, _open_document(path))
        with _OPEN_LOCK:
            _OPEN[digest] = pdf
            while len(_OPEN) > MAX_OPEN_DOCUMENTS:
                _OPEN.popitem(last=False)  # least recently used
        return pdf

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


MAX_OPEN_DOCUMENTS = 8
_OPEN: OrderedDict[str, PdfFile] = OrderedDict()  # content digest -> open document, least recently used first
_OPEN_LOCK = threading.Lock()


def clear_open_documents() -> None:
    """Forget every open document (for measurements and tests)."""
    with _OPEN_LOCK:
        _OPEN.clear()


def _open_document(path: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
    except Exception as exc:  # pymupdf raises several internal types
        # the library message contains server paths: keep it on the exception chain, not in the reply
        raise ArtworkError(f"Could not open {path.name}: the file is damaged or not a PDF.") from exc
    if doc.needs_pass:  # its text cannot be read without the password
        raise ArtworkError(f"{path.name} is password-protected. Export it again without a password and upload that.")
    return doc


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
ASSUMED_SCAN_DPI = 300  # photos and many scans carry no real resolution (often a nominal 72 or 96)
# 50 MP: a 48 MP phone photo or an A3 page at 500 dpi. A small file can claim a huge size (a
# "decompression bomb": 88 KB of PNG for 400 MP), so the size is checked before decoding.
MAX_IMAGE_PIXELS = 50_000_000


def image_to_pdf(data: bytes, name: str) -> bytes:
    """A one-page PDF holding a photo or scan of artwork, so it goes through the same reader (by OCR).

    The image is turned upright from its camera orientation tag, and the page is sized from the
    image's own resolution when that is a real scan resolution, else from 300 dpi."""
    from PIL import Image, ImageOps, UnidentifiedImageError  # Pillow is already a dependency

    try:
        image = Image.open(io.BytesIO(data))  # reads the header only
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ArtworkError(f"{name} is {image.width} x {image.height} pixels, more than this checker reads "
                               f"({MAX_IMAGE_PIXELS // 1_000_000} megapixels). Scan or export it at 300 dpi and upload that.")
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Image.DecompressionBombError as exc:
        raise ArtworkError(f"{name} claims an image size too large to open safely. "
                           "Scan or export it at 300 dpi and upload that.") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ArtworkError(f"Could not open {name} as an image.") from exc
    dpi = float((image.info.get("dpi") or (0, 0))[0] or 0)
    dpi = dpi if 150 <= dpi <= 2400 else ASSUMED_SCAN_DPI
    png = io.BytesIO()
    image.save(png, format="PNG")
    with PDF_LOCK:
        doc = pymupdf.open()
        page = doc.new_page(width=image.width * 72 / dpi, height=image.height * 72 / dpi)
        page.insert_image(page.rect, stream=png.getvalue())
        return doc.tobytes(deflate=True)


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
