"""`behavior/fsm.py` entry beats: one expression per state, on the transition, never per tick.

The edge is the FSM's own: every transition site sets `entered_state`, and the beat is the last write
before the publish, so the cooldown and micro-idle blocks cannot replace it. These tests are that
claim, plus the two refusals that keep the table from becoming a second way to walk the dog.
"""

from __future__ import annotations

import importlib

import pytest

from houndmind_ai.behavior.fsm import BehaviorModule, BehaviorState
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.intents import IntentBoard

T0 = 1000.0

# What `core/config.py` puts in `settings.behavior.action_classes`, in miniature: the loader's shape,
# not a hand-built one. Without it the repertoire only knows the twelve built-in actions.
ACTION_CLASSES = {
    "head_up_down": {"class": "expression"},
    "wag_tail": {"class": "expression"},
    "tilting_head": {"class": "expression"},
    "relax_neck": {"class": "expression"},
    "nod": {"class": "expression"},
    "bark": {"class": "expression"},
}


def _module(monkeypatch, **behavior_settings):
    mod = BehaviorModule("behavior", enabled=True)
    ctx = RuntimeContext()
    board = IntentBoard()
    ctx.set("intent_board", board)
    settings = {
        "autonomy_modes": ["idle"],
        "random_idle_chance": 0.0,
        "catalog": {"idle": ["sit"], "alert": ["bark"], "rest": ["lie"], "play": ["stretch"]},
        "action_classes": ACTION_CLASSES,
    }
    settings.update(behavior_settings)
    ctx.set("settings", {"behavior": settings})
    fsm_mod = importlib.import_module("houndmind_ai.behavior.fsm")
    monkeypatch.setattr(fsm_mod.time, "time", lambda: T0)
    return mod, ctx, board


def _published(board: IntentBoard) -> str | None:
    command = board.find(Source.BEHAVIOUR)
    return None if command is None else command.action


def test_entering_alert_publishes_the_beat(monkeypatch):
    mod, ctx, board = _module(monkeypatch, state_expressions={"alert": {"action": "head_up_down"}})
    mod.tick(ctx)
    assert _published(board) == "sit", "idle has no entry in this table, so the idle pick is used"

    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)

    assert mod.state is BehaviorState.ALERT
    assert _published(board) == "head_up_down"
    assert mod.last_action == "head_up_down", "the beat is what the cooldown holds, so it must be current"


def test_holding_the_state_never_repeats_the_beat(monkeypatch):
    mod, ctx, board = _module(monkeypatch, state_expressions={"alert": {"action": "head_up_down"}})
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    assert _published(board) == "head_up_down"

    mod.tick(ctx)
    assert _published(board) == "bark", "the tick after the entry belongs to the state, not the beat"

    mod.tick(ctx)
    assert _published(board) == "bark"


def test_micro_idle_cannot_swallow_the_beat(monkeypatch):
    """Micro-idle ships enabled and rewrites the action; the beat is applied after it, on purpose."""
    mod, ctx, board = _module(
        monkeypatch,
        state_expressions={"idle": {"action": "relax_neck"}},
        micro_idle_enabled=True,
        micro_idle_chance=1.0,
        micro_idle_actions=["nod"],
        micro_idle_interval_s=0.0,
    )
    ctx.set("energy_level", 0.1)
    mod.tick(ctx)
    assert mod.state is BehaviorState.REST

    ctx.set("energy_level", 0.6)
    mod.tick(ctx)

    assert mod.state is BehaviorState.IDLE
    assert _published(board) == "relax_neck", "micro-idle chose nod; the entry beat wins the tick"


def test_no_table_means_no_beat(monkeypatch):
    mod, ctx, board = _module(monkeypatch)
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    assert _published(board) == "bark", "an absent table must leave the state's own action alone"


def test_micro_idle_still_runs_when_no_beat_is_configured(monkeypatch):
    """The companion to the ordering test above: without it, that test could pass vacuously."""
    mod, ctx, board = _module(
        monkeypatch,
        micro_idle_enabled=True,
        micro_idle_chance=1.0,
        micro_idle_actions=["nod"],
        micro_idle_interval_s=0.0,
    )
    ctx.set("energy_level", 0.1)
    mod.tick(ctx)
    ctx.set("energy_level", 0.6)
    mod.tick(ctx)

    assert mod.state is BehaviorState.IDLE
    assert _published(board) == "nod", "micro-idle owns an idle-entry tick when no beat is configured"


def test_an_unknown_beat_is_refused_and_warned_once(caplog):
    mod = BehaviorModule("behavior", enabled=True)
    settings = {
        "state_expressions": {"alert": {"action": "teleport"}},
        "action_classes": ACTION_CLASSES,
    }
    with caplog.at_level("WARNING"):
        assert mod._entry_beat(settings, BehaviorState.ALERT, "bark") is None
        assert mod._entry_beat(settings, BehaviorState.ALERT, "bark") is None

    warnings = [r for r in caplog.records if "teleport" in r.getMessage()]
    assert len(warnings) == 1, "a typo is one warning, not one per transition"


def test_a_locomotion_beat_is_refused(caplog):
    mod = BehaviorModule("behavior", enabled=True)
    settings = {"state_expressions": {"alert": {"action": "forward"}}}
    with caplog.at_level("WARNING"):
        assert mod._entry_beat(settings, BehaviorState.ALERT, "bark") is None
    assert any("locomotion is not an expression" in r.getMessage() for r in caplog.records)


def test_a_beat_never_displaces_a_step():
    mod = BehaviorModule("behavior", enabled=True)
    settings = {
        "state_expressions": {"patrol": {"action": "tilting_head"}},
        "action_classes": ACTION_CLASSES,
    }
    assert mod._entry_beat(settings, BehaviorState.PATROL, "forward") is None
    assert mod._entry_beat(settings, BehaviorState.PATROL, "bark") == "tilting_head"


@pytest.mark.parametrize("entry", ["nod", {}, {"action": ""}, {"action": None}, {"other": "nod"}])
def test_a_malformed_entry_is_no_beat(entry):
    mod = BehaviorModule("behavior", enabled=True)
    assert mod._entry_beat({"state_expressions": {"alert": entry}}, BehaviorState.ALERT, "bark") is None


CUE_SOUNDS = ["single_bark_1", "woohoo", "pant", "snoring"]


def test_the_entry_command_carries_the_beat_and_its_cue(monkeypatch):
    """One command, one tick: the cue rides the beat instead of competing with it for the source."""
    mod, ctx, board = _module(
        monkeypatch,
        state_expressions={"alert": {"action": "head_up_down", "sound": "single_bark_1"}},
        cue_sounds=CUE_SOUNDS,
        cue_volume=55,
    )
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)

    command = board.find(Source.BEHAVIOUR)
    assert command.action == "head_up_down"
    assert command.params == {"cue": {"name": "single_bark_1", "volume": 55}}


def test_quiet_mode_drops_the_cue_and_keeps_the_beat(monkeypatch):
    mod, ctx, board = _module(
        monkeypatch,
        state_expressions={"alert": {"action": "head_up_down", "sound": "single_bark_1"}},
        cue_sounds=CUE_SOUNDS,
    )
    ctx.set("quiet_mode_active", True)
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)

    command = board.find(Source.BEHAVIOUR)
    assert command.action == "head_up_down"
    assert "cue" not in command.params


def test_a_cue_rides_a_locomotion_command_without_displacing_it(monkeypatch):
    """A cue belongs to the transition, not to the beat — and it must never cost the step it rides.

    `autonomy_modes` cannot reach `patrol` today (#82), so the locomotion entry is staged through the
    override path: it resolves `patrol_behavior`, which publishes a step rather than a posture.
    """
    mod, ctx, board = _module(
        monkeypatch,
        catalog={"rest": ["lie"], "patrol": ["forward"]},
        state_expressions={"idle": {"sound": "pant"}},
        cue_sounds=CUE_SOUNDS,
    )
    ctx.set("energy_level", 0.1)
    mod.tick(ctx)
    assert mod.state is BehaviorState.REST

    ctx.set("behavior_override", "patrol_behavior")
    mod.tick(ctx)

    assert mod.state is BehaviorState.IDLE
    command = board.find(Source.BEHAVIOUR)
    assert command.action == "forward"
    assert command.params == {"cue": {"name": "pant", "volume": 60}}


def test_a_cue_outside_the_advisory_list_is_warned_once_and_still_played(caplog):
    mod = BehaviorModule("behavior", enabled=True)
    settings = {
        "state_expressions": {"alert": {"sound": "custom_woof"}},
        "cue_sounds": CUE_SOUNDS,
    }
    with caplog.at_level("WARNING"):
        first = mod._entry_cue(settings, BehaviorState.ALERT, False)
        second = mod._entry_cue(settings, BehaviorState.ALERT, False)

    assert first == second == {"name": "custom_woof", "volume": 60}
    warnings = [r for r in caplog.records if "custom_woof" in r.getMessage()]
    assert len(warnings) == 1, "the advisory list is a hint, warned once per name"


def test_the_cue_volume_is_defaulted_and_clamped():
    mod = BehaviorModule("behavior", enabled=True)

    def cue(**behavior) -> dict | None:
        settings = {"state_expressions": {"alert": {"sound": "woohoo"}}}
        settings.update(behavior)
        return mod._entry_cue(settings, BehaviorState.ALERT, False)

    assert cue()["volume"] == 60
    assert cue(cue_volume=500)["volume"] == 100
    assert cue(cue_volume=-5)["volume"] == 0
    assert cue(cue_volume="loud")["volume"] == 60


def test_a_beat_without_a_cue_publishes_no_params(monkeypatch):
    mod, ctx, board = _module(
        monkeypatch,
        state_expressions={"alert": {"action": "head_up_down"}},
        cue_sounds=CUE_SOUNDS,
    )
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    assert board.find(Source.BEHAVIOUR).params == {}


@pytest.mark.parametrize(
    "entry", ["woohoo", {}, {"sound": ""}, {"sound": None}, {"sound": 5}]
)
def test_a_malformed_cue_is_no_cue(entry):
    mod = BehaviorModule("behavior", enabled=True)
    assert mod._entry_cue({"state_expressions": {"alert": entry}}, BehaviorState.ALERT, False) is None

