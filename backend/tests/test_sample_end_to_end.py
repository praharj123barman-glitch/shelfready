"""End to end on the real Esko sample files: every planted defect we know about
must be reported with the right verdict, and the correct parts must pass."""

from pathlib import Path

import pytest

from checker.artwork import ArtworkError, read_artwork
from checker.content_sheet import SheetError, read_content_sheet
from checker.engine import run_checks
from checker.rules import load_regulation_pack, load_rulebook

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
XLSX = ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"


@pytest.fixture(scope="module")
def artwork():
    return read_artwork(PDF)


@pytest.fixture(scope="module")
def report(artwork):
    rules = load_regulation_pack(ROOT / "rules" / "us_fda_food.json").merged(
        load_rulebook(ROOT / "rules" / "dancing_fish_company_rulebook.md")
    )
    return run_checks(artwork, rules, read_content_sheet(XLSX))


def verdict_of(report, check):
    return {f.verdict.value for f in report.findings if f.check == check}


def test_reads_live_text_panels_and_barcode(artwork):
    assert set(artwork.panels) >= {"front", "back", "left", "right"}
    assert any(l.text == "Total Carbohydrate 66g" and l.panel == "left" for l in artwork.lines)
    assert artwork.barcodes[0]["text"] == "0120000000036"


def test_hidden_eu_table_detected_and_visible_panel_not(artwork):
    hidden = {l.text for l in artwork.lines if l.hidden}
    assert {"Typical Values", "1868kJ/445kcal", "Carbohydrate"} <= hidden
    assert not any(l.hidden for l in artwork.lines if l.text.startswith("Total Carbohydrate"))


def test_dieline_marks_are_not_copy(artwork):
    assert all(l.role == "guide" for l in artwork.lines if l.text in {"Front panel", "Orientation", "Copy free"})


@pytest.mark.parametrize(
    "check, verdict",
    [
        ("calories_atwater", "definite"),
        ("rounding", "definite"),
        ("daily_values", "definite"),
        ("serving_size", "definite"),
        ("nf_vs_sheet", "definite"),
        ("no_added_sugar", "definite"),
        ("vegan_ingredients", "definite"),
        ("vegan_cholesterol", "definite"),
        ("may_contain_ingredient", "definite"),
        ("net_quantity_pdp", "definite"),
        ("net_quantity_units", "definite"),
        ("manufacturer", "definite"),
        ("hidden", "definite"),
        ("ingredients_match", "definite"),
        ("servings_math", "likely"),
        ("added_sugars_zero", "likely"),
        ("eu_allergen_terms", "review"),
        ("sheet_sugars_gt_carbs", "review"),
    ],
)
def test_planted_defects_found(report, check, verdict):
    assert verdict_of(report, check) == {verdict}


@pytest.mark.parametrize("check", ["barcode", "identity", "dieline_marks", "subtotals", "allergens_declared", "text_storage_instructions"])
def test_correct_parts_pass(report, check):
    assert verdict_of(report, check) == {"pass"}


def test_report_is_not_ready_and_every_problem_has_evidence(report):
    assert report.ready_to_launch is False
    assert report.check_errors == []
    for f in report.findings:
        if f.verdict.value in {"definite", "likely"}:
            assert f.evidence, f"{f.check} has no evidence"
            assert f.rule_id, f"{f.check} cites no rule"


def test_missing_and_invalid_files_raise_clear_errors(tmp_path):
    with pytest.raises(ArtworkError, match="not found"):
        read_artwork(tmp_path / "nope.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")
    with pytest.raises(ArtworkError, match="Could not open"):
        read_artwork(bad)
    with pytest.raises(SheetError, match="not found"):
        read_content_sheet(tmp_path / "nope.xlsx")
