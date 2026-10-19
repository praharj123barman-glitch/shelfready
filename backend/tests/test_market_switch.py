"""Rules are data: the same carton gives market-correct results under US and India rules."""

from pathlib import Path

import pytest

from checker.artwork import read_artwork
from checker.content_sheet import read_content_sheet
from checker.engine import run_checks
from checker.rules import load_regulation_pack, load_rulebook

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "rules"


@pytest.fixture(scope="module")
def inputs():
    return (read_artwork(ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"),
            read_content_sheet(ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"))


def checks(report):
    return {f.check: f for f in report.findings}


@pytest.fixture(scope="module")
def us(inputs):
    rules = load_regulation_pack(R / "us_fda_food.json").merged(load_rulebook(R / "dancing_fish_company_rulebook.md"))
    return checks(run_checks(*inputs[:1], rules, inputs[1]))


@pytest.fixture(scope="module")
def india(inputs):
    rules = load_regulation_pack(R / "india_fssai_food.json").merged(load_regulation_pack(R / "artwork_approval_core.json"))
    return checks(run_checks(*inputs[:1], rules, inputs[1]))


def test_us_only_checks_switch_off_for_india(us, india):
    for c in ["rounding", "daily_values", "net_quantity_units", "type_size", "net_qty_height", "eu_front_of_pack"]:
        assert c in us and c not in india, c


def test_india_checks_switch_on_only_for_india(us, india):
    for c in ["fssai_licence", "fssai_mrp", "fssai_consumer_care", "fssai_nutrition", "fssai_contains"]:
        assert c in india and c not in us, c
        assert india[c].verdict.value == "definite"


def test_grams_alone_are_fine_in_india_but_not_in_the_us(us, india):
    assert us["net_quantity_units"].verdict.value == "definite"  # US needs ounces too
    assert "ounce" not in india["fssai_net_qty"].explanation.lower()
    assert "metric units, which India accepts" in india["fssai_net_qty"].explanation


def test_hidden_per_100g_table_does_not_count_in_india(india):
    assert "hidden" in india["fssai_nutrition"].explanation


def test_shared_requirements_cite_the_loaded_rule(us, india):
    assert us["hidden"].rule_id == "DF-06" and india["hidden"].rule_id == "CORE-HIDDEN"
    assert us["no_added_sugar"].rule_id == "FDA-101.60-NAS" and india["no_added_sugar"].rule_id == "FSSAI-CLAIM-NAS"
    assert india["no_added_sugar"].rule_text  # the FSSAI rule text is attached, not left empty


def test_market_mismatch_is_flagged(us, india):
    assert "market_mismatch" in india and "market_mismatch" not in us
