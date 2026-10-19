"""The AI layer's safety net, tested with hand-made model answers (no API calls).

Whatever the model says, code decides what survives: fabricated quotes, false
'missing' claims and unsupported passes must all come out as REVIEW, and AI
must never produce a DEFINITE finding.
"""

from pathlib import Path

import pytest

from checker.ai.client import default_client
from checker.ai.evidence import CitedEvidence
from checker.ai.rule_judge import RuleJudge, RuleVerdict
from checker.artwork import read_artwork
from checker.checks.base import CheckContext
from checker.models import Verdict
from checker.rules import Rule, RuleSet

ROOT = Path(__file__).resolve().parents[2]
RULE = Rule(id="T-01", title="Test rule", text="Something must be on the pack.", source="company", source_name="test")


@pytest.fixture(scope="module")
def ctx():
    art = read_artwork(ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf")
    return CheckContext.build(art, RuleSet(rules=[RULE]), None)


def to_finding(ctx, rule, answer):
    return RuleJudge(ctx, default_client()).to_finding(rule, answer)


def line_id(ctx, text):
    return next(l.id for l in ctx.art.lines if l.text == text)


def answer(verdict, *evidence):
    return RuleVerdict(rule_id="T-01", verdict=verdict, title="t", reasoning="r", evidence=list(evidence))


def test_real_quote_is_kept(ctx):
    lid = line_id(ctx, "Store in a cool, dry place. Once")
    f = to_finding(ctx, RULE, answer("pass", CitedEvidence(kind="text", line_id=lid, quote="cool, dry place")))
    assert f.verdict == Verdict.PASS and f.evidence


def test_fabricated_quote_is_downgraded(ctx):
    lid = line_id(ctx, "Store in a cool, dry place. Once")
    f = to_finding(ctx, RULE, answer("likely", CitedEvidence(kind="text", line_id=lid, quote="keep refrigerated")))
    assert f.verdict == Verdict.REVIEW
    assert "did not check out" in f.explanation


def test_nonexistent_line_is_downgraded(ctx):
    f = to_finding(ctx, RULE, answer("likely", CitedEvidence(kind="text", line_id="L999", quote="anything")))
    assert f.verdict == Verdict.REVIEW


def test_false_absence_claim_is_rejected(ctx):
    # the model claims storage instructions are missing; 'store in a cool' is on the pack
    f = to_finding(ctx, RULE, answer("likely", CitedEvidence(kind="absent", searched_for=["store in a cool"])))
    assert f.verdict == Verdict.REVIEW


def test_true_absence_claim_is_accepted(ctx):
    f = to_finding(ctx, RULE, answer("likely", CitedEvidence(kind="absent", searched_for=["www", "1-800"])))
    assert f.verdict == Verdict.LIKELY


def test_absence_is_checked_on_the_named_panel_only(ctx):
    # 'Dancing Fish' is printed on the back (manufacturer line) but not on the front face
    front = to_finding(ctx, RULE, answer("likely", CitedEvidence(kind="absent", panel="front", searched_for=["dancing fish"])))
    back = to_finding(ctx, RULE, answer("likely", CitedEvidence(kind="absent", panel="back", searched_for=["dancing fish"])))
    assert front.verdict == Verdict.LIKELY
    assert back.verdict == Verdict.REVIEW


def test_pass_without_evidence_is_downgraded(ctx):
    assert to_finding(ctx, RULE, answer("pass")).verdict == Verdict.REVIEW


def test_visual_evidence_needs_a_real_panel(ctx):
    ok = to_finding(ctx, RULE, answer("pass", CitedEvidence(kind="visual", panel="front", description="logo")))
    bad = to_finding(ctx, RULE, answer("pass", CitedEvidence(kind="visual", panel="lid", description="logo")))
    assert ok.verdict == Verdict.PASS and ok.confidence < 0.75  # image-only evidence carries lower confidence
    assert bad.verdict == Verdict.REVIEW


def test_ai_cannot_be_definite(ctx):
    # the response schema has no 'definite' option at all
    with pytest.raises(ValueError):
        answer("definite")


def test_not_applicable_produces_no_finding(ctx):
    assert to_finding(ctx, RULE, answer("not_applicable")) is None
