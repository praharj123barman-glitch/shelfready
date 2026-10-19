"""Compare two proofs of the same artwork: what text changed, and which issues
the new proof resolved, introduced or left open."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .feedback import problem_key
from .models import Artwork, BBox, Finding, TextLine

SAME_PLACE = 3.0  # pt: a line this close to its old position has not moved
MIN_OVERLAP = 0.3  # share of the smaller box two lines must overlap to be "the same slot"


class TextChange(BaseModel):
    kind: Literal["added", "removed", "changed", "moved"]
    panel: str
    before: str | None = None
    after: str | None = None
    before_bbox: BBox | None = None
    after_bbox: BBox | None = None


class IssueChange(BaseModel):
    status: Literal["resolved", "introduced", "still_open"]
    check: str
    title: str
    verdict: str
    rule_id: str | None = None
    method: Literal["deterministic", "ai"] = "deterministic"


class Comparison(BaseModel):
    before: str
    after: str
    text_changes: list[TextChange]
    issues: list[IssueChange]
    summary: dict[str, int]


def _overlap(a: BBox, b: BBox) -> float:
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0)) or 1
    return w * h / smaller


def _near(a: BBox, b: BBox) -> bool:
    return abs(a.x0 - b.x0) <= SAME_PLACE and abs(a.y0 - b.y0) <= SAME_PLACE


def diff_text(before: Artwork, after: Artwork) -> list[TextChange]:
    old = [l for l in before.copy_lines(include_hidden=True)]
    new = [l for l in after.copy_lines(include_hidden=True)]
    used: set[str] = set()

    def take(pred) -> TextLine | None:
        hit = next((n for n in new if n.id not in used and pred(n)), None)
        if hit:
            used.add(hit.id)
        return hit

    changes: list[TextChange] = []
    unmatched: list[TextLine] = []
    for o in old:  # unchanged first: same text in the same place
        if not take(lambda n: n.text == o.text and n.panel == o.panel and _near(n.bbox, o.bbox)):
            unmatched.append(o)
    still: list[TextLine] = []
    for o in unmatched:  # same text elsewhere: moved
        n = take(lambda n: n.text == o.text)
        if n:
            changes.append(TextChange(kind="moved", panel=n.panel, before=o.text, after=n.text, before_bbox=o.bbox, after_bbox=n.bbox))
        else:
            still.append(o)
    for o in still:  # different text in the same slot: changed; otherwise removed
        # same hidden/visible status only: hidden text sits under visible text by definition
        n = take(lambda n: n.panel == o.panel and n.hidden == o.hidden and _overlap(n.bbox, o.bbox) >= MIN_OVERLAP)
        if n:
            changes.append(TextChange(kind="changed", panel=n.panel, before=o.text, after=n.text, before_bbox=o.bbox, after_bbox=n.bbox))
        else:
            changes.append(TextChange(kind="removed", panel=o.panel, before=o.text, before_bbox=o.bbox))
    changes += [TextChange(kind="added", panel=n.panel, after=n.text, after_bbox=n.bbox) for n in new if n.id not in used]
    order = {"changed": 0, "added": 1, "removed": 2, "moved": 3}
    return sorted(changes, key=lambda c: (order[c.kind], c.panel))


def _key(f: Finding) -> tuple:
    # code findings are reproducible, so their wording identifies the problem;
    # AI wording varies between runs and models, so AI findings match by check (rule) only
    return (f.check,) if f.method == "ai" else (f.check, problem_key(f.title))


def diff_issues(before: list[Finding], after: list[Finding]) -> list[IssueChange]:
    def problems(fs):
        # waived problems are still the same problems: a waiver changing between proofs
        # must not make a problem look introduced or resolved
        return {_key(f): f for f in fs if f.verdict.value in {"definite", "likely"}}

    def change(status, f):
        return IssueChange(status=status, check=f.check, title=f.title, verdict=f.verdict.value, rule_id=f.rule_id, method=f.method)

    b, a = problems(before), problems(after)
    out = [change("resolved", f) for k, f in b.items() if k not in a]
    out += [change("introduced", f) for k, f in a.items() if k not in b]
    out += [change("still_open", f) for k, f in a.items() if k in b]
    return out


def compare(before_art: Artwork, after_art: Artwork, before: list[Finding], after: list[Finding]) -> Comparison:
    text = diff_text(before_art, after_art)
    issues = diff_issues(before, after)
    summary = {k: sum(1 for c in text if c.kind == k) for k in ("changed", "added", "removed", "moved")}
    # headline counts are code-checked only: reproducible from run to run
    summary.update({k: sum(1 for i in issues if i.status == k and i.method == "deterministic")
                    for k in ("resolved", "introduced", "still_open")})
    summary["ai_changes"] = sum(1 for i in issues if i.status != "still_open" and i.method == "ai")
    return Comparison(before=before_art.file_name, after=after_art.file_name, text_changes=text, issues=issues, summary=summary)
