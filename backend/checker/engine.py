"""Run the deterministic checks and assemble the report.

``run_checks`` runs every registered check whose rules are loaded (see
checks/registry.py). ``Report.with_findings`` sorts the findings worst first
and recomputes the summary and the launch verdict; the pipeline calls it again
after adding AI findings and applying reviewer waivers.
"""

from __future__ import annotations

import logging
from collections import Counter

from pydantic import BaseModel

from .checks import REGISTRY
from .checks.base import CheckContext
from .content_sheet import ApprovedSpec
from .models import Artwork, Finding, Risk, Verdict
from .rules import RuleSet

log = logging.getLogger(__name__)

VERDICT_ORDER = {Verdict.DEFINITE: 0, Verdict.LIKELY: 1, Verdict.REVIEW: 2, Verdict.PASS: 3}
RISK_ORDER = {Risk.SAFETY: 0, Risk.LEGAL: 1, Risk.PRODUCTION: 2, Risk.DATA: 3, Risk.BRAND: 4}


class RiskRanker:
    """What happens if a finding ships, by its category, with a few per-check overrides."""

    BY_CATEGORY = {
        "allergens": Risk.SAFETY,
        "ingredients": Risk.SAFETY,  # an unapproved recipe change can hide an allergen (walnuts were added)
        "nutrition": Risk.LEGAL,
        "claims": Risk.LEGAL,
        "mandatory": Risk.LEGAL,
        "print_readiness": Risk.PRODUCTION,
        "source_data": Risk.DATA,
        "copy": Risk.BRAND,
        "ai_rules": Risk.BRAND,
    }
    BY_CHECK = {
        "text_allergen_information": Risk.SAFETY,
        "allergens_declared": Risk.SAFETY,
        "ingredient_structure": Risk.LEGAL,
        "vegan_ingredients": Risk.LEGAL,
    }

    @classmethod
    def rank(cls, finding: Finding) -> Finding:
        risk = cls.BY_CHECK.get(finding.check) or finding.risk or cls.BY_CATEGORY.get(finding.category, Risk.LEGAL)
        return finding.model_copy(update={"risk": risk})


class Report(BaseModel):
    artwork: str
    content_sheet: str | None
    rule_sources: list[str]
    findings: list[Finding]
    summary: dict[str, int]
    ready_to_launch: bool
    check_errors: list[str] = []
    waived: int = 0  # findings a reviewer waived as false alarms (still listed)

    def with_findings(self, findings: list[Finding]) -> "Report":
        """A copy with these findings, sorted worst first, and the counts and launch verdict recomputed."""
        # waived findings sink to the end of their verdict group and stop counting toward the verdict
        ranked = sorted(
            (RiskRanker.rank(f) for f in findings),
            key=lambda f: (VERDICT_ORDER[f.verdict], f.waiver is not None, RISK_ORDER[f.risk], f.category),
        )
        counts = Counter(f.verdict.value for f in ranked if f.waiver is None)
        return self.model_copy(update={
            "findings": ranked,
            "waived": sum(1 for f in ranked if f.waiver is not None),
            "summary": {v.value: counts.get(v.value, 0) for v in Verdict},
            # an errored check means we did not look, which is not the same as a pass
            "ready_to_launch": counts.get("definite", 0) == 0 and counts.get("likely", 0) == 0 and not self.check_errors,
        })


def run_checks(art: Artwork, rules: RuleSet, spec: ApprovedSpec | None) -> Report:
    """Run every check whose rules are loaded. A check that crashes is reported, not hidden."""
    ctx = CheckContext.build(art, rules, spec)
    findings: list[Finding] = []
    errors: list[str] = []
    for spec_ in REGISTRY.applicable(rules):
        try:
            findings.extend(spec_.run(ctx))
        except Exception as exc:  # one broken check must not hide the others' results
            log.exception("check %s failed", spec_.name)
            errors.append(f"{spec_.name}: {exc}")
    empty = Report(
        artwork=art.file_name, content_sheet=spec.file_name if spec else None,
        rule_sources=sorted({r.source_name for r in rules.rules}),
        findings=[], summary={}, ready_to_launch=False, check_errors=errors,
    )
    return empty.with_findings(findings)
