"""Reviewer feedback must change the next review, visibly and reversibly."""

from pathlib import Path

import pytest

from checker.feedback import FeedbackStore
from checker.models import Finding, Verdict
from checker.pipeline import ReviewPipeline
from checker.rules import Rule, RuleSet

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
V2 = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton_v2_GENERATED.pdf"
XLSX = ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"
RULES = [ROOT / "rules" / "us_fda_food.json", ROOT / "rules" / "dancing_fish_company_rulebook.md"]


@pytest.fixture
def store(tmp_path):
    return FeedbackStore(tmp_path / "feedback.json")


def review(store, pdf=PDF):
    return ReviewPipeline(feedback=store).run(pdf, XLSX, RULES, use_ai=False).report


def gmo_finding(store):
    return next(f for f in review(store).findings if f.check == "gmo_wording")


def test_false_alarm_waives_the_problem_on_the_next_run(store):
    first = review(store)
    target = next(f for f in first.findings if f.check == "gmo_wording")
    assert target.verdict == Verdict.LIKELY and target.waiver is None

    out = store.record(target, "false_alarm", "Our legal team approved GMO Free for this market", PDF)
    assert out["waiver"] and out["rule_note"] is None  # code finding: waiver only

    second = review(store)
    again = next(f for f in second.findings if f.check == "gmo_wording")
    assert again.waiver["reason"].startswith("Our legal team")  # still listed, with the reason
    assert second.waived == 1
    assert second.summary["likely"] == first.summary["likely"] - 1  # no longer counts

    assert store.remove_waiver(out["waiver"]["id"])  # undo
    assert review(store).waived == 0


def test_waiver_only_applies_to_the_same_artwork_file(store, tmp_path):
    other = tmp_path / "other.pdf"
    other.write_bytes(PDF.read_bytes() + b"\n%changed")  # a different file, same content otherwise
    store.record(gmo_finding(store), "false_alarm", "ok here", other)
    assert review(store).waived == 0


def test_ai_false_alarm_becomes_rule_guidance(store):
    ai_finding = Finding(id="F1", check="ai_rule_RET-01", category="ai_rules", verdict=Verdict.LIKELY,
                         title="Brand logo missing from front panel", explanation="x", rule_id="RET-01", method="ai")
    out = store.record(ai_finding, "false_alarm", "The logo on the top flap counts for this retailer", PDF)
    assert out["rule_note"]["rule_id"] == "RET-01"
    rules = RuleSet(rules=[Rule(id="RET-01", title="Logo", text="Logo on front.", source="company", source_name="x")])
    assert "top flap counts" in store.with_rule_notes(rules).rules[0].text


def test_accepting_does_not_waive(store):
    store.record(gmo_finding(store), "accepted", "", PDF)
    assert store.load().waivers == [] and review(store).waived == 0


def test_waivers_carry_over_to_a_new_proof(store):
    store.record(gmo_finding(store), "false_alarm", "Legal approved", PDF)
    assert store.carry_waivers(PDF, V2) == 1
    assert store.carry_waivers(PDF, V2) == 0  # idempotent
    gmo = next(f for f in review(store, V2).findings if f.check == "gmo_wording")
    assert gmo.waiver and "carried over" in gmo.waiver["reason"]
