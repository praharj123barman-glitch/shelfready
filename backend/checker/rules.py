"""Load rule sets: built-in regulation packs (JSON) and company rulebooks (Markdown).

A rulebook written as "### <ID> <Title>" sections is parsed exactly. Free-form
documents with no IDs are handed to the AI rule extractor instead
(see ai/rulebook_reader.py), so we never invent rule IDs from a heading guess.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

RULE_HEADING = re.compile(r"^#{2,4}\s+([A-Z][A-Z0-9]*-[A-Z0-9.\-]+)\s+(.+?)\s*$", re.M)


class RuleError(ValueError):
    """A rule file could not be read."""


class Rule(BaseModel):
    id: str
    title: str
    text: str
    source: Literal["regulation", "company"]
    source_name: str
    citation: str | None = None
    url: str | None = None
    market: str | None = None  # from the rule pack, e.g. 'United States', 'India', 'any'


# The same requirement can come from different rule sources. When the rule a
# check cites is not loaded, the first loaded equivalent is used instead, so a
# company rulebook (DF-*) and the market-independent core pack (CORE-*) both
# work, and India's FSSAI rules take over US ones where the requirement is shared.
EQUIVALENT_RULES: dict[str, tuple[str, ...]] = {
    "DF-01": ("CORE-COPY",),
    "DF-02": ("CORE-COPY",),
    "DF-04": ("CORE-COPY",),
    "DF-06": ("CORE-HIDDEN",),
    "DF-10": ("CORE-DIELINE",),
    "DF-11": ("CORE-FOLDS",),
    "DF-03": ("FSSAI-VEGAN",),
    "FDA-101.4": ("FSSAI-INGREDIENTS",),
    "FDA-101.60-NAS": ("FSSAI-CLAIM-NAS",),
    "FDA-101.9-SUBTOTALS": ("CORE-DATA",),
}


class RuleSet(BaseModel):
    rules: list[Rule]

    def get(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def resolve(self, rule_id: str | None) -> str | None:
        """The loaded rule to cite for `rule_id`: itself, or its first loaded equivalent."""
        if rule_id is None or self.get(rule_id):
            return rule_id
        return next((alt for alt in EQUIVALENT_RULES.get(rule_id, ()) if self.get(alt)), rule_id)

    def merged(self, other: "RuleSet") -> "RuleSet":
        ids = {r.id for r in self.rules}
        return RuleSet(rules=self.rules + [r for r in other.rules if r.id not in ids])


def load_regulation_pack(path: str | Path) -> RuleSet:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuleError(f"Rule pack not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RuleError(f"Rule pack {path.name} is not valid JSON: {exc}") from exc
    # uploaded files can be any JSON: check the shape and say what is wrong instead of failing with a 500
    if not isinstance(data, dict) or not isinstance(data.get("rules", []), list):
        raise RuleError(f"Rule pack {path.name} must be a JSON object with a \"rules\" list (see rules/us_fda_food.json)")
    common = {"source": data.get("source", "regulation"), "source_name": data.get("name", path.stem), "market": data.get("market")}
    rules = []
    for i, entry in enumerate(data.get("rules", []), start=1):
        if not isinstance(entry, dict):
            raise RuleError(f"Rule pack {path.name}: rule {i} must be an object with id, title and text")
        try:
            rules.append(Rule(**{**common, **entry}))
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])
            raise RuleError(f"Rule pack {path.name}: rule {i} is invalid ({problems})") from exc
    return RuleSet(rules=rules)


def parse_markdown_rulebook(text: str, source_name: str) -> RuleSet:
    """Parse '### ID Title' sections. Returns an empty set for free-form text."""
    matches = list(RULE_HEADING.finditer(text))
    rules: list[Rule] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = re.sub(r"\s+", " ", text[m.end() : end]).strip()
        rules.append(Rule(id=m.group(1), title=m.group(2), text=body, source="company", source_name=source_name))
    return RuleSet(rules=rules)


def load_rulebook(path: str | Path) -> RuleSet:
    path = Path(path)
    if not path.exists():
        raise RuleError(f"Rulebook not found: {path.name}")
    text = path.read_text(encoding="utf-8", errors="replace")
    title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem)
    return parse_markdown_rulebook(text, title)
