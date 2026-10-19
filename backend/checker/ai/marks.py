"""Find logos and certification marks in the panel images.

Marks such as USDA Organic or Certified Vegan are drawn as graphics, so text
extraction cannot see them. The model only reports what it sees; the
judgement (is this mark approved, does the recipe allow it) is done in code.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..checks.base import CheckContext
from ..checks.claims_checks import ANIMAL_WORDS, _ingredients
from ..models import Evidence, Finding, Verdict
from .client import AIError, generate_json
from .rule_checker import panel_images

SYSTEM = """You inventory the logos, certification marks and symbols printed on a carton.
You get one image per panel. List every distinct mark you can see: certification seals (organic, vegan,
non-GMO, kosher, gluten free, Jaivik Bharat), regulatory logos (FSSAI logo; the Indian vegetarian symbol, a green
filled circle in a green square; the non-vegetarian symbol, a brown triangle in a brown square), recycling
symbols, brand logos, barcodes and badges.
Report only what is visible. Read the words printed inside each mark exactly; if they are too small to read
with certainty, leave words_in_mark empty rather than guessing. Do not report marks that are not there."""

KNOWN_MARKS = {
    "usda organic": r"usda\s*organic",
    "certified vegan": r"certified\s*vegan|vegan\.org",
    "recyclable": r"recycl",
    "non-gmo": r"non[\s-]*gmo",
    "veg symbol": r"\b(non[\s-]*)?veg(etarian)?\b.*\b(symbol|mark|logo)\b|\b(green|brown)\b.*\b(dot|circle|triangle)\b",
    "fssai logo": r"fssai",
    "jaivik bharat": r"jaivik|india\s*organic",
}
# India marks the FSSAI pack requires; each maps to the rule that requires it
INDIA_REQUIRED = {
    "veg symbol": ("FSSAI-VEG-MARK", "Vegetarian or non-vegetarian symbol not found",
                   "Indian packaged food must show the green (veg) or brown (non-veg) symbol on the front panel near the name."),
    "fssai logo": ("FSSAI-LICENSE", "FSSAI logo not found",
                   "The FSSAI logo must appear on the label together with the licence number."),
}


class Mark(BaseModel):
    name: str = Field(description="what the mark is, e.g. 'USDA Organic seal'")
    words_in_mark: str = Field(description="exact words printed inside the mark, '' if none")
    panel: str = Field(description="exact panel name from the IMAGE caption the mark is in")
    kind: Literal["certification", "recycling", "brand_logo", "barcode", "badge", "other"]


class MarkInventory(BaseModel):
    marks: list[Mark]


def inventory(ctx: CheckContext) -> list[Mark]:
    images = panel_images(ctx)
    if not images:
        raise AIError("No panel images available for this artwork")
    marks = generate_json(["List every mark on these carton panels.", *images], MarkInventory, SYSTEM).marks
    return [m for m in marks if m.panel in ctx.art.panels]  # drop marks placed on a panel that does not exist


def _canonical(mark: Mark) -> str | None:
    text = f"{mark.name} {mark.words_in_mark}".lower()
    return next((k for k, rx in KNOWN_MARKS.items() if re.search(rx, text)), None)


def check_marks(ctx: CheckContext) -> list[Finding]:
    try:
        marks = inventory(ctx)
    except AIError as exc:
        return [ctx.finding("marks_inventory", "claims", Verdict.REVIEW, "Certification marks could not be checked",
                            f"The image check failed ({str(exc)[:160]}). Check logos and seals by eye.", method="ai", confidence=0.0)]
    approved = (ctx.spec.value("front_back_panel_claims_certifications") or "").lower() if ctx.spec else ""
    findings: list[Finding] = []
    certs = [m for m in marks if m.kind in {"certification", "recycling"}]
    seen = ", ".join(f"{m.name} ({m.panel})" for m in certs) or "none"
    findings.append(ctx.finding(
        "marks_inventory", "claims", Verdict.PASS, f"{len(certs)} certification or recycling mark(s) found in the images",
        f"Seen: {seen}.", method="ai", confidence=0.6,
        evidence=[Evidence(source="artwork", text=f"Seen in image: {m.name} '{m.words_in_mark}'", panel=m.panel,
                           bbox=ctx.art.panels.get(m.panel)) for m in certs],
    ))
    animal = [i for i in _ingredients(ctx) if re.search(ANIMAL_WORDS, i, re.I)]
    for m in certs:
        key = _canonical(m)
        ev = [Evidence(source="artwork", text=f"Seen in image: {m.name} '{m.words_in_mark}'", panel=m.panel, bbox=ctx.art.panels.get(m.panel))]
        if key == "certified vegan" and animal:
            findings.append(ctx.finding(
                "vegan_mark", "claims", Verdict.LIKELY, f"Certified Vegan mark on the {m.panel} panel, but the recipe has {', '.join(animal)}",
                "The image check found the Certified Vegan seal. Code then found an animal-derived ingredient, so the seal "
                "cannot be used with this recipe. (The seal itself was identified by AI, so a human should confirm it.)",
                rule_id="DF-03", method="ai", confidence=0.7, evidence=ev,
            ))
        if key and key in {"usda organic", "certified vegan", "recyclable", "non-gmo"} and approved and not re.search(KNOWN_MARKS[key], approved):
            findings.append(ctx.finding(
                "mark_not_approved", "claims", Verdict.LIKELY, f"'{m.name}' is not on the approved claims list",
                "Every certification mark must be listed in the approved claims field of the content sheet.",
                rule_id="DF-04", method="ai", confidence=0.6, evidence=ev,
            ))
    findings += _india_required_marks(ctx, marks)
    return findings


def _india_required_marks(ctx: CheckContext, marks: list[Mark]) -> list[Finding]:
    """Marks a market requires but the images do not show. Absence in an image
    cannot be verified in code, so these stay LIKELY with low confidence."""
    found = {_canonical(m) for m in marks}
    out = []
    for key, (rule_id, title, why) in INDIA_REQUIRED.items():
        if not ctx.rules.get(rule_id) or key in found:
            continue
        out.append(ctx.finding(
            f"mark_missing_{key.replace(' ', '_')}", "mandatory", Verdict.LIKELY, title,
            why + " It was not seen in any panel image. (Judged by AI from the images; please confirm.)",
            rule_id=rule_id, method="ai", confidence=0.55,
            evidence=[Evidence(source="computed", text=f"Not seen in: {', '.join(ctx.art.content_panels)}")],
        ))
    return out
