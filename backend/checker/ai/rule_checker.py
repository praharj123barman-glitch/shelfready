"""AI judgement for rules no deterministic check covers.

Guardrails, in order:
1. The model sees the real extracted text (each line tagged with its id) and
   rendered images of the panels, nothing else.
2. Every claim must cite evidence: a text line id with a verbatim quote, or a
   panel image with a description of what is seen there.
3. Text quotes are verified against the cited line. A finding whose text
   evidence does not check out is downgraded to REVIEW and says why.
4. AI can never return DEFINITE. Only arithmetic and exact matching can.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..artwork import render_panel_png
from ..checks.base import CheckContext, art_evidence
from ..models import Evidence, Finding, Verdict
from ..rules import Rule
from .client import AIError, generate_json, image_part

RULES_PER_CALL = 8  # batching keeps the free tier's per-minute limit out of the way
IMAGE_PANELS = ["front", "back", "left", "right", "top"]
# at 110 dpi the model misread the recycling mark as "PAP 21"; small print needs more pixels
IMAGE_DPI = 160

SYSTEM = """You are a senior packaging compliance reviewer checking rules against one carton artwork.
You get the artwork as extracted TEXT LINES (each with an id like L013) and as one IMAGE per panel.
Logos, certification marks, symbols and barcodes are usually graphics, so look for them in the images, not the text.
Work only from what you are given. Never use outside knowledge about this product.
For every rule, cite evidence: either kind "text" with the line id and the exact words from that line,
or kind "visual" with the panel name and a short description of what you see in that panel image,
or, when something required is missing, kind "absent" with the words or symbols you searched for.
If what you are given is not enough to decide, answer "review" and say what a human must check.
Use "not_applicable" when the rule does not apply to this product.
Use "likely" only when the evidence clearly breaks the rule. Use "pass" only when it clearly satisfies it.
Be brief and concrete. No hype, no exclamation marks."""


class CitedEvidence(BaseModel):
    kind: Literal["text", "visual", "absent"]
    line_id: str | None = Field(default=None, description="for kind text: the line id, e.g. L013")
    quote: str | None = Field(default=None, description="for kind text: exact words copied from that line")
    panel: str | None = Field(default=None, description="for kind visual: front, back, left, right or top")
    description: str | None = Field(default=None, description="for kind visual: what is seen in the panel image")
    searched_for: list[str] = Field(
        default_factory=list,
        description="for kind absent: words or symbols that would show the required item if it were present, e.g. ['www', '.com', 'call', '1-800']",
    )


class RuleVerdict(BaseModel):
    rule_id: str
    verdict: Literal["pass", "likely", "review", "not_applicable"]
    title: str = Field(description="one-line finding headline, under 90 characters")
    reasoning: str = Field(description="2 to 3 sentences: what the artwork shows and why it does or does not meet the rule")
    evidence: list[CitedEvidence]
    fix: str | None = Field(default=None, description="what to change, if anything")


class RuleVerdicts(BaseModel):
    verdicts: list[RuleVerdict]


def artwork_digest(ctx: CheckContext) -> str:
    rows = []
    for panel in ["front", "back", "left", "right", "top", "bottom", "other"]:
        lines = ctx.art.copy_lines(panel)
        if lines:
            rows.append(f"## {panel} panel")
            rows += [f"[{ln.id}] {ln.text}" for ln in sorted(lines, key=lambda l: (l.bbox.y0, l.bbox.x0))]
    hidden = [ln for ln in ctx.art.lines if ln.hidden and ln.role == "copy"]
    if hidden:
        rows.append("## hidden (covered by other artwork, not visible)")
        rows += [f"[{ln.id}] {ln.text}" for ln in hidden]
    return "\n".join(rows)


def sheet_digest(ctx: CheckContext) -> str:
    if ctx.spec is None:
        return "(no approved content sheet supplied)"
    return "\n".join(f"[{f.cell}] {f.label}: {f.value}" for f in ctx.spec.fields.values())


def panel_images(ctx: CheckContext) -> list:
    """Alternating caption + image parts for each main panel."""
    if not ctx.art.path:
        return []
    parts = []
    for name in IMAGE_PANELS:
        if bb := ctx.art.panels.get(name):
            parts += [f"IMAGE: {name} panel", image_part(render_panel_png(ctx.art.path, bb, dpi=IMAGE_DPI))]
    return parts


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_evidence(ctx: CheckContext, items: list[CitedEvidence]) -> tuple[list[CitedEvidence], list[str]]:
    """Keep evidence that checks out. Text quotes must be in the cited line;
    visual evidence must name a real panel (its content cannot be verified in code)."""
    ok, problems = [], []
    all_text = [(ln.id, _norm(ln.text)) for ln in ctx.art.copy_lines()]
    for e in items:
        if e.kind == "absent":
            terms = [_norm(t) for t in e.searched_for if t.strip()]
            hits = [(lid, t) for t in terms for lid, txt in all_text if t in txt]
            if not terms:
                problems.append("absence claimed without saying what was searched for")
            elif hits:
                problems.append("claimed missing, but " + ", ".join(f"'{t}' is in {lid}" for lid, t in hits[:3]))
            else:
                ok.append(e)
            continue
        if e.kind == "visual":
            if e.panel in ctx.art.panels and e.description:
                ok.append(e)
            else:
                problems.append(f"visual evidence names an unknown panel '{e.panel}'")
            continue
        line = ctx.line(e.line_id)
        if line is None:
            problems.append(f"cited line {e.line_id} does not exist")
        elif not e.quote or (_norm(e.quote) not in _norm(line.text) and _norm(line.text) not in _norm(e.quote)):
            problems.append(f"quote '{e.quote}' is not in line {e.line_id} ('{line.text}')")
        else:
            ok.append(e)
    return ok, problems


def _evidence(ctx: CheckContext, e: CitedEvidence) -> Evidence:
    if e.kind == "absent":
        return Evidence(source="computed", text="Verified absent from all artwork text: " + ", ".join(f"'{t}'" for t in e.searched_for))
    if e.kind == "visual":
        return Evidence(source="artwork", text=f"Seen in image: {e.description}", panel=e.panel, bbox=ctx.art.panels[e.panel])
    return art_evidence([ctx.line(e.line_id)], text=e.quote)


def to_finding(ctx: CheckContext, rule: Rule, v: RuleVerdict) -> Finding | None:
    if v.verdict == "not_applicable":
        return None
    verified, problems = verify_evidence(ctx, v.evidence)
    verdict = {"pass": Verdict.PASS, "likely": Verdict.LIKELY, "review": Verdict.REVIEW}[v.verdict]
    explanation = v.reasoning
    if problems or (verdict != Verdict.REVIEW and not verified):
        verdict = Verdict.REVIEW
        explanation += " [Downgraded to review: the AI's evidence did not check out against the artwork: " + (
            "; ".join(problems) if problems else "no evidence cited") + ".]"
    visual_only = verified and all(e.kind == "visual" for e in verified)
    confidence = 0.4 if verdict == Verdict.REVIEW else 0.6 if visual_only else 0.75
    return ctx.finding(
        f"ai_rule_{rule.id}", "ai_rules", verdict, v.title, explanation, rule_id=rule.id,
        fix=v.fix, method="ai", confidence=confidence, evidence=[_evidence(ctx, e) for e in verified],
    )


def _failed(ctx: CheckContext, rule: Rule, reason: str) -> Finding:
    return ctx.finding(
        f"ai_rule_{rule.id}", "ai_rules", Verdict.REVIEW, f"Rule {rule.id} could not be checked automatically",
        f"{reason} A human must check this rule: {rule.text}", rule_id=rule.id, method="ai", confidence=0.0,
    )


def _check_batch(ctx: CheckContext, rules: list[Rule], images: list) -> tuple[list[Finding], list[str]]:
    rule_text = "\n".join(
        f"- {r.id}: {r.title}. {r.text} (source: {r.source_name}{', ' + r.citation if r.citation else ''})" for r in rules
    )
    market = ctx.spec.value("country_of_market") if ctx.spec else "unknown"
    prompt = [
        f"RULES TO CHECK (answer every rule id once)\n{rule_text}\n\nMARKET: {market}\n\n"
        f"ARTWORK TEXT LINES\n{artwork_digest(ctx)}\n\nAPPROVED CONTENT SHEET\n{sheet_digest(ctx)}\n",
        *images,
    ]
    try:
        answer = generate_json(prompt, RuleVerdicts, SYSTEM)
    except AIError as exc:
        return [_failed(ctx, r, f"The AI check failed ({str(exc)[:160]}).") for r in rules], []
    by_id = {v.rule_id: v for v in answer.verdicts}
    out, not_applicable = [], []
    for r in rules:
        if r.id not in by_id:
            out.append(_failed(ctx, r, "The AI returned no verdict for this rule."))
        elif f := to_finding(ctx, r, by_id[r.id]):
            out.append(f)
        else:
            not_applicable.append(r.id)
    return out, not_applicable


def check_rules(ctx: CheckContext, rules: list[Rule]) -> tuple[list[Finding], list[str]]:
    """Returns findings plus the ids the AI judged not applicable to this product."""
    findings: list[Finding] = []
    not_applicable: list[str] = []
    if not rules:
        return findings, not_applicable
    images = panel_images(ctx)
    for i in range(0, len(rules), RULES_PER_CALL):
        f, na = _check_batch(ctx, rules[i : i + RULES_PER_CALL], images)
        findings += f
        not_applicable += na
    return findings, not_applicable


def uncovered_rules(rules: list[Rule], findings: list[Finding]) -> list[Rule]:
    covered = {f.rule_id for f in findings if f.method == "deterministic" and f.rule_id}
    return [r for r in rules if r.id not in covered]


# ---------------- free-form rulebooks ----------------

EXTRACT_SYSTEM = """You turn a packaging rules document into a list of separate, checkable rules.
Copy each rule's key sentence verbatim into source_quote. Do not add rules that are not in the document.
Skip background text, definitions and history that do not require anything of the label."""


class ExtractedRule(BaseModel):
    title: str = Field(description="short name of the rule")
    requirement: str = Field(description="what the label must or must not do, one or two sentences")
    source_quote: str = Field(description="sentence copied word for word from the document")


class ExtractedRules(BaseModel):
    rules: list[ExtractedRule]


def extract_rules(document: str, source_name: str, prefix: str = "U") -> tuple[list[Rule], list[str]]:
    """AI splits free text into rules; any rule whose quote is not in the document is dropped."""
    result = generate_json(f"DOCUMENT: {source_name}\n\n{document[:60000]}", ExtractedRules, EXTRACT_SYSTEM)
    doc = _norm(document)
    rules, dropped = [], []
    for i, r in enumerate(result.rules, 1):
        if _norm(r.source_quote)[:80] in doc:
            rules.append(Rule(id=f"{prefix}-{i:02d}", title=r.title, text=r.requirement, source="company",
                              source_name=source_name, citation=f"quote: \"{r.source_quote[:160]}\""))
        else:
            dropped.append(r.title)
    return rules, dropped
