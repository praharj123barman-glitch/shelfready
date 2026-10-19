"""Reviewer feedback that changes the next review.

* A false alarm on a finding becomes a waiver for that artwork file and that
  problem. Waived findings stay in the report, marked with the reason, and no
  longer block the launch verdict. Nothing is deleted silently.
* A false alarm on an AI finding also becomes a guidance note on the rule; the
  note is given to the AI on every later review, so the same misreading is not
  repeated (the "read the transcript, fix the prompt" loop).

Storage is a JSON file, which is enough for a prototype with one reviewer.
"""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .models import Finding
from .rules import RuleSet

STORE = Path(__file__).resolve().parents[1] / "runs" / "feedback.json"
_LOCK = threading.Lock()


class Waiver(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    artwork_sha256: str
    artwork_name: str
    check: str
    problem: str  # finding title with numbers removed, so "3 values" and "2 values" match
    reason: str
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class RuleNote(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    rule_id: str
    note: str
    created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class FeedbackStore(BaseModel):
    waivers: list[Waiver] = []
    rule_notes: list[RuleNote] = []
    accepted: list[dict] = []


def problem_key(title: str) -> str:
    return re.sub(r"\d+(\.\d+)?", "#", title).strip().lower()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(store: Path = STORE) -> FeedbackStore:
    if not store.exists():
        return FeedbackStore()
    try:
        return FeedbackStore.model_validate_json(store.read_text(encoding="utf-8"))
    except ValueError:
        # a corrupt file must not stop reviews; keep it for inspection and start fresh
        store.rename(store.with_suffix(".corrupt.json"))
        return FeedbackStore()


def save(data: FeedbackStore, store: Path = STORE) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_suffix(".tmp")
    tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(store)  # atomic on the same disk


def record(finding: Finding, decision: str, reason: str, artwork_path: Path, store: Path = STORE) -> dict:
    """Store a reviewer decision and return what it changed."""
    with _LOCK:
        data = load(store)
        if decision == "accepted":
            data.accepted.append({"check": finding.check, "problem": problem_key(finding.title), "rule_id": finding.rule_id})
            save(data, store)
            return {"saved": True, "waiver": None, "rule_note": None}
        waiver = Waiver(
            artwork_sha256=file_sha256(artwork_path), artwork_name=artwork_path.name, check=finding.check,
            problem=problem_key(finding.title), reason=reason.strip() or "Marked as a false alarm by the reviewer",
        )
        data.waivers.append(waiver)
        note = None
        if finding.method == "ai" and finding.rule_id and reason.strip():
            note = RuleNote(rule_id=finding.rule_id, note=reason.strip())
            data.rule_notes.append(note)
        save(data, store)
        return {"saved": True, "waiver": waiver.model_dump(), "rule_note": note.model_dump() if note else None}


def carry_waivers(previous_artwork: Path, new_artwork: Path, store: Path = STORE) -> int:
    """A new proof of the same job keeps the reviewer's waivers: a false alarm
    dismissed on v1 should not come back on v2. Returns how many were carried."""
    old_sha, new_sha = file_sha256(previous_artwork), file_sha256(new_artwork)
    if old_sha == new_sha:
        return 0
    with _LOCK:
        data = load(store)
        existing = {(w.check, w.problem) for w in data.waivers if w.artwork_sha256 == new_sha}
        carried = [
            Waiver(artwork_sha256=new_sha, artwork_name=new_artwork.name, check=w.check, problem=w.problem,
                   reason=f"{w.reason} (carried over from {w.artwork_name})")
            for w in data.waivers
            if w.artwork_sha256 == old_sha and (w.check, w.problem) not in existing
        ]
        data.waivers.extend(carried)
        save(data, store)
        return len(carried)


def remove_waiver(waiver_id: str, store: Path = STORE) -> bool:
    with _LOCK:
        data = load(store)
        before = len(data.waivers)
        data.waivers = [w for w in data.waivers if w.id != waiver_id]
        save(data, store)
        return len(data.waivers) < before


def apply_waivers(findings: list[Finding], artwork_path: Path, store: Path = STORE) -> list[Finding]:
    sha = file_sha256(artwork_path)
    waivers = {(w.check, w.problem): w for w in load(store).waivers if w.artwork_sha256 == sha}
    out = []
    for f in findings:
        w = waivers.get((f.check, problem_key(f.title)))
        out.append(f.model_copy(update={"waiver": w.model_dump()}) if w and f.verdict.value != "pass" else f)
    return out


def with_rule_notes(rules: RuleSet, store: Path = STORE) -> RuleSet:
    """Append reviewer guidance to the rule text the AI reads."""
    notes: dict[str, list[str]] = {}
    for n in load(store).rule_notes:
        notes.setdefault(n.rule_id, []).append(n.note)
    if not notes:
        return rules
    return RuleSet(rules=[
        r.model_copy(update={"text": r.text + " Reviewer guidance from earlier reviews: " + " ".join(notes[r.id])})
        if r.id in notes else r
        for r in rules.rules
    ])
