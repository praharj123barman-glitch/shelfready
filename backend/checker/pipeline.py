"""One call that runs a full review: read inputs, deterministic checks, then AI.

Order matters: code checks run first; the AI only gets the rules code did
not cover, plus the visual marks inventory. If AI is unavailable the report
still comes back, with a visible note that the AI part did not run.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from .ai.client import MODELS_USED, AIError, ai_available
from .ai.marks import check_marks
from .ai.rule_checker import check_rules, extract_rules, uncovered_rules
from .artwork import read_artwork
from .checks.base import CheckContext
from .content_sheet import read_content_sheet
from .engine import Report, finalize, run_checks
from .feedback import STORE as FEEDBACK_STORE
from .feedback import apply_waivers, with_rule_notes
from .models import Finding
from .rules import RuleSet, load_regulation_pack, load_rulebook

log = logging.getLogger(__name__)
RULES_DIR = Path(__file__).resolve().parents[2] / "rules"
DEFAULT_PACK = RULES_DIR / "us_fda_food.json"


class RuleSource(BaseModel):
    name: str
    kind: str  # regulation | company | ai_extracted
    rule_count: int
    dropped: list[str] = []  # AI-extracted rules dropped for failing the quote check


class ReviewResult(BaseModel):
    report: Report
    rule_sources: list[RuleSource]
    coverage: list[dict]
    ai_ran: bool
    ai_note: str | None = None
    ai_models: list[str] = []  # which models actually answered (cached answers say so)


def load_rule_file(path: Path) -> tuple[RuleSet, RuleSource]:
    """JSON packs and '### ID' rulebooks are parsed exactly; anything else goes to the AI extractor."""
    if path.suffix.lower() == ".json":
        rs = load_regulation_pack(path)
        return rs, RuleSource(name=rs.rules[0].source_name if rs.rules else path.stem, kind="regulation", rule_count=len(rs.rules))
    rs = load_rulebook(path)
    if rs.rules:
        return rs, RuleSource(name=rs.rules[0].source_name, kind="company", rule_count=len(rs.rules))
    text = path.read_text(encoding="utf-8", errors="replace")
    prefix = "".join(c for c in path.stem.upper() if c.isalpha())[:3] or "U"
    rules, dropped = extract_rules(text, path.stem, prefix=prefix)
    return RuleSet(rules=rules), RuleSource(name=path.stem, kind="ai_extracted", rule_count=len(rules), dropped=dropped)


def coverage_table(rules: RuleSet, findings: list[Finding], not_applicable: list[str]) -> list[dict]:
    """For every rule: was it checked by code, by AI, or not at all?"""
    rows = []
    for r in rules.rules:
        fs = [f for f in findings if f.rule_id == r.id]
        methods = {f.method for f in fs}
        how = "code" if "deterministic" in methods else "ai" if "ai" in methods else "not checked"
        worst = min((f.verdict.value for f in fs), key=lambda v: ["definite", "likely", "review", "pass"].index(v), default=None)
        if r.id in not_applicable:
            how, worst = "ai", "not_applicable"
        rows.append({"rule_id": r.id, "title": r.title, "source": r.source_name, "checked_by": how, "result": worst})
    return rows


def review(
    artwork_path: Path, sheet_path: Path | None, rule_paths: list[Path], use_ai: bool = True,
    feedback_store: Path = FEEDBACK_STORE,
) -> ReviewResult:
    art = read_artwork(artwork_path)
    spec = read_content_sheet(sheet_path) if sheet_path else None

    rules, sources = RuleSet(rules=[]), []
    ai_errors: list[str] = []
    for p in rule_paths or [DEFAULT_PACK]:
        try:
            rs, src = load_rule_file(p)
        except AIError as exc:
            ai_errors.append(f"could not read rules from {p.name}: {exc}")
            continue
        rules = rules.merged(rs)
        sources.append(src)

    report = run_checks(art, rules, spec)
    ai_ran = use_ai and ai_available()
    note, not_applicable = None, []
    if ai_ran:
        MODELS_USED.clear()
        # the AI reads rules with any reviewer guidance from earlier false alarms appended
        ctx = CheckContext.build(art, with_rule_notes(rules, feedback_store), spec, first_id=len(report.findings) + 1)
        rule_findings, not_applicable = check_rules(ctx, uncovered_rules(ctx.rules.rules, report.findings))
        report = finalize(report, report.findings + rule_findings + check_marks(ctx))
    else:
        note = "AI checks did not run (no GEMINI_API_KEY or AI switched off). Only code checks are shown."
    report = finalize(report, apply_waivers(report.findings, artwork_path, feedback_store))
    if ai_errors:
        note = "; ".join(filter(None, [note] + ai_errors))
    return ReviewResult(
        report=report, rule_sources=sources, coverage=coverage_table(rules, report.findings, not_applicable),
        ai_ran=ai_ran, ai_note=note, ai_models=sorted(MODELS_USED) if ai_ran else [],
    )
