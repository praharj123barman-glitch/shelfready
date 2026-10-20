"""Turn positioned artwork lines into readable blocks (ingredients, allergens...).

Justified copy is exported as many small line fragments ("Organic" ...
"Wholegrain" ... "Oat"), so we rebuild reading order: group fragments into
rows by vertical position, then read rows top to bottom, left to right.
"""

from __future__ import annotations

import re

from .artwork.ocr import FONT as OCR_FONT
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


def same_size(a: TextLine, b: TextLine) -> bool:
    """Set in the same font size. Live text sizes are exact; OCR sizes are estimated from box heights
    (see artwork/ocr.py), which vary by up to about a third between lines of one paragraph."""
    if a.font == OCR_FONT or b.font == OCR_FONT:
        return abs(a.size - b.size) < 0.35 * max(a.size, b.size)
    return abs(a.size - b.size) < 0.3


def _column_lines(art: Artwork, start: TextLine) -> list[TextLine]:
    """Copy in the same text column and font size as the heading, below it."""
    return [
        ln
        for ln in art.copy_lines(start.panel)
        if same_size(ln, start) and ln.bbox.x0 >= start.bbox.x0 - 3 and ln.bbox.y0 >= start.bbox.y0 - 1
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


QUANTITY = re.compile(r"^\s*(?:net\s*wt\.?\s*)?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>g|kg|oz|lb|ml|l|fl\.?\s*oz)\b", re.I)
NUTRIENT_WORDS = re.compile(r"\b(fat|saturates?|sugars?|salt|sodium|protein|fib(re|er)|carb\w*|calories|energy|kcal|kj)\b", re.I)


def net_quantity_lines(art: Artwork) -> list[TextLine]:
    """Lines that declare the pack's net quantity, best first.

    '3.8g' next to the word 'Fat' is a nutrient amount, not a net weight, so any
    quantity with nutrient words beside it is skipped. 'NET WT' lines and the
    front panel are preferred.
    """
    out = []
    for ln in art.copy_lines():
        text = ln.text.strip()
        if not QUANTITY.match(text) or len(text) > 30:
            continue
        neighbours = [o for o in art.copy_lines(ln.panel) if o.id != ln.id
                      and abs(o.bbox.cy - ln.bbox.cy) < 2.2 * ln.size and abs(o.bbox.cx - ln.bbox.cx) < 40]
        if NUTRIENT_WORDS.search(text) or any(NUTRIENT_WORDS.search(o.text) for o in neighbours):
            continue
        out.append(ln)
    return sorted(out, key=lambda l: ("net" not in l.text.lower(), l.panel != "front"))


BADGE_MIN_SIZE = 9.0  # pt: badge words are set large


def badge_texts(art: Artwork) -> list[tuple[str, list[TextLine]]]:
    """Stacked short uppercase words read as one badge: 'NO' 'ADDED' 'SUGAR' -> 'NO ADDED SUGAR'."""
    words = [ln for ln in art.copy_lines() if ln.size >= BADGE_MIN_SIZE and ln.text.isupper() and len(ln.text) <= 12]
    clusters: list[list[TextLine]] = []
    for ln in sorted(words, key=lambda l: (l.panel, l.bbox.cy)):
        for cluster in clusters:
            last = cluster[-1]
            if last.panel == ln.panel and abs(last.bbox.cx - ln.bbox.cx) < 25 and 0 <= ln.bbox.cy - last.bbox.cy < 1.6 * ln.size:
                cluster.append(ln)
                break
        else:
            clusters.append([ln])
    return [(" ".join(l.text for l in cluster), cluster) for cluster in clusters if len(cluster) >= 2]


def may_contain_items(text: str) -> list[str]:
    """'May contain almonds, may contain brazil nuts' -> ['almonds', 'brazil nuts']."""
    return [m.strip(" ,.") for m in re.findall(r"may\s+contain\s+([^,]+?)(?=,|\s+or\s+|\.|$)", text, re.I)]


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
