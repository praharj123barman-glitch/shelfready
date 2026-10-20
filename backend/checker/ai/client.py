"""Gemini access: settings, a response cache, and a client with a model fallback chain.

Three small classes with one job each:

* ``AISettings``    what to call: API key(s), primary model, fallbacks, timeout (from .env)
* ``ResponseCache`` real earlier answers stored on disk, so repeated requests
                    (demos, re-runs) do not spend free-tier quota
* ``GeminiClient``  makes the call: structured JSON output, timeout, and moving to
                    the next model when one is rate limited or overloaded

Every call returns a validated Pydantic object or raises ``AIError``. Callers turn
``AIError`` into a visible "needs review" finding: nothing pretends the model ran.

Use ``default_client()`` to get the shared client.
"""

from __future__ import annotations

import concurrent.futures
import functools
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / "backend" / "runs" / "ai_cache"


class AIError(RuntimeError):
    """The model could not be reached or returned something unusable."""


def load_env_file(path: Path = PROJECT_ROOT / ".env") -> None:
    """Read KEY=VALUE lines into the environment (no extra dependency). Real
    environment variables win over the file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class AISettings:
    api_key: str | None
    primary_model: str = "gemini-2.5-flash"
    fallback_models: tuple[str, ...] = ()
    timeout_seconds: float = 60.0
    fallback_api_key: str | None = None  # used when every model refuses on the first key

    @classmethod
    def from_env(cls) -> "AISettings":
        load_env_file()
        fallbacks = tuple(m.strip() for m in os.environ.get("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip())
        return cls(
            api_key=os.environ.get("GEMINI_API_KEY") or None,
            primary_model=os.environ.get("GEMINI_MODEL", cls.primary_model),
            fallback_models=fallbacks,
            timeout_seconds=float(os.environ.get("AI_TIMEOUT_SECONDS", cls.timeout_seconds)),
            fallback_api_key=os.environ.get("GEMINI_FALLBACK_API_KEY") or None,
        )

    @property
    def model_chain(self) -> list[str]:
        """Models to try, in order: the primary, then each distinct fallback."""
        return [self.primary_model] + [m for m in self.fallback_models if m != self.primary_model]

    @property
    def api_keys(self) -> list[str]:
        """Keys to try, in order. Only their position is ever logged or shown, never the key."""
        return [k for k in (self.api_key, self.fallback_api_key) if k]

    @property
    def routes(self) -> list[tuple[int, str]]:
        """(key number, model) pairs in the order to try: every model on the first key, then on the second."""
        return [(i, m) for i in range(len(self.api_keys)) for m in self.model_chain]


@dataclass
class ResponseCache:
    """Stores each validated answer with the model that wrote it.

    The key is the request (system prompt, schema, prompt text and images), not
    the model, because any model in the chain may have answered it.
    """

    directory: Path = CACHE_DIR

    @staticmethod
    def key(prompt: str | list, schema: type[BaseModel], system: str) -> str:
        h = hashlib.sha256()
        for part in [system, schema.__name__, json.dumps(schema.model_json_schema(), sort_keys=True)]:
            h.update(part.encode())
        for p in prompt if isinstance(prompt, list) else [prompt]:
            # text parts by content, image parts by their bytes
            h.update(p.encode() if isinstance(p, str) else getattr(getattr(p, "inline_data", None), "data", b"") or b"")
        return h.hexdigest()[:32]

    def get(self, key: str, schema: type[T]) -> tuple[T, str] | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        if "result" not in entry:
            return None
        return schema.model_validate(entry["result"]), entry.get("model", "?")

    def put(self, key: str, result: BaseModel, model: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{key}.json").write_text(json.dumps({"model": model, "result": result.model_dump()}), encoding="utf-8")


# errors that mean "try another model", not "this request is wrong"
# (404: a model can exist for one key and not for another; 500/502/504: Google's side failed or timed out,
# seen live as a 504 from gemini-flash-latest, which used to end the chain before the models that had quota)
RETRYABLE_ERRORS = ("429", "500", "502", "503", "504", "404", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "NOT_FOUND",
                    "INTERNAL", "DEADLINE_EXCEEDED", "timed out")
# seconds to wait before one more round of the whole chain when every model refused
ROUND_WAITS = (0, 15)
# a model that just refused (quota, overload) is tried last for this long; per-minute
# quotas reset within it, and a model out of daily quota costs one probe a minute, not one per call
COOLDOWN_SECONDS = 60
SEED = 7  # any fixed number; the model then makes a best effort to answer a repeated request the same way


@dataclass
class GeminiClient:
    settings: AISettings
    cache: ResponseCache = field(default_factory=ResponseCache)
    # models that actually answered since the last reset_usage(); cached answers say so
    models_used: set[str] = field(default_factory=set)
    _sdk_clients: dict[int, Any] = field(default_factory=dict, repr=False)  # key number -> SDK client
    _refused_until: dict[tuple[int, str], float] = field(default_factory=dict, repr=False)  # route -> monotonic time
    _sdk_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def available(self) -> bool:
        return bool(self.settings.api_key)

    def reset_usage(self) -> None:
        self.models_used.clear()

    def generate_json(self, prompt: str | list, schema: type[T], system: str,
                      temperature: float = 0.0, use_cache: bool = True) -> T:
        """Ask for an answer that fits `schema`, and validate it.

        Identical requests are answered from the cache unless use_cache=False
        (for example chat replies, where a fresh answer is wanted).
        """
        key = ResponseCache.key(prompt, schema, system)
        if use_cache and (hit := self.cache.get(key, schema)):
            result, model = hit
            self.models_used.add(f"{model} (cached)")
            return result

        response, model = self._call_with_fallback(prompt, self._config(schema, system, temperature))
        self.models_used.add(model)
        try:
            result = schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            log.warning("model returned invalid JSON: %s", (response.text or "")[:300])
            raise AIError(f"Model returned an answer that does not match the expected format: {exc.errors()[:2]}") from exc
        self.cache.put(key, result, model)
        return result

    @staticmethod
    def image_part(png_bytes: bytes):
        """An image to send alongside text in a prompt list."""
        from google.genai import types

        return types.Part.from_bytes(data=png_bytes, mime_type="image/png")

    # ---------------- internals ----------------

    def _sdk(self, key_number: int = 0):
        # one long-lived SDK client per key: a throwaway one can be garbage collected and
        # close its HTTP connection while a request is still in flight. The lock matters
        # because the pipeline's AI steps run in parallel: two threads creating a client at
        # once would replace one mid-request ("client has been closed").
        with self._sdk_lock:
            if key_number not in self._sdk_clients:
                keys = self.settings.api_keys
                if key_number >= len(keys):
                    raise AIError("GEMINI_API_KEY is not set. Add it to .env (see .env.example).")
                from google import genai
                from google.genai import types

                # the HTTP timeout ends an abandoned request's thread too (see _call_once)
                http = types.HttpOptions(timeout=int(self.settings.timeout_seconds * 1000))
                self._sdk_clients[key_number] = genai.Client(api_key=keys[key_number], http_options=http)
            return self._sdk_clients[key_number]

    @staticmethod
    def _config(schema: type[BaseModel], system: str, temperature: float):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, response_mime_type="application/json", response_schema=schema,
            seed=SEED,  # best effort at the same answer for the same request (the cache makes repeats exact)
        )

    def _call_with_fallback(self, prompt, config):
        """Quota or overload on one model moves straight to the next, then to the same
        models on the fallback key; when every route refuses, wait once and go round
        again before giving up. Returns (response, label of who answered)."""
        if not self.settings.api_keys:  # say so plainly: with no routes the loop below would report "rate limited"
            raise AIError("GEMINI_API_KEY is not set. Add it to .env (see .env.example).")
        last_error: AIError | None = None
        for wait in ROUND_WAITS:
            time.sleep(wait)
            for key_number, model in self._routes_in_order():
                label = model if key_number == 0 else f"{model} (key {key_number + 1})"
                try:
                    return self._call_once(prompt, config, model, key_number), label
                except AIError as exc:
                    if not any(code in str(exc) for code in RETRYABLE_ERRORS):
                        raise
                    last_error = exc
                    self._refused_until[(key_number, model)] = time.monotonic() + COOLDOWN_SECONDS
                    log.warning("%s unavailable (%s), trying next", label, str(exc)[:60])
        keys = f" on {len(self.settings.api_keys)} keys" if len(self.settings.api_keys) > 1 else ""
        # the last error says why (quota, overload, timeout): the summary must not guess
        raise AIError(f"No model could answer{keys} ({', '.join(self.settings.model_chain)}); last error: {last_error}")

    def _routes_in_order(self) -> list[tuple[int, str]]:
        """Every (key, model) route, with those that refused in the last minute moved to the end
        (still tried, so a cooldown never makes a call fail that could have succeeded)."""
        now = time.monotonic()
        return sorted(self.settings.routes, key=lambda route: self._refused_until.get(route, 0) > now)

    def _call_once(self, prompt, config, model: str, key_number: int = 0):
        timeout = self.settings.timeout_seconds
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(lambda: self._sdk(key_number).models.generate_content(model=model, contents=prompt, config=config))
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise AIError(f"Model call timed out after {timeout:.0f}s") from exc
        except AIError:
            raise
        except Exception as exc:
            raise AIError(f"Model call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        finally:
            # do not wait for a timed-out call: 'with ThreadPoolExecutor' would block here until it finished
            pool.shutdown(wait=False)


@functools.lru_cache(maxsize=1)
def default_client() -> GeminiClient:
    """The shared client, configured from the environment and .env."""
    return GeminiClient(settings=AISettings.from_env())
