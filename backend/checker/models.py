"""Shared data model for the artwork checker.

A finding always carries evidence (where on the artwork / in the source data
it came from) and the rule it was judged against, so the user can verify it.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    PASS = "pass"  # checked and correct
    DEFINITE = "definite"  # proven wrong (math, missing text, exact mismatch)
    LIKELY = "likely"  # rule interpretation says wrong, a human should confirm
    REVIEW = "review"  # cannot decide automatically, needs a human


class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def contains(self, other: "BBox", tol: float = 1.0) -> bool:
        return (
            self.x0 - tol <= other.x0
            and self.y0 - tol <= other.y0
            and self.x1 + tol >= other.x1
            and self.y1 + tol >= other.y1
        )


class TextLine(BaseModel):
    """One visual line of text read straight from the artwork PDF."""

    id: str
    text: str
    bbox: BBox
    size: float
    font: str
    panel: str
    role: Literal["copy", "guide"] = "copy"  # guide = dieline print marks
    hidden: bool = False  # covered by an opaque shape drawn on top
    seqno: int = -1
    layer: str | None = None  # PDF optional content group, e.g. "DESIGN"


class Evidence(BaseModel):
    source: Literal["artwork", "content_sheet", "rulebook", "computed"]
    text: str
    panel: str | None = None
    bbox: BBox | None = None
    line_ids: list[str] = Field(default_factory=list)
    cell: str | None = None  # spreadsheet cell, e.g. "B26"
    note: str | None = None  # how to read this evidence, e.g. why the crop shows something else


class Risk(str, Enum):
    """What happens if this ships, independent of how sure we are (the verdict)."""

    SAFETY = "safety"  # could harm a shopper: allergens, undeclared ingredients
    LEGAL = "legal"  # misbranding: mandatory information, claims, nutrition
    PRODUCTION = "production"  # print and conversion: folds, hidden objects, type size
    DATA = "data"  # the approved source data itself is wrong
    BRAND = "brand"  # approved copy, taglines, retailer style


class Finding(BaseModel):
    id: str
    check: str  # machine name of the check that produced it
    category: str  # nutrition, claims, allergens, ingredients, net_quantity, ...
    verdict: Verdict
    risk: Risk | None = None  # filled in by the engine from the check or category
    title: str
    explanation: str  # why it matters, in plain language
    rule_id: str | None = None
    rule_text: str | None = None
    expected: str | None = None
    found: str | None = None
    fix: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    # row-level breakdown for grouped findings, e.g. one row per wrong %DV
    details: list[dict] = Field(default_factory=list)
    method: Literal["deterministic", "ai"] = "deterministic"
    confidence: float = 1.0
    waiver: dict | None = None  # set when a reviewer marked this exact problem a false alarm


class Artwork(BaseModel):
    file_name: str
    path: str | None = None  # local file, used to render panel images for the AI
    width: float
    height: float
    panels: dict[str, BBox]
    # panels that carry any design artwork (text or graphics); empty flaps are skipped
    content_panels: list[str] = Field(default_factory=list)
    lines: list[TextLine]
    barcodes: list[dict] = Field(default_factory=list)

    def copy_lines(self, panel: str | None = None, include_hidden: bool = False) -> list[TextLine]:
        return [
            ln
            for ln in self.lines
            if ln.role == "copy"
            and (include_hidden or not ln.hidden)
            and (panel is None or ln.panel == panel)
        ]

    def panel_text(self, panel: str) -> str:
        return "\n".join(ln.text for ln in self.copy_lines(panel))

    def full_text(self) -> str:
        return "\n".join(ln.text for ln in self.copy_lines())
