"""Finding the carton's panels (front, back, sides, flaps) on a flat dieline.

Rules such as "net quantity on the principal display panel" only make sense
once we know which part of the flat sheet becomes which face of the box.
"""

from __future__ import annotations

import re
import statistics

import pymupdf

from ..models import BBox, TextLine
from .guides import is_structural_layer
from .pdf_file import PdfFile, to_bbox
from .text_lines import RawLine

FACE_LABEL = re.compile(r"(front|back|left|right) panel", re.I)  # dieline guide text such as "Front panel"
MIN_FACE_WIDTH = 60  # points: narrower crease columns are glue strips or tucks, not faces


class PanelFinder:
    """Splits the page into named panels.

    Uses the dieline fold lines when the file has them; otherwise the large
    filled panel shapes; a page with neither is a flat label, so the whole
    page is its front.
    """

    def __init__(self, pdf: PdfFile, page_no: int, guide_lines: list[tuple[str, BBox]], raw: list[RawLine]) -> None:
        self.pdf = pdf
        self.page_no = page_no
        self.page = pdf.page(page_no)
        self.guide_lines = guide_lines  # (text, box) of dieline labels, used for naming
        self.raw = raw  # all text, used to spot the front by its largest type

    def find(self) -> dict[str, BBox]:
        return self._from_creases() or self._from_fills()

    # ---------------- from fold lines ----------------

    def _from_creases(self) -> dict[str, BBox] | None:
        """Faces are the cells between fold lines: the long horizontal creases bound
        the body, the vertical creases split it into faces, and what lies above or
        below each face is that face's top or bottom flap."""
        creases = self.pdf.dieline_segments("crease", self.page_no)
        cuts = self.pdf.dieline_segments("cut", self.page_no)
        if not creases:
            return None
        width, height = self.page.rect.width, self.page.rect.height
        # a body fold may be drawn as one long line or as one segment per face,
        # so sum the horizontal crease length at each height
        length_at: dict[int, float] = {}
        for x0, y0, x1, y1 in creases:
            if abs(y0 - y1) < 1:
                length_at[round(y0)] = length_at.get(round(y0), 0) + abs(x1 - x0)
        folds = sorted(y for y, total in length_at.items() if total > width * 0.5)
        if len(folds) < 2:
            return None
        top, bottom = folds[0], folds[-1]
        xs = sorted({
            round(x0) for x0, y0, x1, y1 in creases + cuts
            if abs(x0 - x1) < 1 and min(y0, y1) <= top + 1 and max(y0, y1) >= bottom - 1
        })
        columns = [(a, b) for a, b in zip(xs, xs[1:]) if b - a > MIN_FACE_WIDTH]

        panels: dict[str, BBox] = {}
        for (x0, x1), name in zip(columns, self._name_columns(columns, top, bottom)):
            if not name:
                continue
            panels[name] = BBox(x0=x0, y0=top, x1=x1, y1=bottom)
            panels[f"{name} top flap"] = BBox(x0=x0, y0=0, x1=x1, y1=top)
            panels[f"{name} bottom flap"] = BBox(x0=x0, y0=bottom, x1=x1, y1=height)
        if not panels:
            return None
        first_face = min(p.x0 for p in panels.values())
        if first_face > 5:
            panels["glue flap"] = BBox(x0=0, y0=top, x1=first_face, y1=bottom)
        return panels

    def _name_columns(self, columns: list[tuple[float, float]], top: float, bottom: float) -> list[str | None]:
        """Name each body column. Guide labels ('Front panel') win; columns without
        one are named from geometry, because many dielines carry no such labels:
        the wide column with the largest type is the front, the other wide one the
        back, and narrow columns are the sides. The glue flap is too narrow to name."""
        names = [self._label_inside(x0, x1, top, bottom) for x0, x1 in columns]
        names = [n if n and names.count(n) == 1 else None for n in names]  # a label used twice is not trusted

        widths = [x1 - x0 for x0, x1 in columns]
        wide = max(widths) * 0.75 if widths else 0
        largest_type: dict[int, float] = {}
        for line in self.raw:
            cx, cy = (line.bbox[0] + line.bbox[2]) / 2, (line.bbox[1] + line.bbox[3]) / 2
            for i, (x0, x1) in enumerate(columns):
                if x0 <= cx <= x1 and top <= cy <= bottom:
                    largest_type[i] = max(largest_type.get(i, 0), line.size)

        unnamed_wide = sorted((i for i, n in enumerate(names) if n is None and widths[i] >= wide),
                              key=lambda i: -largest_type.get(i, 0))
        for i in unnamed_wide:
            names[i] = next((n for n in ("front", "back") if n not in names), None)
        for i, name in enumerate(names):
            if name is None and 0.3 * max(widths) < widths[i] < wide:
                names[i] = next((s for s in ("left", "right") if s not in names), None)
        return names

    def _label_inside(self, x0: float, x1: float, top: float, bottom: float) -> str | None:
        """'front' / 'back' / ... from a guide label inside this area, if there is one."""
        for text, box in self.guide_lines:
            match = FACE_LABEL.match(text.strip())
            if match and x0 <= box.cx <= x1 and top <= box.cy <= bottom:
                return match.group(1).lower()
        return None

    # ---------------- from filled shapes ----------------

    def _from_fills(self) -> dict[str, BBox]:
        """Panel faces drawn as big filled rectangles; their edges give the column
        grid, and each column is named from the guide label inside it."""
        page = self.page
        fills = [d["rect"] for d in page.get_drawings()
                 if d.get("fill") is not None and d["rect"].width > 150 and d["rect"].height > 150]
        tall = [r for r in fills if r.height > page.rect.height * 0.45]
        if not tall:
            # no dieline at all: a flat label, so the whole page is the principal display panel
            return {"front": to_bbox(page.rect)}
        top = min(r.y0 for r in tall)
        bottom = statistics.median(r.y1 for r in tall)
        xs = sorted({round(v) for r in fills for v in (r.x0, r.x1)})

        panels: dict[str, BBox] = {}
        for x0, x1 in ((a, b) for a, b in zip(xs, xs[1:]) if b - a > 120):
            name = self._label_inside(x0, x1, top, bottom)
            if name and name not in panels:
                panels[name] = BBox(x0=x0, y0=top, x1=x1, y1=bottom)
        panels["top"] = BBox(x0=0, y0=0, x1=page.rect.width, y1=top)
        panels["bottom"] = BBox(x0=0, y0=bottom, x1=page.rect.width, y1=page.rect.height)
        return panels


def panel_for(box: BBox, panels: dict[str, BBox]) -> str:
    """Panel containing the box centre; faces win over flaps on shared edges."""
    for name, panel in sorted(panels.items(), key=lambda kv: " " in kv[0]):  # flap names contain a space
        if panel.x0 <= box.cx <= panel.x1 and panel.y0 <= box.cy <= panel.y1:
            return name
    return "other"


def content_panels(page: pymupdf.Page, panels: dict[str, BBox], lines: list[TextLine]) -> list[str]:
    """Panels that carry design: faces always count; a flap counts when design-layer text or graphics sit inside it."""
    design = [
        to_bbox(d["rect"]) for d in page.get_drawings()
        if not is_structural_layer(d.get("layer")) and d["rect"].width < page.rect.width * 0.5
    ] + [to_bbox(img["bbox"]) for img in page.get_image_info()]
    out = []
    for name, panel in panels.items():
        has_text = any(line.panel == name and line.role == "copy" for line in lines)
        has_art = any(panel.x0 <= b.cx <= panel.x1 and panel.y0 <= b.cy <= panel.y1 for b in design)
        if " " not in name or has_text or has_art:
            out.append(name)
    return out
