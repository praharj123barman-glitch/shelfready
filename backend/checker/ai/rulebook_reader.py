"""Turn a rulebook written in plain prose into separate, checkable rules.

The model splits the document into rules and must copy each rule's key
sentence word for word. ``RulebookReader`` keeps only rules whose quote really
appears in the document, so the AI cannot invent a rule; dropped titles are
returned so the UI can say what was dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from ..rules import Rule
from .client import GeminiClient
from .evidence import normalise

MAX_DOCUMENT_CHARS = 60_000
QUOTE_MATCH_CHARS = 80  # the start of the quote must match; models sometimes trim long endings

SYSTEM = """You turn a packaging rules document into a list of separate, checkable rules.
Copy each rule's key sentence verbatim into source_quote. Do not add rules that are not in the document.
Skip background text, definitions and history that do not require anything of the label."""


class ExtractedRule(BaseModel):
    title: str = Field(description="short name of the rule")
    requirement: str = Field(description="what the label must or must not do, one or two sentences")
    source_quote: str = Field(description="sentence copied word for word from the document")


class ExtractedRules(BaseModel):
    rules: list[ExtractedRule]


@dataclass
class RulebookReader:
    client: GeminiClient

    def read(self, document: str, source_name: str, id_prefix: str = "U") -> tuple[list[Rule], list[str]]:
        """Returns (rules kept, titles of rules dropped because their quote is not in the document)."""
        answer = self.client.generate_json(f"DOCUMENT: {source_name}\n\n{document[:MAX_DOCUMENT_CHARS]}", ExtractedRules, SYSTEM)
        text = normalise(document)
        kept: list[Rule] = []
        dropped: list[str] = []
        for number, extracted in enumerate(answer.rules, 1):
            if normalise(extracted.source_quote)[:QUOTE_MATCH_CHARS] in text:
                kept.append(Rule(
                    id=f"{id_prefix}-{number:02d}", title=extracted.title, text=extracted.requirement,
                    source="company", source_name=source_name, citation=f"quote: \"{extracted.source_quote[:160]}\"",
                ))
            else:
                dropped.append(extracted.title)
        return kept, dropped
