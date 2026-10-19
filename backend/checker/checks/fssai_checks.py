"""India: FSSAI labelling and Legal Metrology requirements, from the artwork text.

These run only when the FSSAI rule pack is loaded. Graphic marks (veg symbol,
FSSAI logo, Jaivik Bharat) are judged in ai/marks.py; this module covers what
the text can prove.
"""

from __future__ import annotations

import re

from ..models import Finding, TextLine, Verdict
from ..sections import may_contain_items, net_quantity_lines, split_ingredients
from ..vocabulary import INDIA_ALLERGENS
from .registry import check
from .base import CheckContext, art_evidence, block_evidence, sheet_evidence

CAT = "mandatory"
def _find(ctx: CheckContext, pattern: str, panel: str | None = None) -> list[TextLine]:
    rx = re.compile(pattern, re.I)
    return [ln for ln in ctx.art.copy_lines(panel) if rx.search(ln.text)]


def _missing(ctx, check, rule, title, why, fix, verdict=Verdict.DEFINITE) -> Finding:
    return ctx.finding(check, CAT, verdict, title, why, rule_id=rule, fix=fix)


@check("FSSAI-LICENSE")
def check_licence(ctx: CheckContext) -> list[Finding]:
    hits = [ln for ln in ctx.art.copy_lines() if re.search(r"(?<!\d)\d{14}(?!\d)", ln.text.replace(" ", ""))]
    if hits:
        return [ctx.finding("fssai_licence", CAT, Verdict.PASS, "FSSAI licence number present",
                            hits[0].text, rule_id="FSSAI-LICENSE", evidence=[art_evidence(hits[:1])])]
    return [_missing(ctx, "fssai_licence", "FSSAI-LICENSE", "No FSSAI licence number",
                     "No 14-digit FSSAI licence or registration number appears anywhere on the pack. It is mandatory for "
                     "every packaged food sold in India.", "Add the FSSAI logo with 'Lic. No. ' and the 14-digit number.")]


@check("FSSAI-NUTRITION")
def check_nutrition_per_100g(ctx: CheckContext) -> list[Finding]:
    rx = r"per\s*100\s*(g|gm|ml)\b"
    visible = _find(ctx, rx)
    if visible:
        return [ctx.finding("fssai_nutrition", "nutrition", Verdict.PASS, "Nutrition declared per 100 g",
                            visible[0].text, rule_id="FSSAI-NUTRITION", evidence=[art_evidence(visible[:1])])]
    hidden_match = any(ln.hidden and re.search(rx, ln.text, re.I) for ln in ctx.art.lines)
    # quote the whole hidden table, not only its 'per 100g' heading
    hidden = [ln for ln in ctx.art.lines if ln.hidden and ln.role == "copy"] if hidden_match else []
    why = ("The only nutrition panel is the US Nutrition Facts, which is per serving. India requires values per 100 g "
           "(energy in kcal, protein, carbohydrate, total and added sugars, fat, saturated and trans fat, cholesterol, sodium).")
    if hidden:
        why += " A per-100 g table does exist in the file, but it is hidden under the US panel, so shoppers cannot see it."
    return [ctx.finding("fssai_nutrition", "nutrition", Verdict.DEFINITE, "No visible nutrition table per 100 g", why,
                        rule_id="FSSAI-NUTRITION", evidence=[art_evidence(hidden, text=" | ".join(l.text for l in hidden))] if hidden else [],
                        fix="Add a per-100 g nutrition table in the FSSAI format.")]


@check("FSSAI-DATE-MARK")
def check_date_marking(ctx: CheckContext) -> list[Finding]:
    out = []
    use_by = _find(ctx, r"\b(use\s*by|expiry|exp\.?\s*date|expires)\b")
    best = _find(ctx, r"best\s*before")
    made = _find(ctx, r"\b(mfd|mfg|pkd|manufactur\w*\s*(on|date)|packed\s*on|date\s*of\s*(manufacture|packing))\b")
    if not use_by:
        why = "No 'Use by' or 'Expiry' declaration was found." + (
            f" The pack only says '{best[0].text}'; in India best before may be added but does not replace use by or expiry." if best else "")
        out.append(ctx.finding("fssai_use_by", CAT, Verdict.LIKELY, "No 'Use by' or 'Expiry' date declaration", why,
                               rule_id="FSSAI-DATE-MARK", evidence=[art_evidence(best[:1])] if best else [],
                               fix="Add 'Use by: see base of pack' (or the expiry date) next to the best before line."))
    if not made:
        out.append(_missing(ctx, "fssai_mfd", "FSSAI-DATE-MARK", "No date of manufacture or packing",
                            "Indian labels must state the date of manufacture or packing (for example 'Mfd. on' or 'Pkd. on'); "
                            "nothing like it was found.", "Add 'Mfd./Pkd. on: see base of pack'.", Verdict.LIKELY))
    return out or [ctx.finding("fssai_dates", CAT, Verdict.PASS, "Date marking present", "Use by and manufacture or packing date found.",
                               rule_id="FSSAI-DATE-MARK")]


@check("FSSAI-LM-MRP")
def check_mrp(ctx: CheckContext) -> list[Finding]:
    hits = _find(ctx, r"\b(m\.?\s*r\.?\s*p\.?|maximum\s+retail\s+price)\b")
    if hits:
        return [ctx.finding("fssai_mrp", CAT, Verdict.PASS, "MRP declared", hits[0].text, rule_id="FSSAI-LM-MRP",
                            evidence=[art_evidence(hits[:1])])]
    return [_missing(ctx, "fssai_mrp", "FSSAI-LM-MRP", "No MRP declaration",
                     "Packaged goods in India must show the maximum retail price in rupees, inclusive of all taxes.",
                     "Add 'MRP ₹ ___ (incl. of all taxes)'.")]


@check("FSSAI-LM-CONSUMER-CARE")
def check_consumer_care(ctx: CheckContext) -> list[Finding]:
    hits = _find(ctx, r"(consumer|customer)\s*care|@[\w-]+\.\w+|\b1800[\s-]?\d{3}|(\+91[\s-]?)?\b[6-9]\d{9}\b")
    if hits:
        return [ctx.finding("fssai_consumer_care", CAT, Verdict.PASS, "Consumer care details present", hits[0].text,
                            rule_id="FSSAI-LM-CONSUMER-CARE", evidence=[art_evidence(hits[:1])])]
    return [_missing(ctx, "fssai_consumer_care", "FSSAI-LM-CONSUMER-CARE", "No consumer care details",
                     "No consumer care phone number, email or address was found. Indian packaging must say whom to contact for complaints.",
                     "Add a consumer care block: name, address, phone and email.")]


@check("FSSAI-MFR-ADDRESS")
def check_manufacturer_india(ctx: CheckContext) -> list[Finding]:
    anchor = next(iter(_find(ctx, r"\b(produced|manufactured|marketed|packed|imported)\s+(by|for)\b")), None)
    if anchor is None:
        return [_missing(ctx, "fssai_manufacturer", "FSSAI-MFR-ADDRESS", "No manufacturer statement",
                         "The label must name the manufacturer with its complete address.", "Add 'Manufactured by: <name, full address, PIN>'.")]
    block = [ln for ln in ctx.art.copy_lines(anchor.panel)
             if 0 <= ln.bbox.y0 - anchor.bbox.y0 < 40 and abs(ln.bbox.cx - anchor.bbox.cx) < 80]
    text = " ".join(ln.text for ln in sorted(block, key=lambda l: l.bbox.y0))
    if re.search(r"(?<!\d)\d{3}\s?\d{3}(?!\d)", text):
        return [ctx.finding("fssai_manufacturer", CAT, Verdict.PASS, "Manufacturer address with PIN code present", text,
                            rule_id="FSSAI-MFR-ADDRESS", evidence=[art_evidence(block)])]
    return [ctx.finding("fssai_manufacturer", CAT, Verdict.DEFINITE, "Manufacturer statement has no complete address",
                        f"'{text}' gives no address or PIN code. India requires the complete address of the manufacturer.",
                        rule_id="FSSAI-MFR-ADDRESS", evidence=[art_evidence(block)], found=text,
                        fix="Add the full address with PIN code, and the FSSAI licence number.")]


@check("FSSAI-LM-NET-QTY")
def check_net_quantity_india(ctx: CheckContext) -> list[Finding]:
    qty = net_quantity_lines(ctx.art)
    if not qty:
        return [_missing(ctx, "fssai_net_qty", "FSSAI-LM-NET-QTY", "No net quantity declaration",
                         "The net quantity in metric units is mandatory.", "Add 'Net Qty: 480 g' to the front panel.")]
    metric = [q for q in qty if re.search(r"\d\s*(g|kg|ml|l)\b", q.text, re.I)]
    ev = [art_evidence([q]) for q in qty[:2]]
    if not any(q.panel == "front" for q in metric):
        return [ctx.finding("fssai_net_qty", CAT, Verdict.DEFINITE,
                            f"Net quantity is only on the {qty[0].panel} panel, not the front",
                            f"'{qty[0].text}' is in metric units, which India accepts, but it must be on the principal display panel.",
                            rule_id="FSSAI-LM-NET-QTY", evidence=ev, fix="Add 'Net Qty: 480 g' to the front panel.")]
    return [ctx.finding("fssai_net_qty", CAT, Verdict.PASS, "Net quantity in metric units on the front", metric[0].text,
                        rule_id="FSSAI-LM-NET-QTY", evidence=ev)]


@check("FSSAI-ALLERGEN")
def check_allergens_india(ctx: CheckContext) -> list[Finding]:
    ing = ctx.blocks.get("ingredients")
    items = split_ingredients(ing.text) if ing else []
    present = {k: sorted({m.group(0) for i in items for m in re.finditer(rx, i, re.I)}) for k, rx in INDIA_ALLERGENS.items()}
    present = {k: v for k, v in present.items() if v}
    if not present:
        return []
    contains = _find(ctx, r"\bcontains?\s*:")
    named = "; ".join(f"{k} ({', '.join(v)})" for k, v in present.items())
    out: list[Finding] = []
    if not contains:
        out.append(ctx.finding(
            "fssai_contains", "allergens", Verdict.DEFINITE, "No 'Contains' allergen declaration",
            f"The ingredients include {named}. India requires these to be declared separately as allergens; the pack only "
            "has 'may contain' statements, which cover cross-contact, not ingredients.",
            rule_id="FSSAI-ALLERGEN", evidence=[block_evidence(ing, named)] if ing else [],
            fix="Add 'Contains: Tree nuts (almonds, pecans, walnuts), cereals containing gluten (oats)'.",
        ))
    block = ctx.blocks.get("allergen_information")
    if block:
        ing_text = " ".join(items).lower()
        stems = [(m, re.sub(r"\s+nuts?$", "", m.lower()).rstrip("s")) for m in may_contain_items(block.text)]
        both = [m for m, st in stems if st not in {"", "nut"} and st in ing_text]
        if both:
            out.append(ctx.finding(
                "fssai_may_contain_ingredient", "allergens", Verdict.DEFINITE,
                f"'May contain' used for {', '.join(both)}, which are ingredients",
                "A precautionary 'may contain' line is for cross-contact only and does not replace the allergen declaration.",
                rule_id="FSSAI-ALLERGEN", evidence=[block_evidence(block)],
            ))
    return out


@check("FSSAI-ORGANIC")
def check_organic_india(ctx: CheckContext) -> list[Finding]:
    claim = ctx.claim_lines(r"\b(certified\s+organic|usda\s+organic|organic)\b")
    approved = (ctx.spec.value("front_back_panel_claims_certifications") or "").lower() if ctx.spec else ""
    if not claim and "organic" not in approved:
        return []
    if _find(ctx, r"jaivik\s*bharat|india\s*organic"):
        return [ctx.finding("fssai_organic", "claims", Verdict.PASS, "Indian organic certification mark referenced", "",
                            rule_id="FSSAI-ORGANIC")]
    return [ctx.finding(
        "fssai_organic", "claims", Verdict.LIKELY, "Organic claim without the Jaivik Bharat logo",
        "The pack claims organic (and carries the USDA Organic seal), but organic food sold in India must be certified under "
        "an Indian system and show the Jaivik Bharat logo. A US seal alone does not meet that. (The seal check is by text; "
        "the image check confirms marks.)",
        rule_id="FSSAI-ORGANIC", evidence=[art_evidence(claim[:2])] if claim else [],
        fix="Certify under NPOP/PGS-India and add the Jaivik Bharat logo, or drop the organic claim for India.",
    )]


@check("CORE-DATA")
def check_market_matches_sheet(ctx: CheckContext) -> list[Finding]:
    if ctx.spec is None:
        return []
    sheet_market = (ctx.spec.value("country_of_market") or "").strip()
    rule_markets = {r.market for r in ctx.rules.rules if r.market and r.market != "any"}
    if not sheet_market or not rule_markets or any(m.lower() in sheet_market.lower() for m in rule_markets):
        return []
    return [ctx.finding(
        "market_mismatch", "source_data", Verdict.REVIEW,
        f"Content sheet is for {sheet_market}, rules are for {', '.join(sorted(rule_markets))}",
        "The approved content sheet was written for a different market than the rules being applied. Findings may reflect the "
        "market difference rather than artwork errors; a localised content sheet is needed.",
        rule_id="CORE-DATA", evidence=[e for e in [sheet_evidence(ctx.spec, "country_of_market")] if e],
    )]

