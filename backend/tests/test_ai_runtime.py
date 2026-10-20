"""Runtime behaviour of the AI layer: timeouts, model cooldown, and the parallel AI steps.

No real model calls: the SDK and the client are replaced by small fakes.
"""

import time
from pathlib import Path

import pytest

from checker.ai.client import AIError, AISettings, GeminiClient
from checker.ai.marks import MarkInventory
from checker.ai.rule_judge import RuleVerdicts
from checker.feedback import FeedbackStore
from checker.pipeline import ReviewPipeline

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "samples" / "DancingFish_Granola_Berry_US_Carton.pdf"
XLSX = ROOT / "samples" / "DancingFish_Granola_BerryCrunch_US_Content_Sheet.xlsx"
RULES = [ROOT / "rules" / "us_fda_food.json", ROOT / "rules" / "dancing_fish_company_rulebook.md"]


class FakeSdk:
    """Stands in for google.genai.Client: answers per model as told."""

    def __init__(self, behaviour):
        self.behaviour = behaviour  # model -> callable()
        self.calls: list[str] = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        return self.behaviour[model]()


def client_with(behaviour, timeout=1.0, chain=("a", "b"), second_key_behaviour=None):
    client = GeminiClient(settings=AISettings(
        api_key="test", primary_model=chain[0], fallback_models=tuple(chain[1:]), timeout_seconds=timeout,
        fallback_api_key="test2" if second_key_behaviour else None,
    ))
    client._sdk_clients[0] = FakeSdk(behaviour)
    if second_key_behaviour:
        client._sdk_clients[1] = FakeSdk(second_key_behaviour)
    return client


def quota_error():
    raise RuntimeError("429 RESOURCE_EXHAUSTED")


def test_requests_carry_a_fixed_seed():
    # measured: without a seed 2 of 10 AI verdicts changed across 3 identical runs, with it 0 of 10
    from checker.ai.client import SEED
    from checker.ai.rule_judge import RuleVerdicts

    assert GeminiClient._config(RuleVerdicts, "system", 0.0).seed == SEED


def test_timeout_returns_without_waiting_for_the_stuck_call():
    client = client_with({"a": lambda: time.sleep(5)}, timeout=0.5, chain=("a",))
    start = time.perf_counter()
    with pytest.raises(AIError, match="timed out"):
        client._call_once("hi", None, "a")
    assert time.perf_counter() - start < 2  # was 5s: leaving the executor waited for the call


def test_a_refusing_model_is_tried_last_for_a_while():
    client = client_with({"a": quota_error, "b": lambda: "ok"})
    assert client._call_with_fallback("p", None) == ("ok", "b")
    assert client._call_with_fallback("p", None) == ("ok", "b")
    assert client._sdk_clients[0].calls == ["a", "b", "b"]  # second call skips straight to the healthy model


@pytest.mark.parametrize("server_error", ["504 DEADLINE_EXCEEDED. Gateway Timeout", "500 INTERNAL", "502 Bad Gateway"])
def test_a_server_side_failure_moves_on_to_the_next_model(server_error):
    # found live: a 504 from one model ended the chain although the next model had quota
    def fail():
        raise RuntimeError(server_error)
    client = client_with({"a": fail, "b": lambda: "ok"})
    assert client._call_with_fallback("p", None) == ("ok", "b")


def test_a_real_request_error_still_stops_at_once():
    # a 400 means the request itself is wrong: trying other models would only repeat it
    def bad():
        raise RuntimeError("400 INVALID_ARGUMENT")
    client = client_with({"a": bad, "b": lambda: "ok"})
    with pytest.raises(AIError, match="400"):
        client._call_with_fallback("p", None)


def test_cooldown_never_blocks_a_model_that_could_answer():
    client = client_with({"a": lambda: "ok", "b": quota_error})
    client._refused_until.update({(0, "a"): time.monotonic() + 60, (0, "b"): time.monotonic() + 60})
    assert client._call_with_fallback("p", None) == ("ok", "a")  # cooled-down models are still tried


def test_second_key_is_used_when_the_first_is_out_of_quota():
    client = client_with({"a": quota_error, "b": quota_error}, second_key_behaviour={"a": lambda: "ok", "b": quota_error})
    assert client._call_with_fallback("p", None) == ("ok", "a (key 2)")  # labelled, so the UI shows which key answered
    assert client._sdk_clients[0].calls == ["a", "b"]
    assert client._call_with_fallback("p", None) == ("ok", "a (key 2)")
    assert client._sdk_clients[0].calls == ["a", "b"]  # the exhausted key is not retried within the cooldown


def test_parallel_first_calls_share_one_sdk_client(monkeypatch):
    # regression: two AI threads creating the SDK client at once replaced one mid-request
    import threading

    from google import genai

    created = []

    class SlowClient:
        def __init__(self, **kwargs):
            time.sleep(0.2)  # widen the race window
            created.append(self)

    monkeypatch.setattr(genai, "Client", SlowClient)
    client = GeminiClient(settings=AISettings(api_key="test"))
    got = []
    threads = [threading.Thread(target=lambda: got.append(client._sdk())) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(created) == 1 and got[0] is got[1]


class SlowRulesFastMarks:
    """A fake client where the rule judge answers last, to prove numbering does not follow finish order."""

    available = True

    def __init__(self):
        self.models_used: set[str] = set()

    def reset_usage(self):
        self.models_used.clear()

    def image_part(self, png):
        return b"image"

    def generate_json(self, prompt, schema, system, temperature=0.0, use_cache=True):
        self.models_used.add("fake")
        if schema is RuleVerdicts:
            time.sleep(0.3)
            return RuleVerdicts(verdicts=[])
        assert schema is MarkInventory
        return MarkInventory(marks=[])


def test_parallel_ai_findings_are_numbered_in_a_fixed_order(tmp_path):
    pipeline = ReviewPipeline(client=SlowRulesFastMarks(), feedback=FeedbackStore(tmp_path / "fb.json"))
    result = pipeline.run(PDF, XLSX, RULES, use_ai=True)
    findings = result.report.findings
    ids = sorted(int(f.id[1:]) for f in findings)
    assert ids == list(range(1, len(findings) + 1))  # unique and contiguous
    ai = sorted((f for f in findings if f.method == "ai"), key=lambda f: int(f.id[1:]))
    kinds = [f.check.startswith("ai_rule_") for f in ai]
    assert kinds == sorted(kinds, reverse=True)  # every rule finding numbered before every mark finding
    assert {"total", "read_inputs", "code_checks", "ai"} <= set(result.timings)
