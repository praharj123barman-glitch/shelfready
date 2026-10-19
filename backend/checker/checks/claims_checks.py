"""Claims and allergens: do the claims on the pack agree with what is in it?"""

from __future__ import annotations

import re

from ..models import Finding, Verdict
from ..sections import may_contain_items
from ..vocabulary import ANIMAL_WORDS, SUGAR_WORDS, US_ALLERGENS
from .registry import check
from .base import CheckContext, art_evidence, block_evidence, sheet_evidence

@check("FDA-101.60-NAS")
def check_no_added_sugar(ctx: CheckContext) -> list[Finding]:
    claim = ctx.claim_lines(r"no\s+added\s+sugars?")
    if not claim:
        return []
    sweet = [i for i in ctx.ingredient_items() if re.search(SUGAR_WORDS, i, re.I)]
    if not sweet:
        return [ctx.finding("no_added_sugar", "claims", Verdict.PASS, "'No Added Sugar' is consistent with the ingredients",
                            "No sugar or sweetening ingredient is listed.", rule_id="FDA-101.60-NAS", evidence=[art_evidence(claim)])]
    ev = [art_evidence(claim, "NO ADDED SUGAR (badge)")]
    if b := ctx.blocks.get("ingredients"):
        ev.append(block_evidence(b, ", ".join(sweet)))
    return [ctx.finding(
        "no_added_sugar", "claims", Verdict.DEFINITE, "'No Added Sugar' claim, but the ingredients add sugar",
        f"The pack claims no added sugar while listing {', '.join(sweet)}. Under FDA rules honey and sugars added in "
        "processing are added sugars, so this claim is false and is a misbranding risk.",
        rule_id="FDA-101.60-NAS", found=", ".join(sweet), evidence=ev,
        fix="Remove the 'No Added Sugar' badge, or reformulate without these ingredients.",
    )]


@check("FDA-101.9-ADDED-SUGARS")
def check_added_sugars_zero(ctx: CheckContext) -> list[Finding]:
    added = ctx.nf.nutrients.get("added_sugars") if ctx.nf else None
    if added is None or added.amount > 0:
        return []
    sweet = [i for i in ctx.ingredient_items() if re.search(SUGAR_WORDS, i, re.I)]
    if not sweet:
        return []
    return [ctx.finding(
        "added_sugars_zero", "nutrition", Verdict.LIKELY, "Added Sugars shows 0g but sweeteners are ingredients",
        f"The panel declares 0g added sugars, yet {', '.join(sweet)} are added. 0g is only allowed when a serving has "
        "less than 0.5 g; honey alone at 1% of a serving is close to that, and coconut sugar and cane sugar add more. "
        "Needs the recipe to confirm the real figure.",
        rule_id="FDA-101.9-ADDED-SUGARS", evidence=[art_evidence([ctx.line(added.line_id)])], confidence=0.8,
    )]


@check("DF-03")
def check_vegan(ctx: CheckContext) -> list[Finding]:
    claim = ctx.claim_lines(r"\bvegans?\b")
    approved = (ctx.spec.value("front_back_panel_claims_certifications") or "") if ctx.spec else ""
    if not claim and "vegan" not in approved.lower():
        return []
    findings: list[Finding] = []
    animal = [i for i in ctx.ingredient_items() if re.search(ANIMAL_WORDS, i, re.I)]
    ev = [art_evidence(claim[:3])] if claim else []
    if animal:
        if b := ctx.blocks.get("ingredients"):
            ev.append(block_evidence(b, ", ".join(animal)))
        findings.append(ctx.finding(
            "vegan_ingredients", "claims", Verdict.DEFINITE, f"Vegan claim, but {', '.join(animal)} is animal derived",
            f"The pack says it is suitable for vegans (and the content sheet lists the Certified Vegan mark), but "
            f"{', '.join(animal)} comes from animals. The vegan claim and certification mark cannot stay with this recipe.",
            rule_id="DF-03", found=", ".join(animal), evidence=ev,
            fix="Replace honey with a plant sweetener, or drop the vegan claim and mark.",
        ))
    chol = ctx.nf.nutrients.get("cholesterol") if ctx.nf else None
    if chol and chol.amount > 0:
        findings.append(ctx.finding(
            "vegan_cholesterol", "claims", Verdict.DEFINITE, f"Vegan product declares {chol.label}",
            "Cholesterol only comes from animal foods, so a vegan product should declare 0mg. Either the claim or the value is wrong.",
            rule_id="DF-03", evidence=ev + [art_evidence([ctx.line(chol.line_id)])],
        ))
    if not findings:
        findings.append(ctx.finding("vegan", "claims", Verdict.PASS, "Vegan claim is consistent with ingredients",
                                    "No animal-derived ingredient found.", rule_id="DF-03", evidence=ev))
    return findings


@check("FDCA-403w", "DF-07")
def check_allergens(ctx: CheckContext) -> list[Finding]:
    ingredients = ctx.ingredient_items()
    present = {name: sorted({m.group(0) for i in ingredients for m in re.finditer(rx, i, re.I)})
               for name, rx in US_ALLERGENS.items()}
    present = {k: v for k, v in present.items() if v}
    block = ctx.blocks.get("allergen_information")
    findings: list[Finding] = []

    if present:
        named = "; ".join(f"{k}: {', '.join(v)}" for k, v in present.items())
        findings.append(ctx.finding(
            "allergens_declared", "allergens", Verdict.PASS, "Major allergens are named in the ingredient list",
            f"{named}. FDA accepts allergens declared by their source name in the ingredient list, so no 'Contains' "
            "line is legally required (many brands add one anyway).", rule_id="FDCA-403w",
            evidence=[block_evidence(ctx.blocks["ingredients"], named)] if "ingredients" in ctx.blocks else [],
        ))
    if block is None:
        return findings

    may = may_contain_items(block.text)
    ing_text = " ".join(ingredients).lower()
    # "Pecan Nuts" -> "pecan"; the bare word "Nuts" is handled by the generic-nuts check
    stems = [(m, re.sub(r"\s+nuts?$", "", m.lower()).rstrip("s")) for m in may]
    contradictions = [m for m, stem in stems if stem not in {"", "nut"} and stem in ing_text]
    if contradictions:
        findings.append(ctx.finding(
            "may_contain_ingredient", "allergens", Verdict.DEFINITE,
            f"'May contain' used for {', '.join(contradictions)}, which are ingredients",
            "A 'may contain' line tells allergic shoppers there is only a cross-contact risk. These nuts are actual "
            "ingredients, so the statement understates the risk and contradicts the ingredient list.",
            rule_id="DF-07", evidence=[block_evidence(block)],
            fix="State 'Contains: Tree nuts (almonds, pecans, walnuts)' and keep 'may contain' only for true cross-contact (e.g. Brazil nuts).",
        ))
    if re.search(r"may\s+contain\s+nuts\b", block.text, re.I):
        findings.append(ctx.finding(
            "generic_nuts", "allergens", Verdict.DEFINITE, "Allergen statement uses the generic word 'Nuts'",
            "Tree nuts must be named individually; 'nuts' does not tell a shopper which nut.",
            rule_id="DF-07", evidence=[block_evidence(block, "May Contain Nuts")],
        ))
    eu_terms = [t for t in ("cereals containing gluten", "oats") if re.search(rf"\b{t}\b", block.text, re.I)]
    if eu_terms:
        findings.append(ctx.finding(
            "eu_allergen_terms", "allergens", Verdict.REVIEW, "EU allergen wording on a US pack",
            f"'{', '.join(eu_terms)}' is EU allergen language. Oats and 'cereals containing gluten' are not US major "
            "allergens; wheat is. Check whether wheat cross-contact is the real intent.",
            rule_id="FDCA-403w", evidence=[block_evidence(block)],
        ))
    return findings


@check("DF-08")
def check_gmo_wording(ctx: CheckContext) -> list[Finding]:
    hits = ctx.claim_lines(r"\bgmo[\s-]*free\b")
    if not hits:
        return []
    return [ctx.finding(
        "gmo_wording", "claims", Verdict.LIKELY, "'GMO Free' wording is used",
        "The company rulebook bans 'GMO free' on US packs and only allows 'Non-GMO' with Non-GMO Project "
        "verification. Absolute 'free' claims are hard to substantiate. Send to regulatory review.",
        rule_id="DF-08", evidence=[art_evidence(hits[:4])], fix="Replace with 'Non-GMO Project Verified' if certified.",
    )]


@check("DF-09")
def check_organic(ctx: CheckContext) -> list[Finding]:
    claim = ctx.claim_lines(r"\b(certified\s+organic|usda\s+organic)\b")
    approved = (ctx.spec.value("front_back_panel_claims_certifications") or "") if ctx.spec else ""
    if not claim and "organic" not in approved.lower():
        return []
    items = ctx.ingredient_items()
    organic = [i for i in items if re.search(r"\borganic\b", i, re.I)]
    findings: list[Finding] = []
    ev = [art_evidence(claim[:2])] if claim else []
    if items and len(organic) < len(items):
        findings.append(ctx.finding(
            "organic_ingredients", "claims", Verdict.REVIEW,
            f"Organic claim, but only {len(organic)} of {len(items)} ingredients are marked organic",
            f"Only '{', '.join(organic) or 'none'}' carries the word Organic. The USDA Organic seal needs at least 95% "
            "organic content and each organic ingredient identified. Confirm the certificate covers the others.",
            rule_id="DF-09", evidence=ev + ([block_evidence(ctx.blocks['ingredients'])] if 'ingredients' in ctx.blocks else []),
        ))
    if not ctx.claim_lines(r"certified\s+organic\s+by"):
        findings.append(ctx.finding(
            "organic_certifier", "claims", Verdict.DEFINITE, "Organic claim without 'Certified organic by ...' statement",
            "Products sold as organic must name their certifying agent below the manufacturer statement "
            "(USDA organic rules, restated in the company rulebook). No such statement was found.",
            rule_id="DF-09", evidence=ev, fix="Add 'Certified organic by <certifier>' under the manufacturer line.",
        ))
    return findings


@check("DF-05")
def check_eu_front_of_pack(ctx: CheckContext) -> list[Finding]:
    eu = [ln for ln in ctx.art.copy_lines() if re.fullmatch(r"(saturates|salt|\d+(\.\d+)?kj)", ln.text.strip(), re.I)
          and not (ctx.nf and ln.panel == ctx.nf.panel)]
    if not eu:
        return []
    panel = eu[0].panel
    icons = [ln for ln in ctx.art.copy_lines(panel) if abs(ln.bbox.cx - eu[0].bbox.cx) < 30]
    detail = ""
    fat = next((ln for ln in icons if ln.text.lower() == "fat"), None)
    if fat and ctx.nf and "total_fat" in ctx.nf.nutrients:
        val = next((ln for ln in icons if ln.bbox.y0 > fat.bbox.y0 and re.fullmatch(r"[\d.]+g", ln.text)), None)
        if val:
            detail = f" Its fat figure ({val.text}) also disagrees with Nutrition Facts ({ctx.nf.nutrients['total_fat'].label})."
    return [ctx.finding(
        "eu_front_of_pack", "claims", Verdict.DEFINITE, f"EU-style nutrition icons on the {panel} panel",
        "The icons use EU terms (Saturates, Salt, kJ) that US packs do not use." + detail
        + " Two nutrition statements that disagree confuse shoppers and regulators.",
        rule_id="DF-05", evidence=[art_evidence(icons)],
        fix="Remove the EU icons, or replace with US 'Facts up Front' icons that match the panel per serving.",
    )]


CLAIM_VOCAB = {
    "no added sugar": r"no added sugars?",
    "oven baked": r"oven baked",
    "gmo free": r"gmo free",
    "high-grain": r"high[\s-]grain",
    "gluten free": r"gluten[\s-]free",
}


@check("DF-04")
def check_claims_approved(ctx: CheckContext) -> list[Finding]:
    if ctx.spec is None:
        return []
    approved = (ctx.spec.value("front_back_panel_claims_certifications") or "").lower()
    if not approved:
        return []
    found = []
    for name, rx in CLAIM_VOCAB.items():
        if lines := ctx.claim_lines(rx):
            found.append((name, lines))
    unapproved = [(n, l) for n, l in found if not re.search(CLAIM_VOCAB[n], approved)]
    if not unapproved:
        return [ctx.finding("claims_approved", "claims", Verdict.PASS, "All claims on the pack are on the approved list",
                            ", ".join(n for n, _ in found), rule_id="DF-04")]
    return [ctx.finding(
        "claims_approved", "claims", Verdict.LIKELY,
        "Claim not on the approved claims list: " + ", ".join(f"'{l[0].text}'" for _, l in unapproved),
        "Every claim must come from the approved claims field of the content sheet. "
        + "; ".join(f"'{n}' appears on the pack but not in the list" for n, _ in unapproved)
        + ". (It may be a product descriptor, so a human should confirm.)",
        rule_id="DF-04", evidence=[art_evidence(l[:2]) for _, l in unapproved]
        + [e for e in [sheet_evidence(ctx.spec, "front_back_panel_claims_certifications")] if e],
    )]

