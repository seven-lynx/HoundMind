"""The phrase map is a motion path, and no test read it (#321).

`config/settings.jsonc` ships fourteen phrases and four aliases. `optional/voice.py` resolves one
into `behavior_override`, `behavior/fsm.py` publishes that as a behaviour intent, and the gateway
runs it through the interlock like any other producer. Nothing read the map at all, so a phrase
could name an action the vocabulary no longer had: the log said `Voice command -> ...` and the dog
sat there, refused for `unknown_action`.

These tests read the shipped file and drive the real path with no microphone - a `voice_text`
through `VoiceModule.tick`, the FSM's one-line publish, then `MotionGatewayModule.tick` against a
`SensorReading` the way `tests/test_gateway.py` does. Nothing sleeps and nothing moves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from houndmind_ai.act.gateway import MotionGatewayModule, canonical_action, legacy_action
from houndmind_ai.act.interlock import Interlock
from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.commands import KNOWN_ACTIONS, Source
from houndmind_ai.kernel.intents import IntentBoard
from houndmind_ai.optional.voice import VoiceModule

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"

# The shipped file with one change: the table ships `enabled: false`, and a disabled table is a
# no-op `tests/test_voice_tts.py` already pins. Turning it on is the user's action, so the phrases
# are read here the way a dog that has them would.
SHIPPED = load_config(SETTINGS_FILE).settings
VOICE = dict(SHIPPED["voice_assistant"], enabled=True)
SETTINGS = dict(SHIPPED, voice_assistant=VOICE)


class Clock:
    """The board, the interlock and the gateway share one injected clock: nothing sleeps."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def reading(battery_v: float | None = 7.8) -> SensorReading:
    """A clear path, upright, and a pack above the floor unless a caller says otherwise."""
    return SensorReading(
        distance_cm=120.0,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=(0.0, 0.0, 9.8),
        gyro=(0.0, 0.0, 0.0),
        timestamp=1000.0,
        distance_valid=True,
        touch_valid=True,
        sound_valid=True,
        imu_valid=True,
        battery_v=battery_v,
        battery_valid=battery_v is not None,
    )


def harness(battery_v: float | None = 7.8) -> tuple[MotionGatewayModule, RuntimeContext]:
    """A gateway on the shipped classification, wired the way `main.build_registry` wires it."""
    clock = Clock()
    gateway = MotionGatewayModule(
        "motion_gateway",
        interlock=Interlock(now=clock),
        clock=clock,
        board=IntentBoard(clock=clock),
    )
    context = RuntimeContext()
    # The runtime publishes the loaded config under `settings`; `start` installs the classification
    # from it and publishes the `intent_board` a producer publishes into.
    context.set("settings", SETTINGS)
    gateway.start(context)
    context.set("sensor_reading", reading(battery_v))
    return gateway, context


def utterances() -> list[tuple[str, str]]:
    """Every phrase and alias the shipped map recognises, with the action it produces.

    The resolver is the module's own (`VoiceModule._resolve_action`), not a copy of it: a second
    implementation of the map is the defect this file exists to catch.
    """
    mapping = VOICE.get("command_map", {})
    aliases = VOICE.get("aliases", {})
    voice = VoiceModule("voice")
    pairs: list[tuple[str, str]] = []
    for spoken in list(mapping) + list(aliases):
        resolved = voice._resolve_action(voice._normalize(spoken), mapping, aliases)
        pairs.append((spoken, "" if resolved is None else str(resolved)))
    return pairs


UTTERANCES = utterances()


def vocabulary(settings: dict[str, Any]) -> frozenset[str]:
    """Every action name this runtime can be asked to perform.

    `kernel/commands.py`'s `KNOWN_ACTIONS` is the built-in subset; `config/actions.jsonc` adds the
    vendor `ActionFlow` names a phrase may legitimately use (`shake head` is one). The two together
    are what the control plane offers and what the interlock can judge, and
    `tests/test_actions_catalog.py` holds the built-ins to the same table.
    """
    return frozenset(KNOWN_ACTIONS) | repertoire_from_settings(settings).known()


# ---------------------------------------------------------------- the shipped map


@pytest.mark.parametrize("spoken,action", UTTERANCES)
def test_every_phrase_names_an_action_the_interlock_can_judge(spoken: str, action: str) -> None:
    """Deleting an action from the vocabulary must fail here, naming the phrase that used it."""
    assert action, f"{spoken!r} resolves to no action at all"
    assert canonical_action(action) in vocabulary(SETTINGS), (
        f"{spoken!r} names {action!r}, which is in neither KNOWN_ACTIONS nor `config/actions.jsonc`"
    )


def test_no_alias_points_at_a_missing_phrase() -> None:
    """An alias is a second spelling of a `command_map` key, not a second map.

    `VoiceModule._resolve_action` accepts an alias that names no phrase and hands it on as if it
    were an action, so a typo in `aliases` would reach the interlock as `unknown_action` while the
    config looked fine.
    """
    mapping = VOICE.get("command_map", {})
    missing = sorted(
        alias for alias, target in VOICE.get("aliases", {}).items() if target not in mapping
    )
    assert missing == [], f"aliases name phrases the map does not have: {missing}"


def test_deleting_an_action_from_the_vocabulary_names_the_phrase_that_used_it() -> None:
    """The guard is not vacuous - #321's done-means, proved without editing the shipped file.

    `shake head` is classified in `config/actions.jsonc` and nowhere else (the built-ins in
    `kernel/actions.py` stop at `wag_tail` and `bark`), so dropping it is exactly what deleting an
    action from the vocabulary looks like.
    """
    classes = {
        name: entry
        for name, entry in SHIPPED["behavior"]["action_classes"].items()
        if name != "shake_head"
    }
    stripped = dict(SETTINGS, behavior={"action_classes": classes})

    lost = [
        f"{spoken!r} -> {action!r}"
        for spoken, action in UTTERANCES
        if canonical_action(action) not in vocabulary(stripped)
    ]

    assert lost, "removing `shake head` left no phrase unjudgeable; the check cannot bite"
    assert sorted(lost) == ["'shake head' -> 'shake head'", "'shake' -> 'shake head'"], lost


# ------------------------------------------------------------ the path it travels


@pytest.mark.parametrize("spoken,action", UTTERANCES)
def test_a_phrase_reaches_the_intent_board_and_the_interlock(spoken: str, action: str) -> None:
    """Voice names an action, the FSM publishes it, the gateway judges it. One route, one envelope."""
    gateway, context = harness()
    voice = VoiceModule("voice")
    voice.start(context)

    context.set("voice_text", spoken)
    voice.tick(context)

    published = context.get("behavior_override")
    assert published == action, f"{spoken!r} published {published!r}, not {action!r}"
    # `behavior_override` is the whole of the module's claim. Writing motion itself would be the
    # unauthenticated 8091 path again, with a nicer voice.
    assert context.get("motion_command") is None, f"{spoken!r} wrote motion without an intent"
    assert context.get("motion_verdict") is None, f"{spoken!r} bypassed the gateway"

    # `BehaviorFSMModule._publish` is this one line. Running the FSM to reach it would drag in the
    # clock, the behaviour library and the idle rotation for no extra coverage.
    context.get("intent_board").publish(published, Source.BEHAVIOUR)
    gateway.tick(context)

    verdict = context.get("motion_verdict")
    command = context.get("motion_command")
    assert verdict is not None and verdict["accepted"] is True, (spoken, verdict)
    assert command is not None, spoken
    assert command["canonical_action"] == canonical_action(action)
    # What the HAL is handed keeps the vendor's spelling (`turn left`, `wag tail`).
    assert command["action"] == legacy_action(canonical_action(action))


def test_a_flat_pack_refuses_the_phrase_loudly_rather_than_silently() -> None:
    """A phrase is judged like any other request: the veto is the proof the interlock was on the path."""
    gateway, context = harness(battery_v=5.0)
    voice = VoiceModule("voice")
    voice.start(context)

    context.set("voice_text", "forward")
    voice.tick(context)
    context.get("intent_board").publish(context.get("behavior_override"), Source.BEHAVIOUR)
    gateway.tick(context)

    verdict = context.get("motion_verdict")
    assert context.get("motion_command") is None
    assert verdict is not None
    assert verdict["status"] == "refused"
    assert verdict["veto"] == "low_voltage"


# ------------------------------------------------------------ the escape hatch (#386)


def test_a_shipped_phrase_reaches_stop() -> None:
    """#386: the word an operator shouts must resolve to the one action nothing vetoes.

    The shipped map pointed `stop` at `lie`, a posture, so the escape hatch spent the tilt latch,
    the battery floor and the deadman - the dog that most needs stopping was the one refused.
    """
    stopping = sorted(spoken for spoken, action in UTTERANCES if action == "stop")

    assert "stop" in stopping, f"no shipped phrase resolves to `stop`: {UTTERANCES}"
    assert "halt" in stopping, "the alias must follow the phrase it names"


def test_the_stop_phrase_survives_a_flat_pack() -> None:
    """Same pack, same tick list as the refusal above: `lie` is vetoed, `stop` is not."""
    gateway, context = harness(battery_v=5.0)
    voice = VoiceModule("voice")
    voice.start(context)

    context.set("voice_text", "stop")
    voice.tick(context)
    context.get("intent_board").publish(context.get("behavior_override"), Source.BEHAVIOUR)
    gateway.tick(context)

    verdict = context.get("motion_verdict")
    command = context.get("motion_command")
    assert verdict is not None and verdict["accepted"] is True, verdict
    assert command is not None and command["canonical_action"] == "stop"


def test_the_stop_phrase_survives_the_tilt_latch() -> None:
    """A dog on its side can still be told to stop - that is the whole reason `stop` is exempt."""
    gateway, context = harness()
    voice = VoiceModule("voice")
    voice.start(context)

    # Latch the tilt through the path that latches it: a tilted snapshot judging a moving action.
    context.set("tilt_warning", {"pitch": 89.0, "roll": 89.0})
    context.get("intent_board").publish("lie", Source.BEHAVIOUR)
    gateway.tick(context)
    assert context.get("motion_verdict")["veto"] == "tilt"
    assert context.get("motion_command") is None

    context.set("voice_text", "stop")
    voice.tick(context)
    context.get("intent_board").publish(context.get("behavior_override"), Source.BEHAVIOUR)
    gateway.tick(context)

    verdict = context.get("motion_verdict")
    assert verdict is not None and verdict["accepted"] is True, verdict
    assert context.get("motion_command") is not None, "the escape hatch published no motion"
