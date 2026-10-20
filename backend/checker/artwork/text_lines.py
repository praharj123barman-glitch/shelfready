"""Turning PDF glyphs into clean text lines.

Design tools export text in ways that break matching: letter-spaced headings
come out as "H I G H", curved headlines as one glyph per line, and strokes or
shadows as duplicate copies. ``TextAssembler`` repairs all three.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, replace

from ..models import BBox
from .pdf_file import to_bbox


def squash(text: str) -> str:
    """Lowercase with all whitespace removed, for spacing-insensitive comparison."""
    return re.sub(r"\s+", "", text).lower()


@dataclass(frozen=True)
class RawLine:
    """One line of text as found in the PDF, before panels and roles are known."""

    text: str
    bbox: tuple[float, float, float, float]
    size: float
    font: str
    confidence: float = 1.0  # live text is exact; OCR lines carry the recogniser's score

    @property
    def box(self) -> BBox:
        return to_bbox(self.bbox)

    @property
    def identity(self) -> tuple:
        """Same text at the same spot: a stroke or shadow copy of this line."""
        return self.text, tuple(round(v) for v in self.bbox)


class TextAssembler:
    """``raw``: one RawLine per PDF line, letter spacing repaired.
    ``lines``: the same with curved text joined and duplicate copies removed."""

    def __init__(self, blocks: list[dict]) -> None:
        self.raw = [line for block in blocks if block.get("type") == 0 for line in self._block_lines(block)]
        self.lines = self._dedupe(self._join_curved(self.raw))

    # ---------------- PDF lines ----------------

    @classmethod
    def _block_lines(cls, block: dict) -> list[RawLine]:
        out = []
        for line in block["lines"]:
            chars = [ch for span in line["spans"] for ch in span["chars"]]
            text = "".join(ch["c"] for ch in chars).strip()
            if not text:
                continue
            size = max(span["size"] for span in line["spans"])
            if cls._looks_letter_spaced(text):
                text = cls._rebuild_spacing(chars, size)
            text = re.sub(r"\s{2,}", " ", text)
            out.append(RawLine(text=text, bbox=tuple(line["bbox"]), size=size, font=line["spans"][0]["font"]))
        return out

    @staticmethod
    def _looks_letter_spaced(text: str) -> bool:
        tokens = text.split()
        if len(tokens) < 2:
            return False
        return sum(1 for t in tokens if len(t) == 1) / len(tokens) >= 0.5

    @staticmethod
    def _rebuild_spacing(chars: list[dict], size: float) -> str:
        """Rebuild words for letter-spaced text using real glyph gaps.

        Word gaps are wider than letter gaps, so cut words where the gap is
        clearly larger than the usual one.
        """
        glyphs = [c for c in chars if c["c"].strip()]
        if len(glyphs) < 3:
            return "".join(c["c"] for c in chars).strip()
        gaps = [glyphs[i + 1]["bbox"][0] - glyphs[i]["bbox"][2] for i in range(len(glyphs) - 1)]
        usual = statistics.median(gaps)
        out = glyphs[0]["c"]
        for gap, glyph in zip(gaps, glyphs[1:]):
            if gap > usual + 0.18 * size:
                out += " "
            out += glyph["c"]
        return out

    # ---------------- curved text ----------------

    @classmethod
    def _join_curved(cls, raw: list[RawLine]) -> list[RawLine]:
        """Join runs of single glyphs with the same font and size (text set on a curve) into one line."""
        out: list[RawLine] = []
        run: list[RawLine] = []
        seen_in_run: set[tuple] = set()

        def flush() -> None:
            out.extend(run if len(run) < 3 else [cls._joined(run)])
            run.clear()
            seen_in_run.clear()

        for line in raw:
            if len(line.text.strip()) != 1:
                flush()
                out.append(line)
                continue
            continues_run = run and line.font == run[-1].font and abs(line.size - run[-1].size) < 0.3
            # a glyph already in this run means a stroke/shadow copy started over
            if not continues_run or line.identity in seen_in_run:
                flush()
            run.append(line)
            seen_in_run.add(line.identity)
        flush()
        return out

    @staticmethod
    def _joined(run: list[RawLine]) -> RawLine:
        """One line from a run of glyphs, with a space where the gap between glyph centres is clearly larger than usual."""
        centres = [((r.bbox[0] + r.bbox[2]) / 2, (r.bbox[1] + r.bbox[3]) / 2) for r in run]
        dists = [((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(centres, centres[1:])]
        usual = statistics.median(dists)
        text = run[0].text
        for dist, glyph in zip(dists, run[1:]):
            text += (" " if dist > usual * 1.45 else "") + glyph.text
        xs0, ys0, xs1, ys1 = zip(*(r.bbox for r in run))
        return replace(run[0], text=text, bbox=(min(xs0), min(ys0), max(xs1), max(ys1)))

    # ---------------- duplicates ----------------

    @staticmethod
    def _dedupe(raw: list[RawLine]) -> list[RawLine]:
        """Drop exact duplicates: stroke and shadow copies of the same text."""
        seen: set[tuple] = set()
        unique = []
        for line in raw:
            if line.identity not in seen:
                seen.add(line.identity)
                unique.append(line)
        return unique
