"""Follow-up questions about one finding.

The assistant answers from the finding, its rule, its evidence and the
artwork text only. Cited line ids are checked; if the answer leans on lines
that do not exist, the reply says so instead of passing it off as grounded.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..checks.base import CheckContext
from ..models import Finding
from .client import generate_json
from .rule_checker import artwork_digest, sheet_digest

SYSTEM = """You are a calm, precise packaging compliance reviewer answering a colleague's question about one finding.
Answer only from the FINDING, RULE, ARTWORK TEXT and APPROVED SHEET provided.
If the answer is not in them, say plainly that the artwork and documents do not show it and what a human should check.
Keep it short: 2 to 4 sentences, one idea per sentence. Plain words, no jargon unless the user uses it, no exclamation marks.
When you rely on an artwork line, list its id in cited_line_ids. Never invent regulations or numbers."""


class ChatAnswer(BaseModel):
    answer: str
    cited_line_ids: list[str] = Field(default_factory=list)
    needs_human: bool = Field(description="true when the documents cannot settle the question")


class ChatTurn(BaseModel):
    role: str
    text: str


def answer_question(ctx: CheckContext, finding: Finding, question: str, history: list[ChatTurn] | None = None) -> ChatAnswer:
    past = "\n".join(f"{t.role}: {t.text}" for t in (history or [])[-6:])
    prompt = (
        f"FINDING ({finding.verdict.value}, {finding.method}): {finding.title}\n{finding.explanation}\n"
        f"Expected: {finding.expected or '-'} | Found: {finding.found or '-'} | Fix: {finding.fix or '-'}\n"
        f"Evidence: {[e.text for e in finding.evidence]}\nDetails: {finding.details}\n\n"
        f"RULE {finding.rule_id or '-'}: {finding.rule_text or '-'}\n\n"
        f"ARTWORK TEXT\n{artwork_digest(ctx)}\n\nAPPROVED SHEET\n{sheet_digest(ctx)}\n\n"
        + (f"CONVERSATION SO FAR\n{past}\n\n" if past else "")
        + f"QUESTION: {question}"
    )
    # chat replies are not cached: the same question in a new context deserves a fresh answer
    ans = generate_json(prompt, ChatAnswer, SYSTEM, temperature=0.2, use_cache=False)
    bad = [i for i in ans.cited_line_ids if ctx.line(i) is None]
    if bad:
        ans.cited_line_ids = [i for i in ans.cited_line_ids if i not in bad]
        ans.answer += f" (Note: this answer referred to artwork lines that do not exist: {', '.join(bad)}. Treat it with care.)"
        ans.needs_human = True
    return ans
