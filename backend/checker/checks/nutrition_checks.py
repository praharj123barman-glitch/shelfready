"""Nutrition Facts checks: all arithmetic, so their verdicts are DEFINITE or PASS."""

from __future__ import annotations

import re

from ..models import Evidence, Finding, Verdict
from ..nutrition import DAILY_VALUES, NUTRIENT_NAMES, atwater_calories, expected_dv, expected_rounding
from ..sections import net_quantity_lines
from .base import CheckContext, art_evidence, computed, fmt

CAT = "nutrition"
# nutrients where FDA requires a %DV next to the amount (protein only with a claim)
DV_REQUIRED = [k for k in DAILY_VALUES if k != "protein"]
HOUSEHOLD_UNITS = r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|pieces?|bars?|slices?|pouch|package|oz)\b"
# Atwater factors are approximate, so only a gap this large is treated as proven wrong
ATWATER_TOLERANCE = 0.20


def check_panel_present(ctx: CheckContext) -> list[Finding]:
    if ctx.nf is None:
        return [
            ctx.finding(
                "nf_present", CAT, Verdict.DEFINITE, "No Nutrition Facts panel found",
                "US packaged food needs a Nutrition Facts panel. None was found in the artwork text.",
                rule_id="FDA-101.9-DV",
            )
        ]
    title = ctx.line(ctx.nf.title_line_id)
    verdict = Verdict.PASS if ctx.nf.footnote_present else Verdict.LIKELY
    note = "with the required %DV footnote" if ctx.nf.footnote_present else "but the %DV footnote is missing"
    return [
        ctx.finding(
            "nf_present", CAT, verdict, f"Nutrition Facts panel present {note}",
            f"Found on the {ctx.nf.panel} panel.", rule_id="FDA-101.9-DV", evidence=[art_evidence([title])],
        )
    ]


def check_serving_size(ctx: CheckContext) -> list[Finding]:
    nf = ctx.nf
    if nf is None:
        return []
    lines = [ctx.line(i) for i in nf.serving_size_line_ids]
    text = (nf.serving_size_text or "").strip()
    has_metric = re.search(r"\d\s*(g|ml)\b", text, re.I)
    has_household = re.search(HOUSEHOLD_UNITS, text, re.I)
    if has_metric and has_household:
        return [ctx.finding("serving_size", CAT, Verdict.PASS, f"Serving size '{text}' has household and metric units",
                            "Serving size is declared correctly.", rule_id="FDA-101.9-SERVING", evidence=[art_evidence(lines)])]
    missing = [n for n, ok in (("a household measure (e.g. '2/3 cup')", has_household), ("a metric amount in grams", has_metric)) if not ok]
    return [
        ctx.finding(
            "serving_size", CAT, Verdict.DEFINITE, f"Serving size '{text or '(blank)'}' has no unit",
            "Shoppers cannot tell what a serving is. FDA requires " + " and ".join(missing) + ".",
            rule_id="FDA-101.9-SERVING", found=text, expected="e.g. '3/4 cup (60g)'",
            fix="Declare the serving as household measure plus grams, e.g. '3/4 cup (60g)'.",
            evidence=[art_evidence(lines)],
        )
    ]


def _net_grams(ctx: CheckContext) -> float | None:
    for ln in net_quantity_lines(ctx.art):
        if m := re.search(r"(\d+(?:\.\d+)?)\s*g\b", ln.text, re.I):
            return float(m.group(1))
    return None


def check_servings_math(ctx: CheckContext) -> list[Finding]:
    nf = ctx.nf
    if nf is None or nf.servings_per_container is None:
        return []
    net = _net_grams(ctx)
    text = nf.serving_size_text or ""
    # '3/4 cup (60g)': the grams are the metric amount; a bare '85' is read as grams
    m = re.search(r"([\d.]+)\s*g\b", text) or re.fullmatch(r"\s*([\d.]+)\s*", text)
    if net is None or m is None:
        return [ctx.finding("servings_math", CAT, Verdict.REVIEW, "Could not verify servings per container",
                            "Net weight or serving size in grams was not found, so servings x serving size cannot be checked.",
                            rule_id="FDA-101.9-SERVINGS")]
    serving = float(m.group(1))
    unit_given = "g" in (nf.serving_size_text or "").lower()
    total = serving * nf.servings_per_container
    evidence = [art_evidence([ctx.line(nf.servings_line_id)] + [ctx.line(i) for i in nf.serving_size_line_ids]),
                computed(f"{fmt(nf.servings_per_container)} servings x {fmt(serving)} g = {fmt(total)} g, net weight is {fmt(net)} g")]
    if abs(total - net) / net <= 0.05:
        return [ctx.finding("servings_math", CAT, Verdict.PASS, "Servings per container match the net weight",
                            f"{fmt(nf.servings_per_container)} x {fmt(serving)} g is {fmt(total)} g, matching {fmt(net)} g.",
                            rule_id="FDA-101.9-SERVINGS", evidence=evidence)]
    assumption = "" if unit_given else " (reading the unitless '85' as grams)"
    return [
        ctx.finding(
            "servings_math", CAT, Verdict.DEFINITE if unit_given else Verdict.LIKELY,
            "Servings x serving size does not equal the net weight",
            f"{fmt(nf.servings_per_container)} servings of {fmt(serving)} g{assumption} is {fmt(total)} g, but the pack holds {fmt(net)} g. "
            f"Either the serving size or the servings count is wrong; {fmt(net)} g / {fmt(nf.servings_per_container)} = {fmt(round(net / nf.servings_per_container, 1))} g per serving.",
            rule_id="FDA-101.9-SERVINGS", expected=f"{fmt(round(net / nf.servings_per_container, 1))} g per serving",
            found=f"{fmt(serving)} per serving", evidence=evidence, confidence=1.0 if unit_given else 0.8,
        )
    ]


def check_calories(ctx: CheckContext) -> list[Finding]:
    nf = ctx.nf
    n = nf.nutrients if nf else {}
    if nf is None or nf.calories is None or not all(k in n for k in ("total_fat", "total_carbohydrate", "protein")):
        return []
    fat, carb, prot = n["total_fat"].amount, n["total_carbohydrate"].amount, n["protein"].amount
    calc = atwater_calories(fat, carb, prot)
    gap = abs(nf.calories - calc) / calc if calc else 0
    lines = [ctx.line(nf.calories_line_id)] + [ctx.line(n[k].line_id) for k in ("total_fat", "total_carbohydrate", "protein")]
    evidence = [art_evidence(lines), computed(f"9 x {fmt(fat)} + 4 x {fmt(carb)} + 4 x {fmt(prot)} = {fmt(calc)} kcal")]
    if gap <= ATWATER_TOLERANCE:
        return [ctx.finding("calories_atwater", CAT, Verdict.PASS, "Calories are consistent with fat, carbohydrate and protein",
                            f"Declared {fmt(nf.calories)} vs calculated {fmt(calc)} kcal.", rule_id="FDA-101.9-CALORIES", evidence=evidence)]
    return [
        ctx.finding(
            "calories_atwater", CAT, Verdict.DEFINITE, f"Calories {fmt(nf.calories)} cannot come from these macronutrients",
            f"{fmt(fat)} g fat, {fmt(carb)} g carbohydrate and {fmt(prot)} g protein give about {fmt(calc)} kcal, "
            f"{round(gap * 100)}% away from the {fmt(nf.calories)} declared. At least one of these numbers is wrong.",
            rule_id="FDA-101.9-CALORIES", expected=f"about {fmt(calc)} kcal", found=fmt(nf.calories), evidence=evidence,
            fix="Re-run the nutrition calculation and update Calories, Total Fat, Total Carbohydrate and Protein together.",
        )
    ]


def check_rounding(ctx: CheckContext) -> list[Finding]:
    nf = ctx.nf
    if nf is None:
        return []
    rows, lines = [], []
    items = [("calories", "Calories", nf.calories, "", nf.calories_line_id)] + [
        (k, v.label, v.amount, v.unit, v.line_id) for k, v in nf.nutrients.items()
    ]
    for key, label, amount, unit, line_id in items:
        if amount is None:
            continue
        exp = expected_rounding(key, amount)
        if exp is not None and abs(exp - amount) > 1e-9:
            rows.append({"item": label, "found": f"{fmt(amount)}{unit}", "expected": f"{fmt(exp)}{unit}"})
            lines.append(ctx.line(line_id))
    if not rows:
        return [ctx.finding("rounding", CAT, Verdict.PASS, "Nutrient amounts follow FDA rounding increments",
                            "Every declared amount is a valid rounded value.", rule_id="FDA-101.9-ROUNDING")]
    return [
        ctx.finding(
            "rounding", CAT, Verdict.DEFINITE, f"{len(rows)} value(s) not rounded the FDA way",
            "FDA fixes the increments label values are rounded to. "
            + "; ".join(f"{r['item']} should read {r['expected']}" for r in rows) + ".",
            rule_id="FDA-101.9-ROUNDING", details=rows, evidence=[art_evidence([l]) for l in lines],
        )
    ]


def check_daily_values(ctx: CheckContext) -> list[Finding]:
    nf = ctx.nf
    if nf is None:
        return []
    rows, lines, missing = [], [], []
    for key in DAILY_VALUES:
        v = nf.nutrients.get(key)
        if v is None:
            continue
        exp = expected_dv(key, v.amount)
        if v.dv_percent is None:
            if key in DV_REQUIRED:
                missing.append(v.label)
            continue
        decimal = "." in (v.dv_text or "")
        # 1 point of slack: FDA lets %DV be computed from the unrounded amount
        if decimal or abs(exp - v.dv_percent) > 1:
            rows.append({"item": v.label, "found": v.dv_text, "expected": f"{fmt(exp)}%",
                         "math": f"{fmt(v.amount)}{v.unit} / {fmt(DAILY_VALUES[key][0])}{DAILY_VALUES[key][1]}"})
            lines += [ctx.line(v.line_id), ctx.line(v.dv_line_id)]
    findings = []
    if rows:
        findings.append(
            ctx.finding(
                "daily_values", CAT, Verdict.DEFINITE, f"{len(rows)} %Daily Value figure(s) are wrong",
                "Each %DV is the amount divided by the FDA reference value. "
                + "; ".join(f"{r['item']}: {r['found']} printed, {r['expected']} correct" for r in rows) + ".",
                rule_id="FDA-101.9-DV", details=rows, evidence=[art_evidence([l]) for l in lines if l],
                fix="Recalculate every %DV from the final amounts.",
            )
        )
    if missing:
        findings.append(ctx.finding("daily_values_missing", CAT, Verdict.DEFINITE, "%DV missing for " + ", ".join(missing),
                                    "These nutrients must show a %Daily Value.", rule_id="FDA-101.9-DV"))
    if not findings:
        findings.append(ctx.finding("daily_values", CAT, Verdict.PASS, "%Daily Values are correct",
                                    "Every %DV matches the amount and FDA reference value.", rule_id="FDA-101.9-DV"))
    return findings


def check_subtotals(ctx: CheckContext) -> list[Finding]:
    nf = ctx.nf
    if nf is None:
        return []
    n = nf.nutrients
    rules = [
        (["saturated_fat", "trans_fat"], "total_fat"),
        (["dietary_fiber", "total_sugars"], "total_carbohydrate"),
        (["added_sugars"], "total_sugars"),
    ]
    bad = []
    for parts, total in rules:
        if total not in n or not any(p in n for p in parts):
            continue
        s = sum(n[p].amount for p in parts if p in n)
        if s > n[total].amount + 1e-9:
            bad.append((parts, total, s))
    if not bad:
        return [ctx.finding("subtotals", CAT, Verdict.PASS, "Nutrient parts do not exceed their totals",
                            "Fats, carbohydrates and sugars add up.", rule_id="FDA-101.9-SUBTOTALS")]
    out = []
    for parts, total, s in bad:
        names = " + ".join(n[p].label for p in parts if p in n)
        out.append(ctx.finding(
            "subtotals", CAT, Verdict.DEFINITE, f"{names} is more than {n[total].label}",
            f"These are part of {n[total].label}, so together ({fmt(s)} {n[total].unit}) they cannot exceed it.",
            rule_id="FDA-101.9-SUBTOTALS", evidence=[art_evidence([ctx.line(n[p].line_id) for p in parts if p in n] + [ctx.line(n[total].line_id)])],
        ))
    return out


def check_against_sheet(ctx: CheckContext) -> list[Finding]:
    """DF-02: every Nutrition Facts amount must equal the approved per serving value."""
    if ctx.nf is None or ctx.spec is None or not ctx.spec.nutrition:
        return []
    approved = {}
    for row in ctx.spec.nutrition:
        key = "calories" if row.name.lower() == "calories" else NUTRIENT_NAMES.get(row.name.lower().replace("incl. ", ""))
        if key:
            approved[key] = row
    printed = {k: (v.amount, v.unit, v.line_id) for k, v in ctx.nf.nutrients.items()}
    if ctx.nf.calories is not None:
        printed["calories"] = (ctx.nf.calories, "", ctx.nf.calories_line_id)

    rows, evidence = [], []
    for key, row in approved.items():
        if key not in printed:
            continue
        amount, unit, line_id = printed[key]
        m = re.match(r"([\d.]+)", row.amount)
        if m and abs(float(m.group(1)) - amount) > 1e-9:
            rows.append({"item": row.name, "artwork": f"{fmt(amount)}{unit}", "approved": row.amount, "cell": row.cell})
            evidence += [art_evidence([ctx.line(line_id)]),
                         Evidence(source="content_sheet", text=f"{row.name} {row.amount}", cell=row.cell)]
    if not rows:
        return [ctx.finding("nf_vs_sheet", CAT, Verdict.PASS, "Nutrition Facts match the approved content sheet",
                            f"All {len(approved)} values agree.", rule_id="DF-02")]
    return [
        ctx.finding(
            "nf_vs_sheet", CAT, Verdict.DEFINITE, f"{len(rows)} Nutrition Facts value(s) differ from the approved sheet",
            "; ".join(f"{r['item']}: artwork {r['artwork']}, approved {r['approved']} ({r['cell']})" for r in rows) + ".",
            rule_id="DF-02", details=rows, evidence=evidence,
            fix="Confirm which value is correct and update either the artwork or the content sheet.",
        )
    ]


CHECKS = [
    check_panel_present,
    check_serving_size,
    check_servings_math,
    check_calories,
    check_rounding,
    check_daily_values,
    check_subtotals,
    check_against_sheet,
]
