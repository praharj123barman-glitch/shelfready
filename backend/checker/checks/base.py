"""Shared context and helpers for deterministic checks.

Each check is a small function ``check(ctx) -> list[Finding]``. Checks never
raise for missing inputs: when something they need is absent (no content
sheet, no Nutrition Facts panel) they return a REVIEW finding saying so,
instead of silently passing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Callable

from ..content_sheet import ApprovedSpec
from ..models import Artwork, BBox, Evidence, Finding, TextLine, Verdict
from ..nutrition import NutritionPanel, read_nutrition_panel
from ..rules import RuleSet
from ..sections import Block, find_blocks


@dataclass
class CheckContext:
    art: Artwork
    rules: RuleSet
    spec: ApprovedSpec | None = None
    blocks: dict[str, Block] = field(default_factory=dict)
    nf: NutritionPanel | None = None
    _ids: count = field(default_factory=lambda: count(1))

    @classmethod
    def build(cls, art: Artwork, rules: RuleSet, spec: ApprovedSpec | None) -> "CheckContext":
        return cls(art=art, rules=rules, spec=spec, blocks=find_blocks(art), nf=read_nutrition_panel(art))

    def line(self, line_id: str | None) -> TextLine | None:
        return next((ln for ln in self.art.lines if ln.id == line_id), None) if line_id else None

    def finding(
        self,
        check: str,
        category: str,
        verdict: Verdict,
        title: str,
        explanation: str,
        rule_id: str | None = None,
        **kwargs,
    ) -> Finding:
        rule = self.rules.get(rule_id) if rule_id else None
        return Finding(
            id=f"F{next(self._ids):03d}",
            check=check,
            category=category,
            verdict=verdict,
            title=title,
            explanation=explanation,
            rule_id=rule_id,
            rule_text=rule.text if rule else None,
            **kwargs,
        )


Check = Callable[[CheckContext], list[Finding]]


def union_bbox(lines: list[TextLine]) -> BBox | None:
    if not lines:
        return None
    return BBox(
        x0=min(l.bbox.x0 for l in lines),
        y0=min(l.bbox.y0 for l in lines),
        x1=max(l.bbox.x1 for l in lines),
        y1=max(l.bbox.y1 for l in lines),
    )


def art_evidence(lines: list[TextLine | None], text: str | None = None) -> Evidence:
    lines = [l for l in lines if l is not None]
    return Evidence(
        source="artwork",
        text=text if text is not None else " / ".join(l.text for l in lines),
        panel=lines[0].panel if lines else None,
        bbox=union_bbox(lines),
        line_ids=[l.id for l in lines],
    )


def block_evidence(block: Block, text: str | None = None) -> Evidence:
    return Evidence(
        source="artwork", text=text or block.text, panel=block.panel, bbox=block.bbox, line_ids=[l.id for l in block.lines]
    )


def sheet_evidence(spec: ApprovedSpec, key: str) -> Evidence | None:
    f = spec.get(key)
    if not f:
        return None
    return Evidence(source="content_sheet", text=f.value, cell=f.cell)


def computed(text: str) -> Evidence:
    return Evidence(source="computed", text=text)


def fmt(x: float) -> str:
    return f"{x:g}"
