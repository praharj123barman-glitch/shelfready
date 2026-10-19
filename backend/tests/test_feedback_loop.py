"""Reviewer feedback must change the next review, visibly and reversibly."""

from pathlib import Path

from checker.feedback import load, record, remove_waiver, with_rule_notes
from checker.models import Finding, Verdict
from checker.pipeline import review
from checker.rules import Rule, RuleSet

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
XLSX = ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"
RULES = [ROOT / "rules" / "us_fda_food.json", ROOT / "rules" / "dancing_fish_company_rulebook.md"]


def run(store):
    return review(PDF, XLSX, RULES, use_ai=False, feedback_store=store).report


def test_false_alarm_waives_the_problem_on_the_next_run(tmp_path):
    store = tmp_path / "feedback.json"
    first = run(store)
    target = next(f for f in first.findings if f.check == "gmo_wording")
    assert target.verdict == Verdict.LIKELY and target.waiver is None

    out = record(target, "false_alarm", "Our legal team approved GMO Free for this market", PDF, store)
    assert out["waiver"] and out["rule_note"] is None  # code finding: waiver only

    second = run(store)
    again = next(f for f in second.findings if f.check == "gmo_wording")
    assert again.waiver["reason"].startswith("Our legal team")  # still listed, with the reason
    assert second.waived == 1
    assert second.summary["likely"] == first.summary["likely"] - 1  # no longer counts

    assert remove_waiver(out["waiver"]["id"], store)  # undo
    assert run(store).waived == 0


def test_waiver_only_applies_to_the_same_artwork_file(tmp_path):
    store = tmp_path / "feedback.json"
    target = next(f for f in run(store).findings if f.check == "gmo_wording")
    other = tmp_path / "other.pdf"
    other.write_bytes(PDF.read_bytes() + b"\n%changed")  # a different file, same content otherwise
    record(target, "false_alarm", "ok here", other, store)
    assert run(store).waived == 0


def test_ai_false_alarm_becomes_rule_guidance(tmp_path):
    store = tmp_path / "feedback.json"
    ai_finding = Finding(id="F1", check="ai_rule_RET-01", category="ai_rules", verdict=Verdict.LIKELY,
                         title="Brand logo missing from front panel", explanation="x", rule_id="RET-01", method="ai")
    out = record(ai_finding, "false_alarm", "The logo on the top flap counts for this retailer", PDF, store)
    assert out["rule_note"]["rule_id"] == "RET-01"
    rules = RuleSet(rules=[Rule(id="RET-01", title="Logo", text="Logo on front.", source="company", source_name="x")])
    assert "top flap counts" in with_rule_notes(rules, store).rules[0].text


def test_accepting_does_not_waive(tmp_path):
    store = tmp_path / "feedback.json"
    target = next(f for f in run(store).findings if f.check == "gmo_wording")
    record(target, "accepted", "", PDF, store)
    assert load(store).waivers == [] and run(store).waived == 0
