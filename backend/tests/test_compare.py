"""Version compare on the generated second proof (see eval/make_v2_proof.py)."""

from pathlib import Path

import pytest

from checker.artwork import read_artwork
from checker.compare import compare
from checker.pipeline import review

ROOT = Path(__file__).resolve().parents[2]
S, R = ROOT / "samples", ROOT / "rules"
V1 = S / "DancingFish_Granola_Berry_US_Carton.pdf"
V2 = S / "DancingFish_Granola_Berry_US_Carton_v2_GENERATED.pdf"
SHEET = S / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"


@pytest.fixture(scope="module")
def comparison(tmp_path_factory):
    store = tmp_path_factory.mktemp("fb") / "feedback.json"
    rules = [R / "us_fda_food.json", R / "dancing_fish_company_rulebook.md"]
    a = review(V1, SHEET, rules, use_ai=False, feedback_store=store).report
    b = review(V2, SHEET, rules, use_ai=False, feedback_store=store).report
    return compare(read_artwork(V1), read_artwork(V2), a.findings, b.findings)


def test_text_diff_finds_exactly_the_four_edits(comparison):
    got = {(c.kind, c.before, c.after) for c in comparison.text_changes}
    assert got == {
        ("changed", "Almonds, May Contain Brazil Nuts, May", "Almonds, May"),
        ("changed", "85", "3/4 cup (60g)"),
        ("added", None, "12 Main St, Portland, OR 97201"),
        ("added", None, "NET WT 16.9 OZ (480g)"),
    }


def test_issue_delta(comparison):
    resolved = {i.check for i in comparison.issues if i.status == "resolved"}
    introduced = {i.check for i in comparison.issues if i.status == "introduced"}
    assert {"net_quantity_pdp", "net_quantity_units", "manufacturer", "serving_size", "net_qty_height"} <= resolved
    assert introduced == {"text_allergen_information"}  # the regression: Brazil nuts dropped


def test_identical_proofs_have_no_changes():
    art = read_artwork(V1)
    c = compare(art, art, [], [])
    assert c.text_changes == [] and c.issues == []


def test_waiver_difference_is_not_an_introduced_issue():
    from checker.models import Finding, Verdict

    f = Finding(id="F1", check="gmo_wording", category="claims", verdict=Verdict.LIKELY, title="'GMO Free' wording is used", explanation="x")
    waived = f.model_copy(update={"waiver": {"reason": "ok"}})
    from checker.compare import diff_issues
    assert [i.status for i in diff_issues([waived], [f])] == ["still_open"]
