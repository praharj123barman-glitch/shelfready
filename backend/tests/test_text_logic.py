from checker.checks.label_checks import upc_check_digit_ok
from checker.checks.match_checks import diff_ingredients, similarity
from checker.rules import parse_markdown_rulebook
from checker.sections import split_ingredients


def test_split_ingredients_respects_brackets_and_sentence_breaks():
    text = "INGREDIENTS: Oats (79%), Vegetable Oil (Rapeseed, Sunflower), Honey (1%), Salt. Natural Flavoring."
    assert split_ingredients(text) == ["Oats (79%)", "Vegetable Oil (Rapeseed, Sunflower)", "Honey (1%)", "Salt", "Natural Flavoring"]


def test_similarity_ignores_generic_words():
    assert similarity("Dried Blueberries", "Blueberries") == 1.0
    assert similarity("Sunflower Seeds", "Flax Seeds") == 0.0


def test_diff_ingredients_classifies_changes():
    approved = ["Oats (79%)", "Almonds", "Dried Blueberries", "Honey (9%)"]
    artwork = ["Oats (79%)", "Almonds", "Walnuts", "Blueberries", "Honey (1%)"]
    changes = {(r["change"], r["approved"], r["artwork"]) for r in diff_ingredients(artwork, approved)}
    assert ("reworded", "Dried Blueberries", "Blueberries") in changes
    assert ("added, not approved", "", "Walnuts") in changes
    assert ("percentage changed", "Honey (9%)", "Honey (1%)") in changes


def test_identical_lists_have_no_diff():
    items = ["Oats", "Almonds"]
    assert diff_ingredients(items, items) == []


def test_upc_check_digit():
    assert upc_check_digit_ok("0120000000036")  # EAN-13 from the sample carton
    assert upc_check_digit_ok("120000000036")  # same code as UPC-A
    assert not upc_check_digit_ok("120000000035")
    assert not upc_check_digit_ok("12ab")


def test_markdown_rulebook_parsing():
    rs = parse_markdown_rulebook("# Book\n### AB-1 First rule\nDo this.\n\n### AB-2 Second\nDo that.\n", "Book")
    assert [r.id for r in rs.rules] == ["AB-1", "AB-2"]
    assert rs.rules[0].text == "Do this."
    assert rs.get("AB-2").title == "Second"


def test_free_form_rulebook_yields_no_invented_rules():
    assert parse_markdown_rulebook("Just some prose about labels.", "x").rules == []
