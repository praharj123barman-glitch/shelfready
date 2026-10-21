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

Speed: rule files (which may need an AI call) load while the PDF is read, and
the two AI steps (rule judging, mark inventory) run side by side. They are
independent: both only read the context, and the panel images are rendered
once, with the code checks, before they start.

Every PyMuPDF step goes through ``self.pdf`` (see pdf_work.py): in this
process by default, or in a worker process when the API passes one.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel

from .ai.client import AIError, GeminiClient, default_client
from .ai.injection import instruction_lines
from .ai.marks import MarkInspector
from .ai.prompt_material import PromptMaterial
from .ai.rule_judge import RuleJudge, rules_without_code_checks
from .ai.rulebook_reader import RulebookReader
from .checks.base import CheckContext
from .content_sheet import ApprovedSpec
from .engine import Report
from .feedback import FeedbackStore
from .models import Artwork, Finding, Verdict
from .nutrition import CorrectedPanel, corrected_panel, read_nutrition_panel
from .pdf_work import InlinePdfWork, PdfWork
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
    timings: dict[str, float] = {}  # seconds per stage, measured on this run (wall clock)


class StageTimer:
    """Wall-clock seconds per named stage of one review."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.seconds[name] = round(time.perf_counter() - start, 2)


class ReviewPipeline:
    def __init__(self, client: GeminiClient | None = None, feedback: FeedbackStore | None = None,
                 pdf: PdfWork | None = None) -> None:
        self.client = client or default_client()
        self.feedback = feedback or FeedbackStore()
        self.pdf = pdf or InlinePdfWork()

    def run(self, artwork_path: Path, sheet_path: Path | None, rule_paths: list[Path], use_ai: bool = True) -> ReviewResult:
        notes: list[str] = []
        timer = StageTimer()
        ai_ran = use_ai and self.client.available
        self.client.reset_usage()  # before the rule files: reading a prose rulebook is AI use too
        with timer.stage("total"):
            with timer.stage("read_inputs"), ThreadPoolExecutor(max_workers=1) as pool:
                # rule files may need an AI call (prose rulebooks); load them while the PDF is read
                loading_rules = pool.submit(self._load_rules, rule_paths or DEFAULT_RULES, notes, ai_ran)
                art, spec = self.pdf.read(artwork_path, sheet_path)
                rules, sources = loading_rules.result()

            checked = self.pdf.check(art, rules, spec, with_panels=ai_ran)
            timer.seconds.update(checked.seconds)
            report = checked.report
            if art.text_source != "live":  # read by OCR, ours or the scanner's
                report = report.with_findings([ocr_capped(f) for f in report.findings])
                notes.append(ocr_note(art))
            if spec is not None and (missing := spec.missing_fields()):
                notes.append(f"content sheet {spec.file_name}: found no {', '.join(missing)}, "
                             "so the checks against those approved values were skipped")
            not_applicable: list[str] = []
            if ai_ran:
                report, not_applicable = self._add_ai_findings(report, art, rules, spec, checked.crops, timer)
                if steering := instruction_lines(art):
                    report = report.with_findings([no_ai_pass(f) for f in report.findings])
                    notes.append(steering_note(steering))
            else:
                notes.insert(0, "AI checks did not run (no GEMINI_API_KEY or AI switched off). Only code checks are shown.")
            report = report.with_findings(self.feedback.apply_waivers(report.findings, artwork_path))

            if art.page_count > 1:
                notes.append(f"only page 1 of {art.page_count} was checked; review the other pages separately")
            corrected = self._corrected_nutrition(art, rules)
        log.info("review of %s: %s", artwork_path.name, timer.seconds)
        return ReviewResult(
            report=report, rule_sources=sources, coverage=coverage_table(rules, report.findings, not_applicable),
            ai_ran=ai_ran, ai_note="; ".join(notes) or None,
            ai_models=sorted(self.client.models_used) if ai_ran else [],
            corrected_nutrition=corrected, timings=timer.seconds,
        )

    # ---------------- steps ----------------

    def _load_rules(self, paths: list[Path], notes: list[str], use_ai: bool) -> tuple[RuleSet, list[RuleSource]]:
        rules, sources = RuleSet(rules=[]), []
        for path in paths:
            try:
                loaded, source = self._load_rule_file(path, use_ai)
            except AIError as exc:  # a prose rulebook needs AI to read it
                notes.append(f"could not read rules from {path.name}: {exc}")
                continue
            rules = rules.merged(loaded)
            sources.append(source)
        return rules, sources

    def _load_rule_file(self, path: Path, use_ai: bool) -> tuple[RuleSet, RuleSource]:
        """JSON packs and '### ID' rulebooks are parsed exactly; any other text is read by AI."""
        if path.suffix.lower() == ".json":
            pack = load_regulation_pack(path)
            name = pack.rules[0].source_name if pack.rules else path.stem
            return pack, RuleSource(name=name, kind="regulation", rule_count=len(pack.rules))
        book = load_rulebook(path)
        if book.rules:
            return book, RuleSource(name=book.rules[0].source_name, kind="company", rule_count=len(book.rules))
        if not use_ai:  # switching AI off must mean no AI calls at all
            raise AIError("it has no '### ID Title' rule headings, so only AI can read it, "
                          "and AI is not available (switched off, or no GEMINI_API_KEY)")
        id_prefix = "".join(c for c in path.stem.upper() if c.isalpha())[:3] or "U"
        rules, dropped = RulebookReader(self.client).read(path.read_text(encoding="utf-8", errors="replace"), path.stem, id_prefix)
        return RuleSet(rules=rules), RuleSource(name=path.stem, kind="ai_extracted", rule_count=len(rules), dropped=dropped)

    def _add_ai_findings(self, report: Report, art: Artwork, rules: RuleSet, spec: ApprovedSpec | None,
                         crops: list[tuple[str, bytes]], timer: StageTimer) -> tuple[Report, list[str]]:
        # the AI reads the rules with reviewer guidance from earlier false alarms appended
        ctx = CheckContext.build(art, self.feedback.with_rule_notes(rules), spec)
        material = PromptMaterial(ctx, self.client, crops=crops)  # panels already rendered with the code checks
        uncovered = rules_without_code_checks(ctx.rules.rules, report.findings)
        with timer.stage("ai"), ThreadPoolExecutor(max_workers=2) as pool:
            judging = pool.submit(RuleJudge(ctx, self.client, material).judge, uncovered)
            inspecting = pool.submit(MarkInspector(ctx, self.client, material).inspect)
            judgement, marks = judging.result(), inspecting.result()
        # number after the code findings, in a fixed order (rules, then marks), whichever thread finished first
        ai_findings = [
            f.model_copy(update={"id": f"F{len(report.findings) + i:03d}"})
            for i, f in enumerate(judgement.findings + marks, start=1)
        ]
        return report.with_findings(report.findings + ai_findings), judgement.not_applicable

    @staticmethod
    def _corrected_nutrition(art: Artwork, rules: RuleSet) -> CorrectedPanel | None:
        if not rules.get("FDA-101.9-DV"):  # a US Nutrition Facts panel only means something under US rules
            return None
        panel = read_nutrition_panel(art)
        return corrected_panel(panel) if panel else None


OCR_CAVEAT = ("[Text read by OCR from the page image: a misread or missed word can cause this, "
              "so it is marked likely, not definite. Confirm it on the artwork.]")
# decoded from the pixels by the barcode reader and verified by check-digit arithmetic, not read by OCR
OCR_INDEPENDENT_CHECKS = {"barcode", "barcode_check_digit"}


def ocr_capped(finding: Finding) -> Finding:
    """A problem proven from OCR text is only as sure as the OCR: Definite becomes Likely. That includes
    "missing" findings ("No FSSAI licence number"), which cite no line: OCR may simply have missed it."""
    if finding.verdict != Verdict.DEFINITE or finding.check in OCR_INDEPENDENT_CHECKS:
        return finding
    return finding.model_copy(update={
        "verdict": Verdict.LIKELY,
        "confidence": min(finding.confidence, 0.8),
        "explanation": f"{finding.explanation} {OCR_CAVEAT}",
    })


def ocr_note(art: Artwork) -> str:
    if art.text_source == "ocr_layer":
        return (f"{art.file_name} is a scan: its {len(art.lines)} text lines come from an invisible OCR layer added "
                "by the scanning software, not from the artwork file, so issues found in that text are marked "
                "likely, never definite")
    low = sum(1 for ln in art.lines if ln.confidence < 0.8)
    note = (f"{art.file_name} has no live text, so its {len(art.lines)} text lines were read by OCR"
            + (f" ({low} with low confidence)" if low else "")
            + "; issues found in that text are marked likely, never definite")
    if len(art.panels) <= 1:
        note += ("; no dieline was found, so the page is checked as one panel and rules about where copy "
                 "sits (front panel, folds) could not be checked")
    return note


STEERING_CAVEAT = ("[Sent to review: the artwork contains text addressed to an AI reviewer, so no AI pass "
                   "is accepted on it. Please check this rule by eye.]")


def no_ai_pass(finding: Finding) -> Finding:
    """On artwork that tries to steer the AI, an AI pass could be the steering working: a person decides."""
    if finding.method != "ai" or finding.verdict != Verdict.PASS:
        return finding
    return finding.model_copy(update={"verdict": Verdict.REVIEW, "confidence": min(finding.confidence, 0.4),
                                      "explanation": f"{finding.explanation} {STEERING_CAVEAT}"})


def steering_note(lines: list) -> str:
    quoted = "; ".join(f"{ln.id} '{ln.text[:60]}'" for ln in lines[:3])
    return (f"the artwork contains text addressed to an AI reviewer ({quoted}); it was not accepted as evidence "
            "and no AI pass was accepted on this artwork. Text like this should not be on a printed pack")


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
