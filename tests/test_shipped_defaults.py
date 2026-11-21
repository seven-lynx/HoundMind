"""What the shipped `config/settings.jsonc` decides by itself, pinned so it cannot drift back (#390).

The shipped config set `behavior.autonomy_enabled: true`, and `autonomy_modes` offers `explore`, whose
action is `forward` — so an install that ended with `systemctl enable --now` had a dog that walked off
on its own: 237 granted `forward`/`trot`/`turn_left`/`turn_right` in seven minutes, every one of them a
behaviour intent the gateway preferred over navigation's `stand`. Safety ships off in this repo for bug
testing; autonomous motion is the same kind of decision and it is not the installer's to make silently.

Two gates, four tests. The file is read the way `tests/test_actions_catalog.py` reads the shipped
catalog — raw, then through `load_config`, so a profile overlay cannot flip it back either. The FSM is
then driven with the key **absent**, because a config that predates `autonomy_enabled` is exactly the
install that used to walk, and its companion test proves the same table does reach `explore` once the
key says so — the pair cannot pass vacuously.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import json5

from houndmind_ai.behavior.fsm import BehaviorModule, BehaviorState
from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.actions import ActionClass, repertoire_from_settings
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.intents import IntentBoard

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"
T0 = 1000.0


def shipped() -> dict:
    return json5.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the shipped file


def test_the_shipped_config_ships_autonomy_off() -> None:
    """The file a fresh install gets: nothing switches autonomy on for the user."""
    assert shipped()["settings"]["behavior"]["autonomy_enabled"] is False


def test_the_loaded_config_ships_autonomy_off() -> None:
    """The value the runtime actually reads, after the profile overlay has had its say."""
    assert load_config(SETTINGS_FILE).settings["behavior"]["autonomy_enabled"] is False


# ------------------------------------------------------------------- the FSM's own gate


def _module(monkeypatch, **behavior_settings):
    """A behaviour module whose only mode is `explore`, so the walk is one branch away."""
    mod = BehaviorModule("behavior", enabled=True)
    ctx = RuntimeContext()
    board = IntentBoard()
    ctx.set("intent_board", board)
    settings = {
        # `explore_action` ships `forward` — a gait-class action, and the one #390 heard on the bench.
        "random_idle_chance": 0.0,
        "autonomy_modes": ["explore"],
        "catalog": {"idle": ["sit"], "explore": ["forward"]},
    }
    settings.update(behavior_settings)
    ctx.set("settings", {"behavior": settings})
    fsm_mod = importlib.import_module("houndmind_ai.behavior.fsm")
    monkeypatch.setattr(fsm_mod.time, "time", lambda: T0)
    return mod, ctx, board


def test_a_config_with_no_autonomy_key_cannot_publish_a_gait(monkeypatch) -> None:
    """The absent key is the second gate: a pre-#390 config must not walk by omission."""
    mod, ctx, board = _module(monkeypatch)
    mod.tick(ctx)

    assert mod.state is BehaviorState.IDLE
    command = board.find(Source.BEHAVIOUR)
    assert command is not None, "an idle dog still offers its idle action"
    action_class = repertoire_from_settings(ctx.get("settings")).classify(command.action)
    assert action_class is not None
    assert action_class is not ActionClass.LOCOMOTION


def test_the_same_table_reaches_explore_once_the_key_says_so(monkeypatch) -> None:
    """The companion: without it, the test above could pass because `explore` was never reachable."""
    mod, ctx, board = _module(monkeypatch, autonomy_enabled=True)
    mod.tick(ctx)

    assert mod.state is BehaviorState.EXPLORE
    command = board.find(Source.BEHAVIOUR)
    assert repertoire_from_settings(ctx.get("settings")).classify(
        command.action
    ) is ActionClass.LOCOMOTION
