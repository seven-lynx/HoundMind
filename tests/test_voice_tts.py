"""`settings.voice_assistant.tts` reaches a real engine, and the right one (#8, #245).

The table shipped in `config/settings.jsonc` was inert once: `_speak` picked an engine by itself, so
`backend: "pyttsx3"` still used the robot voice and `enabled: false` still spoke. It was also wired to
`Pidog.speak()`, which resolves a preset sound *name* to a file rather than speaking text, so the
shipped `pidog` default could never say a sentence (#245).

These tests drive the real path - a `voice_text` through `tick` - and pin the contract: a disabled
table is a no-op, `auto` walks the vendor engines and then `pyttsx3`, a named backend never borrows
another engine, and the vendor engines are `robot_hat.tts` objects driven with `say()`.
"""

from __future__ import annotations

import sys
import types

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.optional.voice import VoiceModule

UTTERANCE = "I heard: hello?"

# The class names `robot_hat.tts` exposes, in the order `auto` should try them.
VENDOR_CLASSES = ("Piper", "EdgeTTS", "Espeak", "Pico2Wave")


class Transcript:
    """What the fake engines saw: which were built, and what was said through them."""

    def __init__(self) -> None:
        self.built: list[str] = []
        self.said: list[tuple[str, str]] = []


class FakeEngine:
    """Stands in for the object `pyttsx3.init()` returns."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def runAndWait(self) -> None:
        return None

    def stop(self) -> None:
        return None


def install_vendor(
    monkeypatch,
    *,
    failing: tuple[str, ...] = (),
    broken: tuple[str, ...] = (),
) -> Transcript:
    """Put a fake `robot_hat.tts` in `sys.modules`, because the import lives inside `_vendor_tts`.

    `failing` engines construct but raise from `say()`; `broken` engines raise from `__init__`, which
    is what a half-installed vendor stack looks like.
    """
    transcript = Transcript()
    vendor = types.ModuleType("robot_hat.tts")

    for label in VENDOR_CLASSES:

        def _make(name: str = label) -> type:
            class Engine:
                def __init__(self) -> None:
                    transcript.built.append(name)
                    if name in broken:
                        raise RuntimeError(f"{name} is not installed")

                def say(self, text: str) -> None:
                    if name in failing:
                        raise RuntimeError(f"{name} could not speak")
                    transcript.said.append((name, text))

            Engine.__name__ = name
            return Engine

        setattr(vendor, label, _make())

    package = types.ModuleType("robot_hat")
    package.tts = vendor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "robot_hat", package)
    monkeypatch.setitem(sys.modules, "robot_hat.tts", vendor)
    return transcript


def hide_vendor(monkeypatch) -> None:
    """Make `import robot_hat.tts` fail the way a lite install does."""
    monkeypatch.setitem(sys.modules, "robot_hat", None)
    monkeypatch.setitem(sys.modules, "robot_hat.tts", None)


def install_pyttsx3(monkeypatch) -> FakeEngine:
    """Put a fake `pyttsx3` in `sys.modules`, because the import lives inside `_speak`."""
    engine = FakeEngine()
    fake = types.ModuleType("pyttsx3")
    fake.init = lambda: engine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyttsx3", fake)
    return engine


def context(**tts: object) -> RuntimeContext:
    """A runtime context whose voice settings carry the `tts` table given, if any."""
    ctx = RuntimeContext()
    voice: dict = {"enabled": True, "cooldown_s": 0.0, "stt": {"enabled": False}}
    if tts:
        voice["tts"] = tts
    ctx.set("settings", {"voice_assistant": voice})
    return ctx


def module() -> VoiceModule:
    vm = VoiceModule("voice", enabled=True)
    vm.available = True
    return vm


def hear_a_question(vm: VoiceModule, ctx: RuntimeContext) -> None:
    """Drive the module the way the runtime does: a question no command maps to."""
    ctx.set("voice_text", "hello?")
    vm.tick(ctx)


def test_a_disabled_table_keeps_the_module_silent(monkeypatch) -> None:
    """`enabled: false` is the switch the shipped config sets; off means no speech at all."""
    transcript = install_vendor(monkeypatch)
    engine = install_pyttsx3(monkeypatch)
    vm = module()

    hear_a_question(vm, context(enabled=False, backend="auto"))

    assert transcript.said == []
    assert transcript.built == []
    assert engine.said == []


def test_auto_speaks_through_the_first_vendor_engine(monkeypatch) -> None:
    """`auto` is the vendor-first order the docstring promises."""
    transcript = install_vendor(monkeypatch)
    engine = install_pyttsx3(monkeypatch)
    vm = module()

    hear_a_question(vm, context(backend="auto"))

    assert transcript.said == [("Piper", UTTERANCE)]
    assert engine.said == []


def test_pidog_uses_the_vendor_speaker_and_never_the_preset_sound_api(monkeypatch) -> None:
    """The regression for #245: `pidog` must not reach `Pidog.speak()`, which takes a sound name."""
    transcript = install_vendor(monkeypatch)

    class FakePidog:
        def __init__(self) -> None:
            raise AssertionError("TTS must not construct Pidog for speech")

    pidog_module = types.ModuleType("pidog")
    pidog_module.Pidog = FakePidog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pidog", pidog_module)
    vm = module()

    hear_a_question(vm, context(backend="pidog"))

    assert transcript.said == [("Piper", UTTERANCE)]


def test_auto_falls_back_to_pyttsx3_without_a_vendor_stack(monkeypatch) -> None:
    """A lite install has no `robot_hat`; the local engine is the last resort, not an error."""
    hide_vendor(monkeypatch)
    engine = install_pyttsx3(monkeypatch)
    vm = module()

    hear_a_question(vm, context(backend="auto"))

    assert engine.said == [UTTERANCE]


def test_a_named_vendor_backend_does_not_fall_back(monkeypatch) -> None:
    """A user who asked for one engine does not get another voice when it fails."""
    transcript = install_vendor(monkeypatch, failing=("Espeak",))
    engine = install_pyttsx3(monkeypatch)
    vm = module()

    hear_a_question(vm, context(enabled=True, backend="espeak"))

    assert transcript.said == []
    assert transcript.built == ["Espeak"]
    assert engine.said == []


def test_an_explicit_pyttsx3_backend_ignores_the_vendor_voice(monkeypatch) -> None:
    """The reported case of #8: asking for pyttsx3 must not build a vendor engine at all."""
    transcript = install_vendor(monkeypatch)
    engine = install_pyttsx3(monkeypatch)
    vm = module()

    hear_a_question(vm, context(enabled=True, backend="pyttsx3"))

    assert engine.said == [UTTERANCE]
    assert transcript.built == []


def test_a_broken_vendor_engine_is_probed_once(monkeypatch) -> None:
    """A missing dependency must not re-raise on every utterance: two ticks, one attempt."""
    transcript = install_vendor(monkeypatch, broken=("Piper",))
    engine = install_pyttsx3(monkeypatch)
    vm = module()

    hear_a_question(vm, context(backend="auto"))
    vm._last_command_ts = 0.0
    hear_a_question(vm, context(backend="auto"))

    assert transcript.built.count("Piper") == 1
    assert transcript.said == [("EdgeTTS", UTTERANCE), ("EdgeTTS", UTTERANCE)]
    assert engine.said == []


def test_a_config_without_the_tts_table_keeps_the_auto_chain(monkeypatch) -> None:
    """A hand-trimmed older config has no `tts` key; it keeps `auto`, not silence."""
    transcript = install_vendor(monkeypatch)
    vm = module()

    hear_a_question(vm, context())

    assert transcript.said == [("Piper", UTTERANCE)]
