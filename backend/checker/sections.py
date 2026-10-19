"""Turn positioned artwork lines into readable blocks (ingredients, allergens...).

Justified copy is exported as many small line fragments ("Organic" ...
"Wholegrain" ... "Oat"), so we rebuild reading order: group fragments into
rows by vertical position, then read rows top to bottom, left to right.
"""

from __future__ import annotations

import re

from .models import Artwork, BBox, TextLine

# headings that start a labelled block on the back panel
HEADINGS = ["INGREDIENTS:", "ALLERGEN INFORMATION:", "DIETARY INFORMATION:"]


class Block:
    def __init__(self, name: str, text: str, lines: list[TextLine]):
        self.name = name
        self.text = text
        self.lines = lines

    @property
    def bbox(self) -> BBox:
        return BBox(
            x0=min(ln.bbox.x0 for ln in self.lines),
            y0=min(ln.bbox.y0 for ln in self.lines),
            x1=max(ln.bbox.x1 for ln in self.lines),
            y1=max(ln.bbox.y1 for ln in self.lines),
        )

    @property
    def panel(self) -> str:
        return self.lines[0].panel


def reading_order(lines: list[TextLine]) -> list[TextLine]:
    rows: list[list[TextLine]] = []
    for ln in sorted(lines, key=lambda l: l.bbox.cy):
        if rows and abs(rows[-1][0].bbox.cy - ln.bbox.cy) < 0.5 * ln.size:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    return [ln for row in rows for ln in sorted(row, key=lambda l: l.bbox.x0)]


def join_text(lines: list[TextLine]) -> str:
    text = " ".join(ln.text for ln in reading_order(lines))
    return re.sub(r"\s+", " ", text).strip()


def _column_lines(art: Artwork, start: TextLine) -> list[TextLine]:
    """Copy in the same text column and font size as the heading, below it."""
    return [
        ln
        for ln in art.copy_lines(start.panel)
        if abs(ln.size - start.size) < 0.3 and ln.bbox.x0 >= start.bbox.x0 - 3 and ln.bbox.y0 >= start.bbox.y0 - 1
    ]


def find_blocks(art: Artwork) -> dict[str, Block]:
    """Split the labelled copy column into named blocks by heading."""
    blocks: dict[str, Block] = {}
    for start in art.copy_lines():
        if not start.text.upper().startswith("INGREDIENTS:"):
            continue
        ordered = reading_order(_column_lines(art, start))
        current: str | None = None
        grouped: dict[str, list[TextLine]] = {}
        prev_bottom = start.bbox.y0
        for ln in ordered:
            heading = next((h for h in HEADINGS if ln.text.upper().startswith(h)), None)
            if heading:
                current = heading.rstrip(":").lower().replace(" ", "_")
            elif ln.bbox.y0 - prev_bottom > 3 * ln.size:
                current = None  # a big gap ends the labelled block
            if current:
                grouped.setdefault(current, []).append(ln)
                prev_bottom = max(prev_bottom, ln.bbox.y1)
        for name, lns in grouped.items():
            blocks[name] = Block(name, join_text(lns), lns)
        break
    return blocks


def find_line(art: Artwork, pattern: str, panel: str | None = None, include_hidden: bool = False) -> TextLine | None:
    rx = re.compile(pattern, re.I)
    return next((ln for ln in art.copy_lines(panel, include_hidden) if rx.search(ln.text)), None)


def find_lines(art: Artwork, pattern: str, panel: str | None = None) -> list[TextLine]:
    rx = re.compile(pattern, re.I)
    return [ln for ln in art.copy_lines(panel) if rx.search(ln.text)]


def nearby_text(art: Artwork, anchor: TextLine, radius: float = 40) -> list[TextLine]:
    """Copy lines close to an anchor: badge words, a stacked claim, a panel row."""
    return [
        ln
        for ln in art.copy_lines(anchor.panel)
        if abs(ln.bbox.cx - anchor.bbox.cx) < radius and abs(ln.bbox.cy - anchor.bbox.cy) < radius
    ]


def split_ingredients(text: str) -> list[str]:
    """Split an ingredient statement on top-level commas (not inside brackets)."""
    body = re.sub(r"^\s*ingredients\s*:\s*", "", text, flags=re.I).strip().rstrip(".")
    items, depth, cur = [], 0, ""
    for ch in body:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        items.append(cur.strip())
    # "Himalayan Pink Salt. Natural Flavoring" ends with a sentence break, not a comma
    out: list[str] = []
    for it in items:
        out.extend(p.strip() for p in re.split(r"\.\s+(?=[A-Z])", it) if p.strip())
    return out
