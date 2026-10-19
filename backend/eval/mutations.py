"""Controlled edits to the real sample files, for measuring the checker.

Each mutation edits the artwork PDF (replace, delete or add one piece of text)
or one cell of the content sheet, and states what the checker must do:

  expect "fail": the check must now report a definite or likely problem
  expect "pass": the check must now pass (or its problem finding disappear)

`allow` lists checks that may legitimately change as a side effect (editing
the saturated fat value also makes the sheet comparison disagree). Any other
check that gets worse counts as a false alarm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import pymupdf

TEXT_COLOR = (0.137, 0.122, 0.125)  # the sample's body text colour


@dataclass
class Edit:
    kind: str  # replace | delete | insert | clear | sheet
    target: str = ""  # exact line text (replace/delete) or cell (sheet)
    text: str = ""  # new text (replace/insert) or cell value (sheet)
    at: tuple[float, float] | None = None  # insert: baseline origin in PDF points
    rect: tuple[float, float, float, float] | None = None  # clear: remove all text in this area
    size: float | None = None  # insert/replace font size override
    right_align: bool = False  # replace: keep the right edge (numbers in a column)


@dataclass
class Mutation:
    id: str
    kind: str  # detect | repair
    description: str
    edits: list[Edit]
    expect: dict[str, str]
    allow: list[str] = field(default_factory=list)


def _find_line(page: pymupdf.Page, text: str) -> dict:
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            if "".join(s["text"] for s in line["spans"]).strip() == text:
                return line
    raise ValueError(f"line not found in artwork: {text!r}")


def _remove(page: pymupdf.Page, line: dict) -> None:
    """Redact a thin band just above the baseline (the body of the letters), not the
    whole line box: a tall line box can contain smaller text above it ('Amount per
    serving' inside the 'Calories 166' box). fill=False keeps the artwork untouched."""
    r = pymupdf.Rect(line["bbox"])
    span = line["spans"][0]
    base, size = span["origin"][1], span["size"]
    page.add_redact_annot(pymupdf.Rect(r.x0, base - 0.55 * size, r.x1, base - 0.15 * size), fill=False)
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE, text=pymupdf.PDF_REDACT_TEXT_REMOVE
    )


def apply_pdf(src: Path, dst: Path, edits: list[Edit]) -> None:
    doc = pymupdf.open(src)
    page = doc[0]
    for e in edits:
        if e.kind == "insert":
            page.insert_text(e.at, e.text, fontsize=e.size or 8, fontname="helv", color=TEXT_COLOR)
            continue
        if e.kind == "clear":  # curved headlines are one glyph per line, so remove by area
            page.add_redact_annot(pymupdf.Rect(*e.rect), fill=False)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                                  text=pymupdf.PDF_REDACT_TEXT_REMOVE)
            continue
        line = _find_line(page, e.target)
        span = line["spans"][0]
        _remove(page, line)
        if e.kind == "replace":
            size = e.size or span["size"]
            x, y = span["origin"]
            if e.right_align:
                x = line["bbox"][2] - pymupdf.get_text_length(e.text, fontname="helv", fontsize=size)
            page.insert_text((x, y), e.text, fontsize=size, fontname="helv", color=TEXT_COLOR)
    doc.save(dst)


def apply_sheet(src: Path, dst: Path, edits: list[Edit]) -> None:
    wb = openpyxl.load_workbook(src)
    ws = wb.worksheets[0]
    for e in edits:
        ws[e.target] = e.text
    wb.save(dst)


R = Edit  # short alias for the table below

MUTATIONS: list[Mutation] = [
    # ---------- detect: inject one new defect ----------
    Mutation("D01", "detect", "Storage text reworded ('cool' to 'warm')",
             [R("replace", "Store in a cool, dry place. Once", "Store in a warm, dry place. Once")],
             {"text_storage_instructions": "fail"}),
    Mutation("D02", "detect", "Marketing copy shortened",
             [R("replace", "your tail fins!", "your fins!")],
             {"text_marketing_copy": "fail"}, allow=["unapproved_copy"]),
    Mutation("D03", "detect", "Brazil nuts dropped from the allergen statement",
             [R("replace", "Almonds, May Contain Brazil Nuts, May", "Almonds, May")],
             {"text_allergen_information": "fail"}),
    Mutation("D04", "detect", "Saturated fat raised so fats exceed total fat",
             [R("replace", "Saturated Fat 5g", "Saturated Fat 9g")],
             {"subtotals": "fail"}, allow=["nf_vs_sheet", "daily_values", "rounding"]),
    Mutation("D05", "detect", "Trans fat raised so fats exceed total fat",
             [R("replace", "Trans Fat 8g", "Trans Fat 12g")],
             {"subtotals": "fail"}, allow=["nf_vs_sheet", "rounding"]),
    Mutation("D06", "detect", "Total sugars larger than total carbohydrate",
             [R("replace", "Total Sugars 18g", "Total Sugars 70g")],
             {"subtotals": "fail"}, allow=["nf_vs_sheet"]),
    Mutation("D07", "detect", "%DV footnote removed",
             [R("delete", "* The % Daily Value (DV) tells you how much a")],
             {"nf_present": "fail"}),
    Mutation("D08", "detect", "Ingredient listed twice",
             [R("replace", "Salt. Natural Flavoring.", "Salt, Almonds. Natural Flavoring.")],
             {"ingredient_structure": "fail"}, allow=["ingredients_match"]),
    Mutation("D09", "detect", "Declared percentages out of descending order",
             [R("replace", "(79%),", "(0.5%),")],
             {"ingredient_structure": "fail"}, allow=["ingredients_match"]),
    Mutation("D10", "detect", "Net weight declaration deleted",
             [R("delete", "480g")],
             {"net_quantity": "fail"}, allow=["servings_math"]),
    Mutation("D11", "detect", "Unapproved 'GLUTEN FREE' claim added to the front",
             [R("insert", text="GLUTEN", at=(700, 700), size=11), R("insert", text="FREE", at=(704, 713), size=11)],
             {"claims_approved": "fail"}),
    Mutation("D12", "detect", "Statement of identity removed from the front",
             [R("clear", rect=(660, 370, 1075, 500))],
             {"identity": "fail"}, allow=["folds", "unapproved_copy"]),
    Mutation("D13", "detect", "Sheet UPC changed (barcode no longer matches)",
             [R("sheet", "E12", "1 20000 00003 7")],
             {"barcode": "fail"}),
    Mutation("D14", "detect", "Sheet net weight changed to 500g",
             [R("sheet", "B35", "500g")],
             {"net_quantity_sheet": "fail"}),
    Mutation("D15", "detect", "Sheet storage text changed",
             [R("sheet", "B25", "Store in the fridge after opening.")],
             {"text_storage_instructions": "fail"}),
    Mutation("D16", "detect", "Copy pushed across the front/left fold",
             [R("insert", text="Crunchy oat clusters", at=(1030, 650), size=9)],
             {"folds": "fail"}, allow=["unapproved_copy"]),
    # ---------- repair: fix one known defect, the finding must go away ----------
    Mutation("R01", "repair", "Net weight added to the front in oz and g at legal size",
             [R("insert", text="NET WT 16.9 OZ (480g)", at=(690, 760), size=20)],
             {"net_quantity_pdp": "pass", "net_quantity_units": "pass", "net_qty_height": "pass"}),
    Mutation("R02", "repair", "Manufacturer address added",
             [R("insert", text="12 Main St, Portland, OR 97201", at=(328, 840), size=6)],
             {"manufacturer": "pass"}),
    Mutation("R03", "repair", "Serving size given household and metric units",
             [R("replace", "85", "3/4 cup (60g)", size=9, right_align=True)],
             {"serving_size": "pass", "servings_math": "pass"}),
    Mutation("R04", "repair", "Calories corrected to match the macronutrients",
             [R("replace", "Calories 166", "Calories 540")],
             {"calories_atwater": "pass"}, allow=["nf_vs_sheet"]),
    Mutation("R05", "repair", "Calories, sodium and potassium rounded the FDA way",
             [R("replace", "Calories 166", "Calories 170"), R("replace", "Sodium 23mg", "Sodium 25mg"),
              R("replace", "Potassium 23mg", "Potassium 25mg")],
             {"rounding": "pass"}, allow=["nf_vs_sheet"]),
    Mutation("R06", "repair", "Duplicate sunflower seeds removed from the sheet",
             [R("sheet", "B26", "INGREDIENTS: Organic Wholegrain Oat Flakes (79%), Almonds, Pecans, Sunflower Seeds, "
                "Vegetable Oils (in varying proportions), Dried Blueberries, Cranberries, Honey (9%), Coconut Sugar, "
                "Crystallized Ginger (cane sugar), Himalayan Pink Salt. Natural Flavoring.")],
             {"sheet_ingredient_duplicates": "pass"}, allow=["ingredients_match"]),
    Mutation("R07", "repair", "Sheet carbohydrate corrected to the artwork value",
             [R("sheet", "B53", "66g")],
             {"sheet_sugars_gt_carbs": "pass"}),
]
