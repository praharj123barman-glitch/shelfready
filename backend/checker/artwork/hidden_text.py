"""Finding text that is in the file but covered by a shape drawn on top of it.

Hidden text is a classic artwork defect: an old claim left under a new panel
fill still sits in the PDF and can reappear on press. Text spans and vector
fills share one drawing sequence number (the paint order), so an opaque fill
with a higher number that fully contains a line was painted over it.
"""

from __future__ import annotations

from typing import NamedTuple

import pymupdf

from ..models import BBox
from .pdf_file import to_bbox
from .text_lines import squash


class PaintInfo(NamedTuple):
    seqno: int  # position in the paint order, -1 when no span matched
    hidden: bool  # an opaque fill painted later covers the line
    layer: str | None  # PDF layer (optional content group) the text is on


class HiddenTextDetector:
    def __init__(self, page: pymupdf.Page) -> None:
        self._spans = [
            (span["seqno"], to_bbox(span["bbox"]), squash("".join(chr(c[0]) for c in span["chars"])), span.get("layer"))
            for span in page.get_texttrace()
        ]
        self._opaque_fills = [
            (d["seqno"], to_bbox(d["rect"]))
            for d in page.get_drawings()
            if d.get("fill") is not None and (d.get("fill_opacity") or 1.0) >= 0.99
        ]

    def inspect(self, box: BBox, text: str) -> PaintInfo:
        """Paint order, hidden state and layer of the text line at `box`."""
        seqno, layer = self._own_span(box, text)
        if seqno < 0:
            return PaintInfo(-1, False, None)
        hidden = any(fill_seq > seqno and fill_box.contains(box, tol=0.5) for fill_seq, fill_box in self._opaque_fills)
        return PaintInfo(seqno, hidden, layer)

    def _own_span(self, box: BBox, text: str) -> tuple[int, str | None]:
        """The text span that is this line. Matched by position AND content,
        because different text can share a spot (that is exactly what hidden text looks like)."""
        own = squash(text)
        candidates = [
            (abs(len(t) - len(own)), seq, layer)
            for seq, span_box, t, layer in self._spans
            if len(t) >= min(3, len(own))  # one-letter spans would match anything
            and (t in own or own in t)
            # overlap, not centre-inside: one span can hold a whole paragraph
            and span_box.x0 < box.x1 and span_box.x1 > box.x0
            and span_box.y0 < box.y1 and span_box.y1 > box.y0
        ]
        if not candidates:
            # curved / tracked text: one glyph per span, all inside the line box
            candidates = [(0, seq, layer) for seq, span_box, t, layer in self._spans if t and box.contains(span_box, tol=1.0)]
        if not candidates:
            return -1, None
        # closest text match wins ("Carbohydrate" vs the "Total Carbohydrate" on top of it)
        _, seq, layer = min(candidates, key=lambda c: (c[0], c[1]))
        return seq, layer
