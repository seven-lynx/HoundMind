"""`settings.voice_assistant.tts` is honoured, not decorative (#8).

The table shipped in `config/settings.jsonc` and documented in `optional/voice.py` was inert:
`_speak` picked an engine by itself, so `backend: "pyttsx3"` still used the robot voice and
`enabled: false` still spoke. These tests drive the real path - a `voice_text` through `tick` -
and pin the contract: a disabled table is a no-op, `auto` keeps the vendor-first order, and a
named backend never borrows the other engine.
"""

from __future__ import annotations

import sys
import types

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.optional.voice import VoiceModule

UTTERANCE = "I heard: hello?"


class FakePidog:
    """Stands in for the vendor module: records the attempt, and can fail on purpose."""

    def __init__(self, fail: bool = False) -> None:
        self.attempts: list[str] = []
        self.fail = fail

    def speak(self, text: str) -> None:
        self.attempts.append(text)
        if self.fail:
            raise RuntimeError("vendor voice unavailable")


class FakeEngine:
    """Stands in for the engine object `pyttsx3.init()` returns."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def runAndWait(self) -> None:
        return None

    def stop(self) -> None:
        return None


def context(**tts: object) -> RuntimeContext:
    """A runtime context whose voice settings carry the `tts` table given, if any."""
    ctx = RuntimeContext()
    voice: dict = {"enabled": True, "cooldown_s": 0.0, "stt": {"enabled": False}}
    if tts:
        voice["tts"] = tts
    ctx.set("settings", {"voice_assistant": voice})
    return ctx


def module(pidog: FakePidog | None = None) -> VoiceModule:
    vm = VoiceModule("voice", enabled=True)
    vm._pidog = pidog
    vm.available = True
    return vm


def install_pyttsx3(monkeypatch) -> FakeEngine:
    """Put a fake `pyttsx3` in `sys.modules`, because the import lives inside `_speak`."""
    engine = FakeEngine()
    fake = types.ModuleType("pyttsx3")
    fake.init = lambda: engine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyttsx3", fake)
    return engine


def hear_a_question(vm: VoiceModule, ctx: RuntimeContext) -> None:
    """Drive the module the way the runtime does: a question no command maps to."""
    ctx.set("voice_text", "hello?")
    vm.tick(ctx)


def test_a_disabled_table_keeps_the_module_silent(monkeypatch) -> None:
    """`enabled: false` is the switch the shipped config sets; off means no speech at all."""
    engine = install_pyttsx3(monkeypatch)
    pidog = FakePidog()
    vm = module(pidog)
    ctx = context(enabled=False, backend="pidog")

    hear_a_question(vm, ctx)

    assert pidog.attempts == []
    assert engine.said == []


def test_auto_prefers_the_vendor_voice_and_enabled_defaults_to_true(monkeypatch) -> None:
    """`auto` is the pre-#8 order, and an absent `enabled` key does not mute it."""
    engine = install_pyttsx3(monkeypatch)
    pidog = FakePidog()
    vm = module(pidog)
    ctx = context(backend="auto")

    hear_a_question(vm, ctx)

    assert pidog.attempts == [UTTERANCE]
    assert engine.said == []


def test_auto_falls_back_to_pyttsx3_without_a_vendor_voice(monkeypatch) -> None:
    engine = install_pyttsx3(monkeypatch)
    vm = module(None)
    ctx = context(backend="auto")

    hear_a_question(vm, ctx)

    assert engine.said == [UTTERANCE]


def test_an_explicit_pidog_backend_does_not_fall_back(monkeypatch) -> None:
    """A user who asked for the robot voice does not get the local one when it fails."""
    engine = install_pyttsx3(monkeypatch)
    pidog = FakePidog(fail=True)
    vm = module(pidog)
    ctx = context(enabled=True, backend="pidog")

    hear_a_question(vm, ctx)

    assert pidog.attempts == [UTTERANCE]
    assert engine.said == []


def test_an_explicit_pyttsx3_backend_ignores_the_vendor_voice(monkeypatch) -> None:
    """The reported case: asking for pyttsx3 must not reach `pidog.speak`."""
    engine = install_pyttsx3(monkeypatch)
    pidog = FakePidog()
    vm = module(pidog)
    ctx = context(enabled=True, backend="pyttsx3")

    hear_a_question(vm, ctx)

    assert engine.said == [UTTERANCE]
    assert pidog.attempts == []


def test_a_config_without_the_tts_table_keeps_the_old_chain() -> None:
    """A hand-trimmed older config has no `tts` key; it keeps `auto`, not silence."""
    pidog = FakePidog()
    vm = module(pidog)
    ctx = context()

    hear_a_question(vm, ctx)

    assert pidog.attempts == [UTTERANCE]
