"""Run every deterministic check and collect findings into one report."""

from __future__ import annotations

import logging
from collections import Counter

from pydantic import BaseModel

from .checks import claims_checks, label_checks, match_checks, nutrition_checks
from .checks.base import CheckContext
from .content_sheet import ApprovedSpec
from .models import Artwork, Finding, Verdict
from .rules import RuleSet

log = logging.getLogger(__name__)

ALL_CHECKS = nutrition_checks.CHECKS + label_checks.CHECKS + claims_checks.CHECKS + match_checks.CHECKS
VERDICT_ORDER = {Verdict.DEFINITE: 0, Verdict.LIKELY: 1, Verdict.REVIEW: 2, Verdict.PASS: 3}


class Report(BaseModel):
    artwork: str
    content_sheet: str | None
    rule_sources: list[str]
    findings: list[Finding]
    summary: dict[str, int]
    ready_to_launch: bool
    check_errors: list[str] = []


def run_checks(art: Artwork, rules: RuleSet, spec: ApprovedSpec | None) -> Report:
    ctx = CheckContext.build(art, rules, spec)
    findings: list[Finding] = []
    errors: list[str] = []
    for check in ALL_CHECKS:
        try:
            findings.extend(check(ctx))
        except Exception as exc:  # one broken check must not hide the others' results
            log.exception("check %s failed", check.__name__)
            errors.append(f"{check.__name__}: {exc}")
    findings.sort(key=lambda f: (VERDICT_ORDER[f.verdict], f.category))
    summary = Counter(f.verdict.value for f in findings)
    return Report(
        artwork=art.file_name,
        content_sheet=spec.file_name if spec else None,
        rule_sources=sorted({r.source_name for r in rules.rules}),
        findings=findings,
        summary={v.value: summary.get(v.value, 0) for v in Verdict},
        # an errored check means we did not look, which is not the same as a pass
        ready_to_launch=summary.get("definite", 0) == 0 and summary.get("likely", 0) == 0 and not errors,
        check_errors=errors,
    )
