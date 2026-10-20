"""Reviewer feedback that changes the next review.

* A false alarm on a finding becomes a **waiver** for that artwork file and that
  problem. Waived findings stay in the report, marked with the reason, and no
  longer block the launch verdict. Nothing is deleted silently.
* A false alarm on an AI finding also becomes a **rule note**: guidance the AI
  reads on every later review, so the same misreading is not repeated (the
  "read the transcript, fix the prompt" loop).
* Comparing a new proof carries the waivers over, so dismissed false alarms do
  not come back on v2.

``FeedbackStore`` owns one JSON file; that is enough for a prototype with one
reviewer (a database would replace it for a team).
"""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .models import Finding
from .rules import RuleSet

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "runs" / "feedback.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def problem_key(title: str) -> str:
    """A finding title with numbers removed, so '3 values not rounded' and
    '2 values not rounded' count as the same problem."""
    return re.sub(r"\d+(\.\d+)?", "#", title).strip().lower()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Waiver(BaseModel):
    id: str = Field(default_factory=_new_id)
    artwork_sha256: str  # waivers belong to one exact file version
    artwork_name: str
    check: str
    problem: str  # see problem_key()
    reason: str
    created: str = Field(default_factory=_now)


class RuleNote(BaseModel):
    id: str = Field(default_factory=_new_id)
    rule_id: str
    note: str
    created: str = Field(default_factory=_now)


class FeedbackData(BaseModel):
    """Everything in the feedback file."""

    waivers: list[Waiver] = []
    rule_notes: list[RuleNote] = []
    accepted: list[dict] = []


class FeedbackStore:
    """Reviewer decisions, persisted in one JSON file. All writes are locked and atomic."""

    _lock = threading.Lock()  # one lock for all stores: they may share a file

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = Path(path)

    # ---------------- reading and writing ----------------

    def load(self) -> FeedbackData:
        if not self.path.exists():
            return FeedbackData()
        try:
            return FeedbackData.model_validate_json(self.path.read_text(encoding="utf-8"))
        except ValueError:
            # a corrupt file must not stop reviews; keep it for inspection and start fresh
            self.path.rename(self.path.with_suffix(".corrupt.json"))
            return FeedbackData()

    def _save(self, data: FeedbackData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)  # atomic on the same disk

    # ---------------- reviewer actions ----------------

    def record(self, finding: Finding, decision: Literal["accepted", "false_alarm"], reason: str, artwork: Path) -> dict:
        """Store a reviewer decision and return what it changed (the waiver and/or rule note)."""
        with self._lock:
            data = self.load()
            if decision == "accepted":
                data.accepted.append({"check": finding.check, "problem": problem_key(finding.title), "rule_id": finding.rule_id})
                self._save(data)
                return {"saved": True, "waiver": None, "rule_note": None}
            sha, problem = file_sha256(artwork), problem_key(finding.title)
            why = reason.strip() or "Marked as a false alarm by the reviewer"
            # one waiver per file and problem: a repeated click updates it, so a single undo removes it
            waiver = next((w for w in data.waivers if (w.artwork_sha256, w.check, w.problem) == (sha, finding.check, problem)), None)
            if waiver:
                waiver.reason = why
            else:
                waiver = Waiver(artwork_sha256=sha, artwork_name=artwork.name, check=finding.check, problem=problem, reason=why)
                data.waivers.append(waiver)
            note = None
            if finding.method == "ai" and finding.rule_id and reason.strip():
                note = next((n for n in data.rule_notes if (n.rule_id, n.note) == (finding.rule_id, reason.strip())), None)
                if note is None:
                    note = RuleNote(rule_id=finding.rule_id, note=reason.strip())
                    data.rule_notes.append(note)
            self._save(data)
            return {"saved": True, "waiver": waiver.model_dump(), "rule_note": note.model_dump() if note else None}

    def remove_waiver(self, waiver_id: str) -> bool:
        with self._lock:
            data = self.load()
            before = len(data.waivers)
            data.waivers = [w for w in data.waivers if w.id != waiver_id]
            self._save(data)
            return len(data.waivers) < before

    def carry_waivers(self, previous_artwork: Path, new_artwork: Path) -> int:
        """Copy the previous proof's waivers to a new proof of the same job. Returns how many were added."""
        old_sha, new_sha = file_sha256(previous_artwork), file_sha256(new_artwork)
        if old_sha == new_sha:
            return 0
        with self._lock:
            data = self.load()
            existing = {(w.check, w.problem) for w in data.waivers if w.artwork_sha256 == new_sha}
            carried = [
                Waiver(artwork_sha256=new_sha, artwork_name=new_artwork.name, check=w.check, problem=w.problem,
                       reason=f"{w.reason} (carried over from {w.artwork_name})")
                for w in data.waivers
                if w.artwork_sha256 == old_sha and (w.check, w.problem) not in existing
            ]
            data.waivers.extend(carried)
            self._save(data)
            return len(carried)

    # ---------------- applying feedback to a review ----------------

    def apply_waivers(self, findings: list[Finding], artwork: Path) -> list[Finding]:
        """Mark findings this artwork file has waivers for (they stay in the list)."""
        sha = file_sha256(artwork)
        waivers = {(w.check, w.problem): w for w in self.load().waivers if w.artwork_sha256 == sha}
        out = []
        for f in findings:
            waiver = waivers.get((f.check, problem_key(f.title)))
            out.append(f.model_copy(update={"waiver": waiver.model_dump()}) if waiver and f.verdict.value != "pass" else f)
        return out

    def with_rule_notes(self, rules: RuleSet) -> RuleSet:
        """The rules with reviewer guidance appended, for the AI to read."""
        notes: dict[str, list[str]] = {}
        for n in self.load().rule_notes:
            notes.setdefault(n.rule_id, []).append(n.note)
        if not notes:
            return rules
        return RuleSet(rules=[
            r.model_copy(update={"text": r.text + " Reviewer guidance from earlier reviews: " + " ".join(notes[r.id])})
            if r.id in notes else r
            for r in rules.rules
        ])
