"""Artwork vs approved content sheet (DF-01), and ingredient list structure (FDA 101.4)."""

from __future__ import annotations

import difflib
import re

from ..models import Evidence, Finding, Verdict
from ..sections import split_ingredients
from .base import CheckContext, art_evidence, block_evidence, sheet_evidence

PCT = re.compile(r"\((\d+(?:\.\d+)?)%\)")


def norm(text: str) -> str:
    text = re.sub(r"^\s*(ingredients|allergen information|dietary information)\s*:\s*", "", text, flags=re.I)
    return re.sub(r"[\s.]+", " ", text).strip().lower()


def _item_key(item: str) -> str:
    """Compare ingredients by name, ignoring their percentage."""
    return PCT.sub("", item).strip().lower()


REWORD_SIMILARITY = 0.5  # share of distinctive words two names must have in common
GENERIC_WORDS = {"seed", "dried", "organic", "natural", "in", "and", "of", "the", "with"}


def _words(item: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", _item_key(item))} - GENERIC_WORDS


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of distinctive words: 'Sunflower Seeds' vs 'Flax Seeds' is 0,
    'Dried Blueberries' vs 'Blueberries' is 1."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def _pair_rewordings(approved: list[str], artwork: list[str]) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Inside a changed stretch, pair items that are the same ingredient reworded
    ('Dried Blueberries' vs 'Blueberries'); the rest are truly added or missing."""
    pairs, left = [], list(artwork)
    unmatched_approved = []
    for s in approved:
        best = max(left, key=lambda a: similarity(s, a), default=None)
        if best and similarity(s, best) >= REWORD_SIMILARITY:
            pairs.append((s, best))
            left.remove(best)
        else:
            unmatched_approved.append(s)
    return pairs, unmatched_approved, left


def diff_ingredients(artwork: list[str], approved: list[str]) -> list[dict]:
    rows: list[dict] = []
    a_keys, s_keys = [_item_key(i) for i in artwork], [_item_key(i) for i in approved]
    sm = difflib.SequenceMatcher(a=s_keys, b=a_keys, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for s, a in zip(approved[i1:i2], artwork[j1:j2]):
                if s != a:  # same ingredient, different percentage
                    rows.append({"change": "percentage changed", "approved": s, "artwork": a})
            continue
        pairs, missing, added = _pair_rewordings(approved[i1:i2], artwork[j1:j2])
        rows += [{"change": "reworded", "approved": s, "artwork": a} for s, a in pairs]
        for s in missing:
            dup = s_keys.count(_item_key(s)) > 1 and _item_key(s) in a_keys
            rows.append({"change": "duplicate in approved list" if dup else "missing on artwork", "approved": s, "artwork": ""})
        rows += [{"change": "added, not approved", "approved": "", "artwork": a} for a in added]
    return rows


def check_ingredients_match(ctx: CheckContext) -> list[Finding]:
    block = ctx.blocks.get("ingredients")
    approved = ctx.spec.value("ingredient_list") if ctx.spec else None
    if block is None or approved is None:
        return []
    rows = diff_ingredients(split_ingredients(block.text), split_ingredients(approved))
    ev = [block_evidence(block), sheet_evidence(ctx.spec, "ingredient_list")]
    if not rows:
        return [ctx.finding("ingredients_match", "ingredients", Verdict.PASS, "Ingredient list matches the approved sheet",
                            "Word for word.", rule_id="DF-01", evidence=ev)]
    groups: dict[str, list[str]] = {}
    for r in rows:
        item = f"{r['approved']} -> {r['artwork']}" if r["approved"] and r["artwork"] else r["approved"] or r["artwork"]
        groups.setdefault(r["change"], []).append(item)
    summary = "; ".join(f"{change}: {', '.join(items)}" for change, items in groups.items())
    return [ctx.finding(
        "ingredients_match", "ingredients", Verdict.DEFINITE, f"Ingredient list differs from the approved sheet in {len(rows)} place(s)",
        f"{summary}. The recipe on the pack is not the approved one, which also affects allergens, claims and nutrition.",
        rule_id="DF-01", details=rows, evidence=ev,
        fix="Confirm the current recipe, then align the artwork and the content sheet.",
    )]


def check_text_fields(ctx: CheckContext) -> list[Finding]:
    """Short approved texts that must appear verbatim on the pack."""
    if ctx.spec is None:
        return []
    findings: list[Finding] = []
    full = norm(ctx.art.full_text())
    for key, label in [("storage_instructions", "Storage instructions"), ("marketing_copy", "Marketing copy")]:
        value = ctx.spec.value(key)
        if not value:
            continue
        ok = norm(value) in full
        findings.append(ctx.finding(
            f"text_{key}", "copy", Verdict.PASS if ok else Verdict.DEFINITE,
            f"{label} {'matches' if ok else 'does not match'} the approved text",
            f"Approved: '{value}'." + ("" if ok else " This exact text was not found on the artwork."),
            rule_id="DF-01", evidence=[e for e in [sheet_evidence(ctx.spec, key)] if e],
        ))
    for key, label in [("allergen_information", "Allergen statement"), ("dietary_information", "Dietary statement")]:
        block, value = ctx.blocks.get(key), ctx.spec.value(key)
        if not (block and value):
            continue
        same = norm(block.text) == norm(value)
        rows = [] if same else [{"approved": value, "artwork": block.text}]
        findings.append(ctx.finding(
            f"text_{key}", "copy", Verdict.PASS if same else Verdict.DEFINITE,
            f"{label} {'matches' if same else 'differs from'} the approved text",
            "Word for word." if same else f"Artwork: '{block.text}'. Approved: '{value}'.",
            rule_id="DF-01", details=rows, evidence=[block_evidence(block), sheet_evidence(ctx.spec, key)],
        ))
    return findings


def check_unapproved_tagline(ctx: CheckContext) -> list[Finding]:
    """Large display copy that is neither a claim, the product name nor approved marketing copy."""
    if ctx.spec is None:
        return []
    approved = norm(" ".join(filter(None, [ctx.spec.value(k) for k in (
        "marketing_copy", "product_name", "legal_name_statement_of_identity", "front_back_panel_claims_certifications", "product_type")])))
    big = [ln for ln in ctx.art.copy_lines() if ln.size >= 11 and len(ln.text.split()) >= 3]
    odd = [ln for ln in big if norm(ln.text) not in approved and not any(norm(ln.text) in norm(m) for m in [ctx.spec.value("marketing_copy") or ""])]
    seen: dict[str, list] = {}
    for ln in odd:
        seen.setdefault(norm(ln.text), []).append(ln)
    if not seen:
        return []
    return [ctx.finding(
        "unapproved_copy", "copy", Verdict.LIKELY, f"Display copy not in the approved sheet: '{lines[0].text}'",
        f"'{lines[0].text}' appears {len(lines)} time(s) ({', '.join(sorted({l.panel for l in lines}))} panel) but is not in the "
        "approved marketing copy. Taglines usually need the same approval as other copy.",
        rule_id="DF-01", evidence=[art_evidence(lines)],
    ) for lines in seen.values()]


def _duplicates(items: list[str]) -> list[str]:
    keys = [_item_key(i) for i in items]
    return sorted({items[i] for i, k in enumerate(keys) if keys.count(k) > 1})


def check_ingredient_structure(ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    block = ctx.blocks.get("ingredients")
    if block:
        items = split_ingredients(block.text)
        dups = _duplicates(items)
        pcts = [(i, float(m.group(1))) for i in items if (m := PCT.search(i))]
        out_of_order = any(b[1] > a[1] for a, b in zip(pcts, pcts[1:]))
        verdict = Verdict.DEFINITE if dups or out_of_order else Verdict.PASS
        problems = ([f"listed twice: {', '.join(dups)}"] if dups else []) + (["declared percentages are not descending"] if out_of_order else [])
        findings.append(ctx.finding(
            "ingredient_structure", "ingredients", verdict,
            "Ingredient list structure is valid" if verdict == Verdict.PASS else "Ingredient list structure problem",
            "Each ingredient appears once and declared percentages are in descending order."
            if verdict == Verdict.PASS else "; ".join(problems) + ".",
            rule_id="FDA-101.4", evidence=[block_evidence(block)],
        ))
    if ctx.spec and (approved := ctx.spec.value("ingredient_list")):
        dups = _duplicates(split_ingredients(approved))
        if dups:
            findings.append(ctx.finding(
                "sheet_ingredient_duplicates", "source_data", Verdict.REVIEW,
                f"The approved content sheet lists {', '.join(dups)} twice",
                "The source of truth itself has an error. Fix the content sheet before using it to approve artwork.",
                rule_id="FDA-101.4", evidence=[sheet_evidence(ctx.spec, "ingredient_list")],
            ))
    return findings


def check_sheet_consistency(ctx: CheckContext) -> list[Finding]:
    """The approved sheet can be wrong too: impossible numbers and open reviewer notes."""
    if ctx.spec is None:
        return []
    findings: list[Finding] = []
    vals = {}
    for row in ctx.spec.nutrition:
        if m := re.match(r"([\d.]+)", row.amount):
            vals[row.name.lower()] = (float(m.group(1)), row)
    if "total sugars" in vals and "total carbohydrate" in vals and vals["total sugars"][0] > vals["total carbohydrate"][0]:
        s, c = vals["total sugars"][1], vals["total carbohydrate"][1]
        findings.append(ctx.finding(
            "sheet_sugars_gt_carbs", "source_data", Verdict.REVIEW,
            f"Content sheet: Total Sugars {s.amount} is more than Total Carbohydrate {c.amount}",
            "Sugars are part of carbohydrate, so the approved figures are impossible. The sheet must be corrected.",
            rule_id="FDA-101.9-SUBTOTALS",
            evidence=[Evidence(source="content_sheet", text=f"Total Sugars {s.amount}", cell=s.cell),
                      Evidence(source="content_sheet", text=f"Total Carbohydrate {c.amount}", cell=c.cell)],
        ))
    notes = [f for f in ctx.spec.fields.values() if f.note and re.search(r"confirm|verify|assumed|not clearly", f.note, re.I)]
    if notes:
        findings.append(ctx.finding(
            "sheet_open_notes", "source_data", Verdict.REVIEW, f"{len(notes)} open question(s) left in the content sheet",
            "The sheet's own reviewer notes ask for confirmation, so these approved values are not final yet.",
            details=[{"field": f.label, "cell": f.cell, "note": f.note} for f in notes],
            evidence=[Evidence(source="content_sheet", text=f"{f.label}: {f.note}", cell=f.cell) for f in notes],
        ))
    return findings


CHECKS = [
    check_ingredients_match,
    check_text_fields,
    check_unapproved_tagline,
    check_ingredient_structure,
    check_sheet_consistency,
]
