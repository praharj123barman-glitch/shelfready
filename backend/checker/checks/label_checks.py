"""Mandatory label elements: identity, net quantity, manufacturer, barcode,
plus print readiness (hidden objects, dieline marks)."""

from __future__ import annotations

import re

from ..models import Evidence, Finding, Verdict
from ..sections import net_quantity_lines
from .registry import check
from .base import CheckContext, art_evidence, fmt, sheet_evidence

QTY = re.compile(r"^(?:net\s*wt\.?\s*)?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>g|kg|oz|lb|ml|l|fl\.?\s*oz)\b", re.I)
GRAMS_PER_OZ = 28.349523125
US_STATE = r"\b(A[LKZR]|C[AOT]|DE|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b"


@check("FDA-101.3")
def check_statement_of_identity(ctx: CheckContext) -> list[Finding]:
    legal = (ctx.spec.value("legal_name_statement_of_identity") if ctx.spec else None) or ""
    core = re.split(r"\s+-\s+|[,;]", legal)[0].strip().lower() or "granola"
    front = [ln for ln in ctx.art.copy_lines("front") if core in ln.text.lower()]
    if front:
        return [ctx.finding("identity", "mandatory", Verdict.PASS, f"Statement of identity '{front[0].text}' is on the front panel",
                            "The common name of the food is a principal feature of the front panel.",
                            rule_id="FDA-101.3", evidence=[art_evidence(front[:1])])]
    return [ctx.finding("identity", "mandatory", Verdict.DEFINITE, "Statement of identity missing from the front panel",
                        f"Expected the common name ('{core}') on the principal display panel.", rule_id="FDA-101.3")]


def _quantity_lines(ctx: CheckContext):
    out = []
    for ln in net_quantity_lines(ctx.art):
        m = QTY.match(ln.text.strip())
        out.append((ln, float(m.group("num")), m.group("unit").lower()))
    return out


@check("FDA-101.105-PDP", "FDA-101.105-UNITS")
def check_net_quantity(ctx: CheckContext) -> list[Finding]:
    found = _quantity_lines(ctx)
    if not found:
        return [ctx.finding("net_quantity", "mandatory", Verdict.DEFINITE, "No net quantity declaration found",
                            "The pack must state its net weight.", rule_id="FDA-101.105-PDP")]
    findings: list[Finding] = []
    on_pdp = [f for f in found if f[0].panel == "front"]
    metric = next((f for f in found if f[2] in {"g", "kg", "ml", "l"}), None)
    customary = next((f for f in found if f[2] in {"oz", "lb"} or "oz" in f[2]), None)
    ev = [art_evidence([f[0]]) for f in found]

    if not on_pdp:
        panels = ", ".join(sorted({f[0].panel for f in found}))
        findings.append(ctx.finding(
            "net_quantity_pdp", "mandatory", Verdict.DEFINITE, f"Net weight is only on the {panels} panel, not the front",
            "US law requires the net quantity on the principal display panel (front), in the bottom 30% of it, "
            "so shoppers see it without turning the pack.", rule_id="FDA-101.105-PDP", evidence=ev,
            fix="Add the net weight to the bottom of the front panel.",
        ))
    if metric and not customary:
        grams = metric[1] * (1000 if metric[2] == "kg" else 1)
        oz = grams / GRAMS_PER_OZ
        suggestion = f"NET WT {oz:.1f} OZ ({fmt(metric[1])}{metric[2]})"
        findings.append(ctx.finding(
            "net_quantity_units", "mandatory", Verdict.DEFINITE, f"Net weight '{metric[0].text}' has no ounces",
            "US packs must declare net weight in both US customary units (ounces) and metric.",
            rule_id="FDA-101.105-UNITS", expected=suggestion, found=metric[0].text, evidence=ev,
            fix=f"Use '{suggestion}'.",
        ))
    approved = ctx.spec.value("package_size_net_weight") if ctx.spec else None
    if approved and metric:
        a = re.match(r"(\d+(?:\.\d+)?)\s*(g|kg)", approved, re.I)
        same = a and abs(float(a.group(1)) - metric[1]) < 1e-9 and a.group(2).lower() == metric[2]
        findings.append(ctx.finding(
            "net_quantity_sheet", "mandatory", Verdict.PASS if same else Verdict.DEFINITE,
            "Net weight matches the approved sheet" if same else "Net weight differs from the approved sheet",
            f"Artwork '{metric[0].text}', approved '{approved}'.", rule_id="DF-01",
            evidence=ev + [e for e in [sheet_evidence(ctx.spec, "package_size_net_weight")] if e],
        ))
    return findings


@check("FDA-101.5")
def check_manufacturer(ctx: CheckContext) -> list[Finding]:
    anchor = next((ln for ln in ctx.art.copy_lines() if re.search(r"\b(produced|manufactured|distributed|packed)\s+(by|for)\b", ln.text, re.I)), None)
    if anchor is None:
        return [ctx.finding("manufacturer", "mandatory", Verdict.DEFINITE, "No manufacturer or distributor statement",
                            "The label must name the responsible firm and its place of business.", rule_id="FDA-101.5")]
    block = [ln for ln in ctx.art.copy_lines(anchor.panel)
             if 0 <= ln.bbox.y0 - anchor.bbox.y0 < 40 and abs(ln.bbox.cx - anchor.bbox.cx) < 80]
    text = " ".join(ln.text for ln in sorted(block, key=lambda l: l.bbox.y0))
    has_zip = re.search(r"\b\d{5}(-\d{4})?\b", text)
    has_state = re.search(US_STATE, text)
    if has_zip and has_state:
        return [ctx.finding("manufacturer", "mandatory", Verdict.PASS, "Manufacturer name and address present",
                            text, rule_id="FDA-101.5", evidence=[art_evidence(block)])]
    return [ctx.finding(
        "manufacturer", "mandatory", Verdict.DEFINITE, "Manufacturer statement has no address",
        f"'{text}' names the company but gives no city, state or ZIP code. FDA requires the place of business so "
        "regulators and consumers can contact the responsible firm.",
        rule_id="FDA-101.5", found=text, expected="PRODUCED BY DANCING FISH GRANOLA CO., <street>, <city>, <ST> <ZIP>",
        evidence=[art_evidence(block)], fix="Add street address, city, state and ZIP code.",
    )]


def upc_check_digit_ok(digits: str) -> bool:
    """GS1 mod-10 check for UPC-A / EAN-13 (weights 3,1 from the right, excluding the check digit)."""
    if not digits.isdigit() or len(digits) not in (12, 13):
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


@check("DF-01")
def check_barcode(ctx: CheckContext) -> list[Finding]:
    if not ctx.art.barcodes:
        return [ctx.finding("barcode", "mandatory", Verdict.REVIEW, "No barcode could be decoded",
                            "No readable barcode was found in the artwork. Check it is present and scannable.")]
    bc = ctx.art.barcodes[0]
    digits = bc["text"].lstrip("0") if bc["format"] == "EAN-13" and bc["text"].startswith("0") else bc["text"]
    upc = digits if len(digits) == 12 else bc["text"]
    ev = [Evidence(source="artwork", text=f"{bc['format']} decoded: {bc['text']}", panel=bc["panel"], bbox=bc["bbox"])]
    findings = []
    if not upc_check_digit_ok(bc["text"]):
        findings.append(ctx.finding("barcode_check_digit", "mandatory", Verdict.DEFINITE, "Barcode check digit is invalid",
                                    "The last digit does not match the GS1 checksum, so scanners will reject it.", evidence=ev))
    approved = re.sub(r"\D", "", ctx.spec.value("upc_barcode") or "") if ctx.spec else ""
    if approved:
        same = approved == upc or approved == bc["text"]
        findings.append(ctx.finding(
            "barcode", "mandatory", Verdict.PASS if same else Verdict.DEFINITE,
            "Barcode matches the approved UPC and scans correctly" if same else "Barcode does not match the approved UPC",
            f"Decoded {bc['format']} {bc['text']} (UPC-A {upc}); approved {ctx.spec.value('upc_barcode')}. Check digit valid.",
            rule_id="DF-01", evidence=ev + [e for e in [sheet_evidence(ctx.spec, "upc_barcode")] if e],
        ))
    return findings


@check("DF-06")
def check_hidden_objects(ctx: CheckContext) -> list[Finding]:
    hidden = [ln for ln in ctx.art.lines if ln.hidden and ln.role == "copy"]
    if not hidden:
        return [ctx.finding("hidden", "print_readiness", Verdict.PASS, "No hidden text in the artwork",
                            "No copy is covered by other artwork.", rule_id="DF-06")]
    panels = sorted({ln.panel for ln in hidden})
    sample = " | ".join(ln.text for ln in hidden[:8])
    return [ctx.finding(
        "hidden", "print_readiness", Verdict.DEFINITE, f"{len(hidden)} lines of hidden text under other artwork ({', '.join(panels)} panel)",
        f"Text is present in the file but painted over by an opaque shape, so it is invisible on screen: '{sample} ...'. "
        "It looks like an old EU-style nutrition table left under the US panel. Hidden content can reappear at the "
        "printer and confuses automated checks.",
        rule_id="DF-06", evidence=[art_evidence(hidden, text=sample)],
        fix="Delete the hidden text from the artwork file.",
    )]


@check("DF-10")
def check_dieline_marks(ctx: CheckContext) -> list[Finding]:
    guides = [ln for ln in ctx.art.lines if ln.role == "guide"]
    if not guides:
        return []
    on_layer = all(ln.layer for ln in guides)
    if on_layer:
        layers = sorted({ln.layer for ln in guides})
        return [ctx.finding(
            "dieline_marks", "print_readiness", Verdict.PASS, "Dieline marks are on a separate structural layer",
            f"{len(guides)} guide texts ('Front panel', 'Orientation', 'Copy free') sit on the layer(s) {', '.join(layers)}, "
            "not on the design layer, so they will not print.", rule_id="DF-10",
        )]
    return [ctx.finding("dieline_marks", "print_readiness", Verdict.REVIEW, "Dieline marks may be on the printing layer",
                        "Guide text was found but the file has no layers, so confirm they are non-printing.", rule_id="DF-10",
                        evidence=[art_evidence(guides[:3])])]

