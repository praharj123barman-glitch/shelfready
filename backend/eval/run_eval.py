"""Mutation eval: does the checker catch injected defects and recognise fixes,
without raising alarms anywhere else?

Run:  python -m eval.run_eval      (from backend/, code checks only, ~2 min)
Writes eval/results.json and eval/RESULTS.md.
"""

from __future__ import annotations

import json
import re
import shutil

import time
from pathlib import Path

from checker.artwork import read_artwork
from checker.content_sheet import read_content_sheet
from checker.engine import run_checks
from checker.rules import load_regulation_pack, load_rulebook

from .mutations import MUTATIONS, Mutation, apply_pdf, apply_sheet

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
XLSX = ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"
OUT = Path(__file__).resolve().parent
WORK = Path(__file__).resolve().parents[1] / "runs" / "eval_work"
RANK = {"pass": 0, "review": 1, "likely": 2, "definite": 3}


def rules():
    return load_regulation_pack(ROOT / "rules" / "us_fda_food.json").merged(
        load_rulebook(ROOT / "rules" / "dancing_fish_company_rulebook.md")
    )


FAIL = {"definite", "likely"}


def problem_key(title: str) -> str:
    """'3 value(s) not rounded' and '2 value(s) not rounded' are the same problem
    with a different count, so numbers are dropped before comparing titles."""
    return re.sub(r"\d+(\.\d+)?", "#", title)


def state_by_check(pdf: Path, xlsx: Path) -> dict[str, tuple[str, frozenset]]:
    """Per check: its worst verdict and the set of failing problems.
    Problems matter: a new problem inside an already-failing check (a second
    unapproved claim) changes them even though the verdict stays the same."""
    report = run_checks(read_artwork(pdf), rules(), read_content_sheet(xlsx))
    state: dict[str, tuple[str, frozenset]] = {}
    for f in report.findings:
        v = f.verdict.value
        worst, titles = state.get(f.check, ("pass", frozenset()))
        state[f.check] = (v if RANK[v] > RANK[worst] else worst, titles | ({problem_key(f.title)} if v in FAIL else set()))
    return state


def _new_problem(before, after) -> bool:
    if after is None or after[0] not in FAIL:
        return False
    return before is None or RANK[after[0]] > RANK[before[0]] or bool(after[1] - before[1])


def judge(m: Mutation, base: dict, after: dict) -> dict:
    outcomes = {}
    for check, want in m.expect.items():
        b, a = base.get(check), after.get(check)  # None: the check produced no finding
        ok = _new_problem(b, a) if want == "fail" else (a is None or a[0] == "pass")
        outcomes[check] = {"wanted": want, "before": b and b[0], "after": a and a[0], "ok": ok}
    # any other check reporting a new or worse problem is a false alarm
    collateral = [
        {"check": c, "before": base.get(c) and base[c][0], "after": a[0]}
        for c, a in after.items()
        if c not in m.expect and c not in m.allow and _new_problem(base.get(c), a)
    ]
    return {"id": m.id, "kind": m.kind, "description": m.description, "outcomes": outcomes,
            "caught": all(o["ok"] for o in outcomes.values()), "false_alarms": collateral}


def run() -> dict:
    base = state_by_check(PDF, XLSX)
    results = []
    # a plain folder, not a TemporaryDirectory: Windows will not delete PDFs the
    # checker's page cache still has open
    WORK.mkdir(parents=True, exist_ok=True)  # runs/ is not in git: a fresh clone has no such folder yet
    for m in MUTATIONS:
        pdf, xlsx = WORK / f"{m.id}.pdf", WORK / f"{m.id}.xlsx"
        pdf_edits = [e for e in m.edits if e.kind != "sheet"]
        sheet_edits = [e for e in m.edits if e.kind == "sheet"]
        apply_pdf(PDF, pdf, pdf_edits) if pdf_edits else shutil.copy(PDF, pdf)
        apply_sheet(XLSX, xlsx, sheet_edits) if sheet_edits else shutil.copy(XLSX, xlsx)
        t = time.time()
        results.append({**judge(m, base, state_by_check(pdf, xlsx)), "seconds": round(time.time() - t, 1)})
        r = results[-1]
        print(f"{m.id} {'OK ' if r['caught'] else 'MISS'} fa={len(r['false_alarms'])} {m.description}")
    detect = [r for r in results if r["kind"] == "detect"]
    repair = [r for r in results if r["kind"] == "repair"]
    summary = {
        "detected": f"{sum(r['caught'] for r in detect)}/{len(detect)}",
        "repairs_recognised": f"{sum(r['caught'] for r in repair)}/{len(repair)}",
        "false_alarms": sum(len(r["false_alarms"]) for r in results),
        "mutations": len(results),
    }
    return {"summary": summary, "baseline": {c: v[0] for c, v in base.items()}, "results": results}


def write_markdown(data: dict) -> str:
    s = data["summary"]
    rows = "\n".join(
        f"| {r['id']} | {r['kind']} | {r['description']} | {', '.join(f'{c}: {o['before'] or '-'} -> {o['after'] or 'gone'}' for c, o in r['outcomes'].items())} "
        f"| {'yes' if r['caught'] else 'NO'} | {len(r['false_alarms'])} |"
        for r in data["results"]
    )
    fa = [f"- {r['id']}: {a['check']} {a['before']} -> {a['after']}" for r in data["results"] for a in r["false_alarms"]]
    return f"""# Mutation eval (code checks)

Each row edits the real Esko sample (PDF text via redaction, or one content-sheet cell) and runs the full
pipeline: PDF extraction, then every check. A detection counts only if the expected check newly fails;
a repair counts only if the expected finding goes away. Any other check that gets worse is a false alarm.

**Detected:** {s['detected']}  ·  **Repairs recognised:** {s['repairs_recognised']}  ·  **False alarms:** {s['false_alarms']} across {s['mutations']} mutations

| ID | Kind | Edit | Expected check (before -> after) | OK | False alarms |
|---|---|---|---|---|---|
{rows}

{"## False alarms" + chr(10) + chr(10).join(fa) if fa else "No false alarms."}

## Bugs this eval found in the checker (all fixed)

The first run scored 12/16 detected, 6/7 repairs and 1 false alarm. Reading every miss found five real
checker bugs, not just eval noise:

1. Servings math read the first number of '3/4 cup (60g)' (3) instead of the grams (60).
2. With '480g' gone, the net-weight check picked up '3.8g' from the EU fat icon as the pack weight.
   Nutrient amounts are now excluded from net quantity detection.
3. Face names came only from dieline guide labels; deleting one ('Back panel') made the back face
   disappear. Unlabelled faces are now named from geometry (wide column with the largest type is the front).
4. The net quantity height check measured the first quantity found, not the one on the front panel.
5. A legal 'NET WT 16.9 OZ (480g)' declaration was flagged as unapproved marketing copy.

AI checks (rulebook reasoning, marks) are not part of this run; they are evaluated by their evidence
verification, see README.
"""


if __name__ == "__main__":
    data = run()
    (OUT / "results.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (OUT / "RESULTS.md").write_text(write_markdown(data), encoding="utf-8")
    print(json.dumps(data["summary"]))
