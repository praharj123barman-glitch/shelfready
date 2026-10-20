"""Bad model output, end to end through the real GeminiClient (validation, cache) and pipeline.

Only the network is faked. Whatever the model sends, an AI problem must show up as
'could not be checked' / REVIEW, never as a pass, never as DEFINITE.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from checker.ai.client import AISettings, GeminiClient, ResponseCache
from checker.feedback import FeedbackStore
from checker.pipeline import ReviewPipeline

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
XLSX = ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"
RULES = [ROOT / "rules" / "us_fda_food.json", ROOT / "rules" / "dancing_fish_company_rulebook.md"]


class ScriptedSdk:
    """Returns the given text for every request, like a model that always answers this way."""

    def __init__(self, text):
        self.text, self.models = text, self

    def generate_content(self, model, contents, config):
        return SimpleNamespace(text=self.text)


def review(tmp_path, model_text):
    # two rules no code check implements, so the AI rule judge really runs
    pack = tmp_path / "ai_only.json"
    pack.write_text(json.dumps({"name": "AI-only test rules", "rules": [
        {"id": "T-01", "title": "Brand logo on the front", "text": "The brand logo must appear on the front panel."},
        {"id": "T-02", "title": "Website on the back", "text": "A website address must appear on the back panel."},
    ]}), encoding="utf-8")
    client = GeminiClient(settings=AISettings(api_key="test"), cache=ResponseCache(tmp_path / "cache"))
    client._sdk_clients[0] = ScriptedSdk(model_text)
    pipeline = ReviewPipeline(client=client, feedback=FeedbackStore(tmp_path / "fb.json"))
    return pipeline.run(PDF, XLSX, RULES + [pack], use_ai=True)


def ai_findings(result):
    return [f for f in result.report.findings if f.method == "ai"]


@pytest.mark.parametrize("model_text", [
    "this is not json",
    '{"verdicts": [{"rule_id": "DF-07", "verdict": "definite", "title": "t", "reasoning": "r", "evidence": []}]}',  # not allowed
    "",
])
def test_unusable_output_becomes_could_not_check(tmp_path, model_text):
    result = review(tmp_path, model_text)
    ai = ai_findings(result)
    assert {f.rule_id for f in ai if f.check.startswith("ai_rule_")} == {"T-01", "T-02"}  # the judge ran
    assert ai and all(f.verdict.value == "review" for f in ai)
    assert all("could not" in f.title.lower() for f in ai)
    assert not (tmp_path / "cache").exists() or not any((tmp_path / "cache").iterdir())  # bad answers are not cached


def test_rules_the_model_skips_or_invents_are_handled(tmp_path):
    # valid JSON: T-01 'likely' with no evidence, T-02 not answered, and a rule id nobody asked about
    text = json.dumps({"verdicts": [
        {"rule_id": "T-01", "verdict": "likely", "title": "Logo missing", "reasoning": "Not seen.", "evidence": []},
        {"rule_id": "MADE-UP-1", "verdict": "likely", "title": "x", "reasoning": "y", "evidence": []},
    ]})
    result = review(tmp_path, text)
    judged = {f.rule_id: f for f in ai_findings(result) if f.check.startswith("ai_rule_")}
    assert judged["T-01"].verdict.value == "review" and "did not check out" in judged["T-01"].explanation  # no evidence
    assert judged["T-02"].verdict.value == "review" and "no verdict" in judged["T-02"].explanation  # skipped
    assert not any(f.rule_id == "MADE-UP-1" for f in result.report.findings)  # an invented rule never appears
