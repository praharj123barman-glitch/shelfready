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
RATE_LIMIT_WAITS = [10, 30]  # seconds between retries after a 429 (free tier is ~10 calls/min)


def _cache_key(prompt, schema: type[BaseModel], system: str) -> str:
    h = hashlib.sha256()
    for part in [model_name(), system, schema.__name__, json.dumps(schema.model_json_schema(), sort_keys=True)]:
        h.update(part.encode())
    for p in prompt if isinstance(prompt, list) else [prompt]:
        h.update(p.encode() if isinstance(p, str) else getattr(getattr(p, "inline_data", None), "data", b"") or b"")
    return h.hexdigest()[:32]


def _call_with_timeout(prompt, config, timeout: float):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(lambda: _client().models.generate_content(model=model_name(), contents=prompt, config=config))
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
        return schema.model_validate_json(cached.read_text(encoding="utf-8"))

    timeout = float(os.environ.get("AI_TIMEOUT_SECONDS", "60"))
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature, response_mime_type="application/json", response_schema=schema
    )
    for attempt, wait in enumerate([0] + RATE_LIMIT_WAITS):
        time.sleep(wait)
        try:
            response = _call_with_timeout(prompt, config, timeout)
            break
        except AIError as exc:
            if "429" not in str(exc) or attempt == len(RATE_LIMIT_WAITS):
                raise
            log.warning("rate limited, retrying in %ss", RATE_LIMIT_WAITS[attempt])
    try:
        result = schema.model_validate_json(response.text or "")
    except ValidationError as exc:
        log.warning("model returned invalid JSON: %s", (response.text or "")[:300])
        raise AIError(f"Model returned an answer that does not match the expected format: {exc.errors()[:2]}") from exc
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(result.model_dump_json(), encoding="utf-8")
    return result


def image_part(png_bytes: bytes):
    from google.genai import types

    return types.Part.from_bytes(data=png_bytes, mime_type="image/png")
