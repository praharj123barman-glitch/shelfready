"""The guardrail: check every piece of evidence the AI cites before trusting it.

The model must back each claim with one of three kinds of evidence:

* text    a line id and words quoted from that line
* visual  a panel name and what it saw in that panel's image
* absent  what it searched for, to show something required is missing

``EvidenceVerifier`` checks each item against the real artwork in code. Text
quotes must appear in the cited line; absence claims are re-checked on the
named panel (or the whole pack); visual evidence must name a real panel (what
is in the image cannot be verified in code, so it carries lower confidence).
A line that reads like an instruction to an AI reviewer is never accepted as
evidence (see injection.py). Anything that fails is reported as a problem, and
the finding is downgraded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ..checks.base import CheckContext, art_evidence
from ..models import Evidence
from .injection import is_instruction


class CitedEvidence(BaseModel):
    """One piece of evidence as the model returns it (this is part of the response schema)."""

    kind: Literal["text", "visual", "absent"]
    line_id: str | None = Field(default=None, description="for kind text: the line id, e.g. L013")
    quote: str | None = Field(default=None, description="for kind text: exact words copied from that line")
    panel: str | None = Field(
        default=None,
        description="kind visual: the exact panel name from the IMAGE caption; kind absent: the panel it is missing from, or empty for the whole pack",
    )
    description: str | None = Field(default=None, description="for kind visual: what is seen in the panel image")
    searched_for: list[str] = Field(
        default_factory=list,
        description="for kind absent: words or symbols that would show the required item if it were present, e.g. ['www', '.com', 'call', '1-800']",
    )


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class EvidenceVerifier:
    ctx: CheckContext

    def verify(self, items: list[CitedEvidence]) -> tuple[list[CitedEvidence], list[str]]:
        """Split cited evidence into what checks out and a list of problems."""
        verified: list[CitedEvidence] = []
        problems: list[str] = []
        for item in items:
            check = {"text": self._check_text, "visual": self._check_visual, "absent": self._check_absent}[item.kind]
            problem = check(item)
            if problem:
                problems.append(problem)
            else:
                verified.append(item)
        return verified, problems

    def to_evidence(self, item: CitedEvidence) -> Evidence:
        """Turn verified evidence into the report's Evidence (with a box to draw)."""
        if item.kind == "absent":
            where = f"the {item.panel} panel text" if item.panel else "all artwork text"
            return Evidence(source="computed", text=f"Verified absent from {where}: " + ", ".join(f"'{t}'" for t in item.searched_for))
        if item.kind == "visual":
            return Evidence(source="artwork", text=f"Seen in image: {item.description}", panel=item.panel,
                            bbox=self.ctx.art.panels[item.panel])
        return art_evidence([self.ctx.line(item.line_id)], text=item.quote)

    # ---------------- one method per kind; each returns a problem or None ----------------

    def _check_text(self, item: CitedEvidence) -> str | None:
        line = self.ctx.line(item.line_id)
        if line is None:
            return f"cited line {item.line_id} does not exist"
        quote, text = normalise(item.quote or ""), normalise(line.text)
        if not quote or (quote not in text and text not in quote):
            return f"quote '{item.quote}' is not in line {item.line_id} ('{line.text}')"
        if is_instruction(line.text):  # the words are on the artwork, but they are an attempt to steer the review
            return f"line {item.line_id} reads like an instruction to an AI reviewer, so it cannot be evidence"
        return None

    def _check_visual(self, item: CitedEvidence) -> str | None:
        if item.panel in self.ctx.art.panels and item.description:
            return None
        return f"visual evidence names an unknown panel '{item.panel}'"

    def _check_absent(self, item: CitedEvidence) -> str | None:
        # "missing from the front" is checked against the front only, not the whole carton
        if item.panel and item.panel not in self.ctx.art.panels:
            return f"absence claimed for an unknown panel '{item.panel}'"
        terms = [normalise(t) for t in item.searched_for if t.strip()]
        if not terms:
            return "absence claimed without saying what was searched for"
        lines = [(ln.id, normalise(ln.text)) for ln in self.ctx.art.copy_lines(item.panel or None)]
        hits = [(line_id, term) for term in terms for line_id, text in lines if term in text]
        if hits:
            return "claimed missing, but " + ", ".join(f"'{term}' is in {line_id}" for line_id, term in hits[:3])
        return None
