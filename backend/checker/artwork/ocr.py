"""Reading text from artwork that has no live text: scans, photos, outlined type.

When a page has no live text, ``ocr_lines`` renders it and reads it with RapidOCR
(PP-OCR models run locally with onnxruntime; nothing leaves the machine). It
returns the same ``RawLine`` objects the live-text reader makes, so panels,
sections and every check work unchanged.

OCR can misread a character, so the pipeline never calls a problem found in OCR
text Definite (see ``pipeline.py``). The only corrections made here are safe
ones: a letter O, l or I touching digits is a zero or a one ("Og" -> "0g").

Two passes: the page as it is, then turned a quarter turn so text set sideways
on side panels is read too. A sideways line only counts if it is wide in the
turned image (so it really was vertical) and no upright line already covers it.
"""

from __future__ import annotations

import re
import threading

import numpy as np
import pymupdf

from .text_lines import RawLine

OCR_DPI = 300  # 6 pt type is about 25 px tall at 300 dpi: enough for the recogniser
MAX_SIDE_PX = 7000  # very large pages are read at a lower resolution to bound memory
MIN_SCORE = 0.5  # lines the recogniser is less sure of are dropped
# font size / OCR box height, measured on the Esko sample (median of 71 lines matched to their live text)
SIZE_PER_BOX_HEIGHT = 0.66
FONT = "OCR"

_engine = None
_engine_lock = threading.Lock()  # creating the engine
_run_lock = threading.Lock()  # running it


def ocr_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_lines(page: pymupdf.Page) -> list[RawLine]:
    """Every readable line on the page, in points, upright lines first in reading order."""
    dpi = min(OCR_DPI, MAX_SIDE_PX * 72 / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    scale = 72 / dpi
    upright = _read(image, lambda x, y: (x * scale, y * scale), keep_tall=True)
    # np.rot90 turns a quarter anticlockwise: a point (x', y') in the turned image is (W - 1 - y', x') here
    width = image.shape[1]
    sideways = _read(np.ascontiguousarray(np.rot90(image)), lambda x, y: ((width - 1 - y) * scale, x * scale), keep_tall=False)
    return upright + [line for line in sideways if not any(_overlaps(line.bbox, u.bbox) for u in upright)]


def _engine_instance():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr import RapidOCR

            # the detector works on a downscaled copy (RapidOCR's default 2000 px) and the recogniser on
            # full-resolution crops: on the Esko sample that reads 97% of the words in about 5 s, while
            # detecting at full size took five times longer for no gain
            _engine = RapidOCR(params={"Global.log_level": "warning"})
        return _engine


def _read(image: np.ndarray, to_page, keep_tall: bool) -> list[RawLine]:
    """OCR one image. ``to_page`` maps an image pixel to page points.
    ``keep_tall``: keep lines taller than wide (False for the turned pass: those were horizontal text)."""
    engine = _engine_instance()
    with _run_lock:  # one recogniser, used by one thread at a time
        result = engine(image)
    lines = []
    for box, text, score in zip(result.boxes if result.boxes is not None else [], result.txts or (), result.scores or ()):
        text = fix_digits(re.sub(r"\s{2,}", " ", text).strip())
        if score < MIN_SCORE or not text:
            continue
        w_px, h_px = box[:, 0].max() - box[:, 0].min(), box[:, 1].max() - box[:, 1].min()
        if not keep_tall and (w_px < 1.5 * h_px or len(text) < 2):
            continue
        points = [to_page(float(x), float(y)) for x, y in box]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        height = min(w_px, h_px) * (max(xs) - min(xs) + max(ys) - min(ys)) / (w_px + h_px)  # across the text, in points
        lines.append(RawLine(text=text, bbox=(min(xs), min(ys), max(xs), max(ys)),
                             size=round(height * SIZE_PER_BOX_HEIGHT, 1), font=FONT, confidence=round(float(score), 2)))
    return lines


UNIT_AFTER_ZERO = re.compile(r"^[Oo](?=(?:g|mg|mcg|µg|kcal|kj|kJ|%)$)")


def fix_digits(text: str) -> str:
    """Letters OCR confuses with digits, corrected only where they touch digits or a unit: 'Og' -> '0g',
    '1O%' -> '10%', and a percent sign read before its number: '%8' -> '8%'."""
    tokens = []
    for token in text.split(" "):
        token = UNIT_AFTER_ZERO.sub("0", token)
        token = re.sub(r"^%(\d+(?:\.\d+)?)$", r"\1%", token)  # '%8': the sign read before the number
        if any(c.isdigit() for c in token):
            token = re.sub(r"(?<=\d)[Oo]|[Oo](?=\d)", "0", token)
            token = re.sub(r"(?<=\d)[lI|]|[lI|](?=\d)", "1", token)
        tokens.append(token)
    return " ".join(tokens)


def _overlaps(a: tuple, b: tuple) -> bool:
    """True when the smaller box lies mostly inside the larger one."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return smaller > 0 and ix * iy / smaller > 0.3
