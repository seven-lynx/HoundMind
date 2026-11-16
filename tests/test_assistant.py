"""The assistant answers text and cannot move the dog.

The module is the one place a language model touches the runtime, so these tests pin the boundaries
rather than the wording: no key means a disabled module and no handler, a reply lands on
`assistant_reply` and nowhere else, a dead link costs the module instead of the loop, and the key is
read from the environment or a file - never from the config this repo publishes.
"""

from __future__ import annotations

import json
import time
import urllib.request

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.optional.assistant import AssistantModule

REPLY = "Woof. I am fine."


class _Response:
    """Stands in for the object `urlopen` returns."""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class Transport:
    """A fake `urlopen`: records the requests and returns a canned completion."""

    def __init__(self, reply: str = REPLY, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request, timeout=None):  # noqa: ANN001 - matches urlopen's shape
        self.requests.append(request)
        if self.fail:
            raise OSError("network is down")
        return _Response({"choices": [{"message": {"content": self.reply}}]})


def install(monkeypatch, transport: Transport) -> Transport:
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    return transport


def settings(**overrides: object) -> dict:
    """A ready-to-run `settings.assistant` table; `requests_per_minute: 0` keeps tests instant."""
    table: dict = {
        "enabled": True,
        "backend": "openai_compatible",
        "base_url": "https://example.invalid/v1",
        "model": "test-model",
        "api_key_env": "HOUNDMIND_TEST_KEY",
        "api_key_path": "",
        "timeout_s": 1.0,
        "requests_per_minute": 0,
        "max_failures": 3,
    }
    table.update(overrides)
    return {"assistant": table}


def context(monkeypatch, key: str = "test-key", **overrides: object) -> RuntimeContext:
    monkeypatch.setenv("HOUNDMIND_TEST_KEY", key)
    ctx = RuntimeContext()
    ctx.set("settings", settings(**overrides))
    return ctx


def wait_for_reply(ctx: RuntimeContext, timeout: float = 2.0) -> str | None:
    """Poll for the worker's reply with a bounded wait - never a bare sleep-and-hope."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = ctx.get("assistant_reply")
        if isinstance(reply, str) and reply:
            return reply
        time.sleep(0.01)
    return None


def test_a_missing_key_disables_the_module_and_registers_no_handler(monkeypatch) -> None:
    install(monkeypatch, Transport())
    monkeypatch.delenv("HOUNDMIND_TEST_KEY", raising=False)
    ctx = RuntimeContext()
    ctx.set("settings", settings(api_key_env="HOUNDMIND_TEST_KEY", api_key_path=""))
    module = AssistantModule("assistant")

    module.start(ctx)

    assert module.status.enabled is False
    assert "API key" in str(module.status.disabled_reason)
    assert ctx.get("voice_question_handler") is None


def test_the_backend_none_keeps_the_block_inert(monkeypatch) -> None:
    install(monkeypatch, Transport())
    ctx = context(monkeypatch, backend="none")
    module = AssistantModule("assistant")

    module.start(ctx)

    assert module.status.enabled is False
    assert "not implemented" in str(module.status.disabled_reason)


def test_answer_returns_at_once_and_the_reply_arrives_on_the_context(monkeypatch) -> None:
    transport = install(monkeypatch, Transport())
    ctx = context(monkeypatch)
    module = AssistantModule("assistant")
    module.start(ctx)
    try:
        assert module.answer("how are you?") == ""
        assert wait_for_reply(ctx) == REPLY
        assert len(transport.requests) == 1
        # Text in, text out: nothing about motion is written anywhere.
        for key in ("motion_command", "behavior_override", "intent_board", "voice_command"):
            assert ctx.get(key) is None
    finally:
        module.stop(ctx)


def test_the_environment_key_wins_over_the_file(monkeypatch, tmp_path) -> None:
    transport = install(monkeypatch, Transport())
    key_file = tmp_path / "llm_key"
    key_file.write_text("file-key", encoding="utf-8")
    ctx = context(monkeypatch, key="env-key", api_key_path=str(key_file))
    module = AssistantModule("assistant")
    module.start(ctx)
    try:
        module.answer("hello?")
        assert wait_for_reply(ctx) == REPLY
        assert transport.requests[0].get_header("Authorization") == "Bearer env-key"
    finally:
        module.stop(ctx)


def test_the_key_file_is_used_when_the_environment_is_empty(monkeypatch, tmp_path) -> None:
    transport = install(monkeypatch, Transport())
    key_file = tmp_path / "llm_key"
    key_file.write_text("file-key\n", encoding="utf-8")
    ctx = context(monkeypatch, key="", api_key_env="", api_key_path=str(key_file))
    module = AssistantModule("assistant")
    module.start(ctx)
    try:
        module.answer("hello?")
        assert wait_for_reply(ctx) == REPLY
        assert transport.requests[0].get_header("Authorization") == "Bearer file-key"
    finally:
        module.stop(ctx)


def test_a_dead_link_disables_the_module_instead_of_the_runtime(monkeypatch) -> None:
    transport = install(monkeypatch, Transport(fail=True))
    ctx = context(monkeypatch, max_failures=2)
    module = AssistantModule("assistant")
    module.start(ctx)
    try:
        module.answer("first?")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(transport.requests) < 1:
            time.sleep(0.01)
        module.answer("second?")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and module.status.enabled:
            time.sleep(0.01)
        assert module.status.enabled is False
        assert "consecutive request failures" in str(module.status.disabled_reason)
        assert ctx.get("assistant_reply") is None
    finally:
        module.stop(ctx)
