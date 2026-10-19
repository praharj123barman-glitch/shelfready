"""Thin Gemini wrapper: structured JSON output, timeouts and honest errors.

Every AI call returns a validated Pydantic object or raises AIError. Callers
turn AIError into a visible REVIEW finding; nothing pretends the model ran
when it did not.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
_ENV_LOADED = False


class AIError(RuntimeError):
    """The model could not be reached or returned something unusable."""


def _load_env() -> None:
    """Read KEY=VALUE pairs from the project .env (no extra dependency)."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env = Path(__file__).resolve().parents[3] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip())
    _ENV_LOADED = True


def ai_available() -> bool:
    _load_env()
    return bool(os.environ.get("GEMINI_API_KEY"))


def model_name() -> str:
    _load_env()
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


_CLIENT = None


def _client():
    # one shared client: a throwaway one gets garbage collected and closes its
    # HTTP connection while the request is still in flight
    global _CLIENT
    if _CLIENT is None:
        _load_env()
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise AIError("GEMINI_API_KEY is not set. Add it to .env (see .env.example).")
        from google import genai

        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


CACHE_DIR = Path(__file__).resolve().parents[2] / "runs" / "ai_cache"
RATE_LIMIT_WAITS = [15]  # seconds before one more round of the model chain after every model refused


def _cache_key(prompt, schema: type[BaseModel], system: str) -> str:
    h = hashlib.sha256()
    # keyed on the request, not the model: any model in the chain may have answered it
    for part in [system, schema.__name__, json.dumps(schema.model_json_schema(), sort_keys=True)]:
        h.update(part.encode())
    for p in prompt if isinstance(prompt, list) else [prompt]:
        h.update(p.encode() if isinstance(p, str) else getattr(getattr(p, "inline_data", None), "data", b"") or b"")
    return h.hexdigest()[:32]


def model_chain() -> list[str]:
    """Primary model first, then GEMINI_FALLBACK_MODELS (comma separated)."""
    _load_env()
    extra = [m.strip() for m in os.environ.get("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
    return [model_name()] + [m for m in extra if m != model_name()]


MODELS_USED: set[str] = set()  # models that actually answered, reported with each review
RETRYABLE = ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "timed out")


def _call_with_fallback(prompt, config, timeout: float):
    """Quota or overload on one model moves straight to the next; when every model
    fails, wait and go round once more before giving up with a clear error."""
    last: AIError | None = None
    for round_no, wait in enumerate([0] + RATE_LIMIT_WAITS):
        time.sleep(wait)
        for model in model_chain():
            try:
                return _call_with_timeout(prompt, config, timeout, model), model
            except AIError as exc:
                if not any(code in str(exc) for code in RETRYABLE):
                    raise
                last = exc
                log.warning("%s unavailable (%s), trying next model", model, str(exc)[:60])
    raise AIError(f"All models are rate limited or unavailable ({', '.join(model_chain())}): {last}")


def _call_with_timeout(prompt, config, timeout: float, model: str):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: _client().models.generate_content(model=model, contents=prompt, config=config))
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise AIError(f"Model call timed out after {timeout:.0f}s") from exc
        except AIError:
            raise
        except Exception as exc:
            raise AIError(f"Model call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc


def generate_json(prompt: str | list, schema: type[T], system: str, temperature: float = 0.0, use_cache: bool = True) -> T:
    """Call the model with a response schema and validate the answer.

    Identical requests are answered from a local cache (real earlier model
    output, stored under backend/runs/ai_cache), which keeps demos repeatable
    and inside the free-tier quota. Set use_cache=False to force a fresh call.
    """
    from google.genai import types

    key = _cache_key(prompt, schema, system)
    cached = CACHE_DIR / f"{key}.json"
    if use_cache and cached.exists():
        entry = json.loads(cached.read_text(encoding="utf-8"))
        if "result" in entry:  # entries record which model wrote them
            MODELS_USED.add(f"{entry.get('model', '?')} (cached)")
            return schema.model_validate(entry["result"])

    timeout = float(os.environ.get("AI_TIMEOUT_SECONDS", "60"))
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature, response_mime_type="application/json", response_schema=schema
    )
    response, used = _call_with_fallback(prompt, config, timeout)
    MODELS_USED.add(used)
    try:
        result = schema.model_validate_json(response.text or "")
    except ValidationError as exc:
        log.warning("model returned invalid JSON: %s", (response.text or "")[:300])
        raise AIError(f"Model returned an answer that does not match the expected format: {exc.errors()[:2]}") from exc
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"model": used, "result": result.model_dump()}), encoding="utf-8")
    return result


def image_part(png_bytes: bytes):
    from google.genai import types

    return types.Part.from_bytes(data=png_bytes, mime_type="image/png")
