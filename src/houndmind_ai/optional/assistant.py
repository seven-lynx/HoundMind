from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are the voice of a small robot dog. Answer in one or two short sentences, plainly, and "
    "never claim you can do something you cannot."
)

# A provider that is merely busy is not a broken feature. Free tiers are rate-limited by design - Groq's
# free plan is 30 requests/minute, OpenRouter's `:free` variants 20 - so three quick 429s in a
# conversation is normal, and counting them against `max_failures` switched the assistant off for good
# (#250). These two sets are the classification the retry policy acts on.
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_STATUS = frozenset({401, 403})


class AssistantRequestError(RuntimeError):
    """A failed call, carrying enough to decide whether it is worth retrying."""

    def __init__(
        self, message: str, status: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def transient(self) -> bool:
        """The provider is busy; the same request may work shortly."""
        return self.status in _TRANSIENT_STATUS

    @property
    def fatal(self) -> bool:
        """The key is wrong or revoked; retrying cannot help."""
        return self.status in _AUTH_STATUS


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    """`Retry-After` in seconds, when the provider sent a plain number.

    A date-formatted value is ignored on purpose - a clock-skewed device would compute a nonsense wait,
    and a fixed backoff is the safer answer for a dog.
    """
    try:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if raw is None:
            return None
        value = float(str(raw).strip())
    except Exception:
        return None
    return max(0.0, min(value, 30.0))


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


class AssistantModule(Module):
    """A language model behind `voice_question_handler` - cloud now, a LAN box later.

    The module answers **text** and nothing else. It registers a callable that `optional/voice.py`
    invokes with an utterance and publishes the reply on `assistant_reply` for the voice module to
    speak. It never writes `behavior_override`, `motion_command` or an intent, so a model cannot move
    the dog: the phrase map in `voice.py` runs first and owns every command.

    Config (`settings.assistant`):

    - `backend`: `openai_compatible` or `none`.
    - `base_url`: any endpoint that speaks the OpenAI chat-completions API. That is the whole reason
      the local model is a config change rather than a second implementation - Ollama, llama.cpp's
      `llama-server` and LM Studio all expose `/v1/chat/completions`.
    - `model`, `max_tokens`, `timeout_s`, `requests_per_minute`, `max_failures`.
    - `api_key_env` / `api_key_path`: the key comes from the environment first, then from a 0600 file.
      It is never read from `config/settings.jsonc` and never logged.

    The request is a stdlib `urllib` POST on a worker thread: no dependency, an explicit timeout, and
    nothing that can stall a tick on a bad link.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._context: Any | None = None
        self._base_url = ""
        self._model = ""
        self._api_key = ""
        self._system_prompt = DEFAULT_SYSTEM_PROMPT
        self._max_tokens = 256
        self._timeout_s = 8.0
        self._min_interval_s = 6.0
        self._max_failures = 3
        self._max_transient_retries = 3
        self._failures = 0
        self._last_request_ts = 0.0
        # Latest utterance wins: a second question replaces a queued one rather than queueing behind
        # it, the same rule the vision scheduler uses for frames.
        self._pending: str | None = None
        self._has_pending = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return

        settings = (context.get("settings") or {}).get("assistant", {}) or {}
        backend = str(settings.get("backend", "none"))
        if backend != "openai_compatible":
            self.disable(f"backend {backend!r} is not implemented; use 'openai_compatible'")
            return

        self._base_url = str(settings.get("base_url", "") or "").rstrip("/")
        self._model = str(settings.get("model", "") or "")
        if not self._base_url or not self._model:
            self.disable("assistant needs settings.assistant.base_url and .model")
            return

        self._api_key = self._read_key(settings)
        if not self._api_key:
            self.disable(
                "no API key: set the environment variable named by settings.assistant.api_key_env, "
                "or write the key into settings.assistant.api_key_path (mode 0600)"
            )
            return

        self._system_prompt = str(
            settings.get("system_prompt", DEFAULT_SYSTEM_PROMPT) or DEFAULT_SYSTEM_PROMPT
        )
        self._max_tokens = _safe_int(settings.get("max_tokens", 256), 256)
        self._timeout_s = _safe_float(settings.get("timeout_s", 8.0), 8.0)
        rate = _safe_int(settings.get("requests_per_minute", 10), 10)
        self._min_interval_s = 60.0 / rate if rate > 0 else 0.0
        self._max_failures = _safe_int(settings.get("max_failures", 3), 3)
        self._max_transient_retries = _safe_int(settings.get("max_transient_retries", 3), 3)

        self._context = context
        context.set("voice_question_handler", self.answer)
        context.set("assistant", {"status": "ready", "model": self._model})

        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="assistant", daemon=True)
        self._worker.start()
        logger.info("Assistant ready: %s at %s", self._model, self._base_url)

    @staticmethod
    def _read_key(settings: dict) -> str:
        """The API key: environment first, then a 0600 file. Never from `settings.jsonc`."""
        env_name = str(settings.get("api_key_env", "") or "")
        if env_name:
            value = os.environ.get(env_name, "")
            if value.strip():
                return value.strip()
        path = str(settings.get("api_key_path", "") or "")
        if path:
            try:
                return Path(path).expanduser().read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.info("Assistant key file %s unreadable: %s", path, exc)
        return ""

    def answer(self, text: str) -> str:
        """Queue `text` and return at once.

        `voice` documents the handler as text in, text out - but a model call is 200-2000 ms and this
        is called from the tick. So the reply is published on `assistant_reply` when it arrives, and
        an empty return here means "nothing to say yet", which `voice` no longer turns into an echo.
        """
        if not self.status.enabled or not str(text or "").strip():
            return ""
        self._pending = str(text).strip()
        self._has_pending.set()
        return ""

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._has_pending.wait(0.2):
                continue
            self._has_pending.clear()
            text = self._pending
            self._pending = None
            if not text:
                continue
            reply = self._ask(text)
            if reply and self._context is not None:
                self._context.set("assistant_reply", reply)

    def _ask(self, text: str) -> str | None:
        """One utterance, with the retry policy for a provider that is merely busy (#250).

        A rate limit is not a broken feature: 429/5xx back off and are never counted toward
        `max_failures`, so a free tier can throttle the dog without switching its voice off. A bad key
        is hopeless and disables at once; anything else is a real failure and is counted.
        """
        for attempt in range(self._max_transient_retries + 1):
            self._wait_for_rate_limit()
            try:
                reply = self._request(text)
            except AssistantRequestError as exc:
                if exc.fatal:
                    self.disable(f"provider rejected the key (HTTP {exc.status}): {exc}")
                    return None
                if exc.transient:
                    if attempt >= self._max_transient_retries:
                        logger.warning(
                            "Assistant dropped an utterance after %d retries: %s", attempt, exc
                        )
                        return None
                    delay = (
                        exc.retry_after
                        if exc.retry_after is not None
                        else min(2.0 * (attempt + 1), 30.0)
                    )
                    logger.warning("Assistant busy (HTTP %s); retrying in %.1fs", exc.status, delay)
                    self._stop.wait(delay)
                    continue
                self._count_failure(exc)
                return None
            except Exception as exc:
                self._count_failure(exc)
                return None
            self._failures = 0
            return reply
        return None

    def _count_failure(self, exc: Exception) -> None:
        """A real failure - a timeout, a dead link, a body that made no sense."""
        self._failures += 1
        logger.warning("Assistant request failed (%d/%d): %s", self._failures, self._max_failures, exc)
        if self._failures >= self._max_failures:
            # A dead link must cost the feature, not the runtime: stop calling out.
            self.disable(f"{self._failures} consecutive request failures: {exc}")

    def _wait_for_rate_limit(self) -> None:
        """Space requests out - a rate limit is a safety feature here, not politeness."""
        if self._min_interval_s <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self._min_interval_s:
            self._stop.wait(self._min_interval_s - elapsed)
        self._last_request_ts = time.monotonic()

    def _request(self, text: str) -> str:
        """One chat-completions call. Raises on anything that is not a usable answer."""
        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": text},
                ],
                "max_tokens": self._max_tokens,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The provider's reason is useful; the request body is never written to the log.
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                detail = ""
            raise AssistantRequestError(
                f"HTTP {exc.code} from {self._base_url}: {detail}",
                status=exc.code,
                retry_after=_retry_after_seconds(exc),
            ) from exc

        choices = payload.get("choices") or []
        if not choices:
            raise AssistantRequestError("provider returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AssistantRequestError("provider returned an empty message")
        return content.strip()

    def tick(self, context) -> None:
        # The worker publishes replies. Nothing here may touch the network: this is the tick.
        return None

    def stop(self, context) -> None:
        self._stop.set()
        self._has_pending.set()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=1.0)
            self._worker = None
        super().stop(context)
