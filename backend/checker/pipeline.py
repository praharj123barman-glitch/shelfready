"""A full review, step by step.

    pipeline = ReviewPipeline()
    result = pipeline.run(artwork_pdf, content_sheet_xlsx, [rule_files...], use_ai=True)

``run`` does, in order:

1. read the artwork, the approved content sheet and the rule files;
2. run every deterministic check whose rules are loaded;
3. if AI is on: judge the rules no code check covered, and inventory the marks;
4. apply the reviewer's earlier feedback (waivers);
5. report, with a coverage row for every rule and any notes (AI off, pages skipped).

Code checks always run first; AI only adds to them. If AI is unavailable the
review still completes, and the result says the AI part did not run.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from .ai.client import AIError, GeminiClient, default_client
from .ai.marks import MarkInspector
from .ai.rule_judge import RuleJudge, rules_without_code_checks
from .ai.rulebook_reader import RulebookReader
from .artwork import read_artwork
from .checks.base import CheckContext
from .content_sheet import ApprovedSpec, read_content_sheet
from .engine import Report, run_checks
from .feedback import FeedbackStore
from .models import Artwork, Finding
from .nutrition import CorrectedPanel, corrected_panel, read_nutrition_panel
from .rules import RuleSet, load_regulation_pack, load_rulebook

log = logging.getLogger(__name__)
RULES_DIR = Path(__file__).resolve().parents[2] / "rules"
DEFAULT_RULES = [RULES_DIR / "us_fda_food.json"]
VERDICT_SEVERITY = ["definite", "likely", "review", "pass"]


class RuleSource(BaseModel):
    name: str
    kind: str  # regulation | company | ai_extracted
    rule_count: int
    dropped: list[str] = []  # AI-extracted rules dropped because their quote was not in the document


class ReviewResult(BaseModel):
    report: Report
    rule_sources: list[RuleSource]
    coverage: list[dict]  # one row per rule: checked by code, AI, or not at all
    ai_ran: bool
    ai_note: str | None = None  # anything the reviewer should know about what was not checked
    ai_models: list[str] = []  # models that answered (cached answers say so)
    corrected_nutrition: CorrectedPanel | None = None  # US Nutrition Facts as the printed amounts require


class ReviewPipeline:
    def __init__(self, client: GeminiClient | None = None, feedback: FeedbackStore | None = None) -> None:
        self.client = client or default_client()
        self.feedback = feedback or FeedbackStore()

    def run(self, artwork_path: Path, sheet_path: Path | None, rule_paths: list[Path], use_ai: bool = True) -> ReviewResult:
        notes: list[str] = []
        art = read_artwork(artwork_path)
        spec = read_content_sheet(sheet_path) if sheet_path else None
        rules, sources = self._load_rules(rule_paths or DEFAULT_RULES, notes)

        report = run_checks(art, rules, spec)
        ai_ran = use_ai and self.client.available
        not_applicable: list[str] = []
        if ai_ran:
            report, not_applicable = self._add_ai_findings(report, art, rules, spec)
        else:
            notes.insert(0, "AI checks did not run (no GEMINI_API_KEY or AI switched off). Only code checks are shown.")
        report = report.with_findings(self.feedback.apply_waivers(report.findings, artwork_path))

        if art.page_count > 1:
            notes.append(f"only page 1 of {art.page_count} was checked; review the other pages separately")
        return ReviewResult(
            report=report, rule_sources=sources, coverage=coverage_table(rules, report.findings, not_applicable),
            ai_ran=ai_ran, ai_note="; ".join(notes) or None,
            ai_models=sorted(self.client.models_used) if ai_ran else [],
            corrected_nutrition=self._corrected_nutrition(art, rules),
        )

    # ---------------- steps ----------------

    def _load_rules(self, paths: list[Path], notes: list[str]) -> tuple[RuleSet, list[RuleSource]]:
        rules, sources = RuleSet(rules=[]), []
        for path in paths:
            try:
                loaded, source = self._load_rule_file(path)
            except AIError as exc:  # a prose rulebook needs AI to read it
                notes.append(f"could not read rules from {path.name}: {exc}")
                continue
            rules = rules.merged(loaded)
            sources.append(source)
        return rules, sources

    def _load_rule_file(self, path: Path) -> tuple[RuleSet, RuleSource]:
        """JSON packs and '### ID' rulebooks are parsed exactly; any other text is read by AI."""
        if path.suffix.lower() == ".json":
            pack = load_regulation_pack(path)
            name = pack.rules[0].source_name if pack.rules else path.stem
            return pack, RuleSource(name=name, kind="regulation", rule_count=len(pack.rules))
        book = load_rulebook(path)
        if book.rules:
            return book, RuleSource(name=book.rules[0].source_name, kind="company", rule_count=len(book.rules))
        id_prefix = "".join(c for c in path.stem.upper() if c.isalpha())[:3] or "U"
        rules, dropped = RulebookReader(self.client).read(path.read_text(encoding="utf-8", errors="replace"), path.stem, id_prefix)
        return RuleSet(rules=rules), RuleSource(name=path.stem, kind="ai_extracted", rule_count=len(rules), dropped=dropped)

    def _add_ai_findings(self, report: Report, art: Artwork, rules: RuleSet, spec: ApprovedSpec | None) -> tuple[Report, list[str]]:
        self.client.reset_usage()
        # the AI reads the rules with reviewer guidance from earlier false alarms appended;
        # numbering continues after the code findings so every finding id stays unique
        ctx = CheckContext.build(art, self.feedback.with_rule_notes(rules), spec, first_id=len(report.findings) + 1)
        judgement = RuleJudge(ctx, self.client).judge(rules_without_code_checks(ctx.rules.rules, report.findings))
        marks = MarkInspector(ctx, self.client).inspect()
        return report.with_findings(report.findings + judgement.findings + marks), judgement.not_applicable

    @staticmethod
    def _corrected_nutrition(art: Artwork, rules: RuleSet) -> CorrectedPanel | None:
        if not rules.get("FDA-101.9-DV"):  # a US Nutrition Facts panel only means something under US rules
            return None
        panel = read_nutrition_panel(art)
        return corrected_panel(panel) if panel else None


def coverage_table(rules: RuleSet, findings: list[Finding], not_applicable: list[str]) -> list[dict]:
    """For every rule: checked by code, by AI, or not at all, and its worst result."""
    rows = []
    for rule in rules.rules:
        hits = [f for f in findings if f.rule_id == rule.id]
        methods = {f.method for f in hits}
        checked_by = "code" if "deterministic" in methods else "ai" if "ai" in methods else "not checked"
        worst = min((f.verdict.value for f in hits), key=VERDICT_SEVERITY.index, default=None)
        if rule.id in not_applicable:
            checked_by, worst = "ai", "not_applicable"
        rows.append({"rule_id": rule.id, "title": rule.title, "source": rule.source_name, "checked_by": checked_by, "result": worst})
    return rows
