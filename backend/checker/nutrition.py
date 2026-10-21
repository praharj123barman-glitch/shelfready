"""Read the US Nutrition Facts panel off the artwork and the FDA reference math.

Values come straight from the panel's text lines. %DV figures sit in a right
hand column, so each one is paired with the nutrient on the same row.
"""

from __future__ import annotations

import math
import re

from pydantic import BaseModel

from .models import Artwork, TextLine

# FDA reference daily values for adults and children 4+ (21 CFR 101.9(c)(8)(iv), (c)(9))
DAILY_VALUES = {
    "total_fat": (78, "g"),
    "saturated_fat": (20, "g"),
    "cholesterol": (300, "mg"),
    "sodium": (2300, "mg"),
    "total_carbohydrate": (275, "g"),
    "dietary_fiber": (28, "g"),
    "added_sugars": (50, "g"),
    "protein": (50, "g"),
    "vitamin_d": (20, "mcg"),
    "calcium": (1300, "mg"),
    "iron": (18, "mg"),
    "potassium": (4700, "mg"),
}
VITAMINS_MINERALS = {"vitamin_d", "calcium", "iron", "potassium"}

NUTRIENT_NAMES = {
    "total fat": "total_fat",
    "saturated fat": "saturated_fat",
    "trans fat": "trans_fat",
    "cholesterol": "cholesterol",
    "sodium": "sodium",
    "total carbohydrate": "total_carbohydrate",
    "dietary fiber": "dietary_fiber",
    "total sugars": "total_sugars",
    "added sugars": "added_sugars",
    "protein": "protein",
    "vitamin d": "vitamin_d",
    "calcium": "calcium",
    "iron": "iron",
    "potassium": "potassium",
}
AMOUNT = re.compile(r"^(?:incl\.?\s*)?(?P<pre>[\d.]+)?\s*(?P<preunit>mcg|mg|g)?\s*(?P<name>[a-z ]+?)\s*(?P<num>[\d.]+)?\s*(?P<unit>mcg|mg|g)?$", re.I)


class NutrientValue(BaseModel):
    key: str
    label: str
    amount: float
    unit: str
    dv_percent: float | None = None
    dv_text: str | None = None
    line_id: str
    dv_line_id: str | None = None


class NutritionPanel(BaseModel):
    title_line_id: str
    panel: str
    servings_per_container: float | None = None
    servings_line_id: str | None = None
    serving_size_text: str | None = None
    serving_size_line_ids: list[str] = []
    calories: float | None = None
    calories_line_id: str | None = None
    nutrients: dict[str, NutrientValue] = {}
    footnote_present: bool = False


def _parse_amount_line(text: str) -> tuple[str, float, str] | None:
    """'Total Fat 15g' -> ('total_fat', 15, 'g'); 'Incl. 0g Added Sugars' -> ('added_sugars', 0, 'g')."""
    m = AMOUNT.match(text.strip())
    if not m:
        return None
    key = NUTRIENT_NAMES.get(m.group("name").strip().lower())
    num, unit = (m.group("num"), m.group("unit")) if m.group("num") else (m.group("pre"), m.group("preunit"))
    if not key or num is None or unit is None:
        return None
    return key, float(num), unit.lower()


def _same_row(a: TextLine, b: TextLine) -> bool:
    return abs(a.bbox.cy - b.bbox.cy) < 0.6 * max(a.size, b.size)


def _number_right_of(label: TextLine, region: list[TextLine]) -> TextLine | None:
    """A bare number on the same row, to the right of the label ('Calories' ... '166')."""
    return next((o for o in region if o.id != label.id and re.fullmatch(r"\d+(\.\d+)?", o.text.strip())
                 and o.bbox.x0 > label.bbox.x0 and _same_row(o, label)), None)


def nutrition_title(art: Artwork) -> TextLine | None:
    """The 'Nutrition Facts' heading. OCR of a label photo can read the large title as two lines,
    'Nutrition' with 'Facts' below or beside it (found on a real Cheerios label): the 'Nutrition' line
    then stands for the heading."""
    lines = art.copy_lines()
    exact = next((ln for ln in lines if ln.text.strip().lower() == "nutrition facts"), None)
    if exact:
        return exact
    for top in (ln for ln in lines if ln.text.strip().lower() == "nutrition"):
        for facts in (ln for ln in lines if ln.text.strip().lower() == "facts" and ln.panel == top.panel):
            below = 0 < facts.bbox.cy - top.bbox.cy < 2.5 * top.size and abs(facts.bbox.x0 - top.bbox.x0) < 2 * top.size
            beside = abs(facts.bbox.cy - top.bbox.cy) < 0.6 * top.size and 0 <= facts.bbox.x0 - top.bbox.x1 < 2 * top.size
            if below or beside:
                return top
    return None


def read_nutrition_panel(art: Artwork) -> NutritionPanel | None:
    title = nutrition_title(art)
    if title is None:
        return None
    region = [ln for ln in art.copy_lines(title.panel) if ln.bbox.y0 >= title.bbox.y0 - 1 and abs(ln.bbox.cx - title.bbox.cx) < 120]
    panel = NutritionPanel(title_line_id=title.id, panel=title.panel)
    dv_lines = [ln for ln in region if re.fullmatch(r"[\d.]+%\*?", ln.text.strip())]

    for ln in region:
        t = ln.text.strip()
        if m := re.match(r"(?:about\s+)?([\d.]+)\s+servings? per container", t, re.I):
            panel.servings_per_container, panel.servings_line_id = float(m.group(1)), ln.id
        elif t.lower().startswith("serving size"):
            value = [o for o in region if o.id != ln.id and _same_row(o, ln)]
            rest = t[len("serving size"):].strip()
            panel.serving_size_text = " ".join([rest] + [o.text for o in value]).strip()
            panel.serving_size_line_ids = [ln.id] + [o.id for o in value]
        elif m := re.match(r"calories\s+([\d.]+)$", t, re.I):
            panel.calories, panel.calories_line_id = float(m.group(1)), ln.id
        elif t.lower() == "calories" and panel.calories is None and (number := _number_right_of(ln, region)):
            # the large calorie figure set as its own piece of text (or read as one by OCR)
            panel.calories, panel.calories_line_id = float(number.text.strip()), ln.id
        elif re.match(r"\*?\s*the\s*%\s*daily value", t, re.I) or (t.startswith("*") and "daily value" in t.lower()):
            panel.footnote_present = True  # OCR may drop the leading asterisk
        elif parsed := _parse_amount_line(t):
            key, amount, unit = parsed
            dv = next((d for d in dv_lines if _same_row(d, ln)), None)
            panel.nutrients[key] = NutrientValue(
                key=key,
                label=t,
                amount=amount,
                unit=unit,
                dv_percent=float(dv.text.strip().rstrip("*%")) if dv else None,
                dv_text=dv.text.strip() if dv else None,
                line_id=ln.id,
                dv_line_id=dv.id if dv else None,
            )
    return panel


# ---------------- FDA math ----------------


def round_half_up(x: float, step: float) -> float:
    return math.floor(x / step + 0.5) * step


def expected_rounding(key: str, amount: float) -> float | None:
    """The value FDA rounding would produce, or None when the amount is a phrase case."""
    if key == "calories":
        return 0 if amount < 5 else round_half_up(amount, 5 if amount <= 50 else 10)
    if key in {"total_fat", "saturated_fat", "trans_fat"}:
        return 0 if amount < 0.5 else round_half_up(amount, 0.5 if amount < 5 else 1)
    if key == "cholesterol":
        return 0 if amount < 2 else (None if amount <= 5 else round_half_up(amount, 5))
    if key in {"sodium", "potassium"}:
        return 0 if amount < 5 else round_half_up(amount, 5 if amount <= 140 else 10)
    if key in {"total_carbohydrate", "dietary_fiber", "total_sugars", "added_sugars", "protein"}:
        return 0 if amount < 0.5 else (None if amount < 1 else round_half_up(amount, 1))
    return None  # vitamins/minerals amounts: no simple increment rule checked here


def expected_dv(key: str, amount: float) -> float | None:
    if key not in DAILY_VALUES:
        return None
    pct = amount / DAILY_VALUES[key][0] * 100
    if key in VITAMINS_MINERALS:
        step = 2 if pct <= 10 else 5 if pct <= 50 else 10
        return round_half_up(pct, step)
    return round_half_up(pct, 1)


def atwater_calories(fat_g: float, carb_g: float, protein_g: float) -> float:
    return 9 * fat_g + 4 * carb_g + 4 * protein_g


# ---------------- corrected panel ----------------

PANEL_ORDER = [
    "total_fat", "saturated_fat", "trans_fat", "cholesterol", "sodium", "total_carbohydrate",
    "dietary_fiber", "total_sugars", "added_sugars", "protein", "vitamin_d", "calcium", "iron", "potassium",
]
LABELS = {
    "total_fat": "Total Fat", "saturated_fat": "Saturated Fat", "trans_fat": "Trans Fat", "cholesterol": "Cholesterol",
    "sodium": "Sodium", "total_carbohydrate": "Total Carbohydrate", "dietary_fiber": "Dietary Fiber",
    "total_sugars": "Total Sugars", "added_sugars": "Incl. Added Sugars", "protein": "Protein", "vitamin_d": "Vitamin D",
    "calcium": "Calcium", "iron": "Iron", "potassium": "Potassium",
}
INDENTED = {"saturated_fat", "trans_fat", "dietary_fiber", "total_sugars", "added_sugars"}


class CorrectedRow(BaseModel):
    key: str
    label: str
    indent: bool
    printed_amount: str
    amount: str
    printed_dv: str | None
    dv: str | None
    changed: bool


class CorrectedPanel(BaseModel):
    basis: str  # what was assumed, shown to the user
    servings_per_container: float | None
    printed_serving: str | None
    calories_printed: float | None
    calories: float | None
    rows: list[CorrectedRow]


def _fmt(x: float) -> str:
    return f"{x:g}"


def corrected_panel(nf: NutritionPanel) -> CorrectedPanel | None:
    """What the panel must say if the printed amounts are right: amounts rounded
    the FDA way, calories from the 4-4-9 factors, every %DV recomputed."""
    n = nf.nutrients
    if not n:
        return None
    rows = []
    for key in PANEL_ORDER:
        v = n.get(key)
        if v is None:
            continue
        rounded = expected_rounding(key, v.amount)
        amount = v.amount if rounded is None else rounded
        dv = expected_dv(key, amount)
        dv_text = f"{_fmt(dv)}%" if dv is not None and key != "protein" else None
        printed_amount = f"{_fmt(v.amount)}{v.unit}"
        rows.append(CorrectedRow(
            key=key, label=LABELS[key], indent=key in INDENTED, printed_amount=printed_amount,
            amount=f"{_fmt(amount)}{v.unit}", printed_dv=v.dv_text, dv=dv_text,
            changed=f"{_fmt(amount)}{v.unit}" != printed_amount or (dv_text or "") != (v.dv_text or "").rstrip("*"),
        ))
    calories = None
    if all(k in n for k in ("total_fat", "total_carbohydrate", "protein")):
        calories = expected_rounding("calories", atwater_calories(n["total_fat"].amount, n["total_carbohydrate"].amount, n["protein"].amount))
    return CorrectedPanel(
        basis="Computed from the amounts printed on the artwork: FDA rounding, calories from 4-4-9, every %DV recomputed. "
              "The amounts themselves must be confirmed against the recipe first, especially where the content sheet disagrees.",
        servings_per_container=nf.servings_per_container, printed_serving=nf.serving_size_text,
        calories_printed=nf.calories, calories=calories, rows=rows,
    )
