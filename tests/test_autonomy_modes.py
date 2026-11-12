"""#82: `autonomy_modes` names modes, and the registry is keyed by `<mode>_behavior`.

The FSM handed the bare mode list to `pick_weighted`, which looks choices up in its own item table,
found none, returned `None`, and let the `or "idle"` fallback win every time — so `patrol`, `explore`
and `interact` were unreachable through autonomy, `autonomy_weights` was dead config for them, and the
personality multipliers multiplied nothing. `BehaviorRegistry.pick_mode` is the one place the two
vocabularies meet; these tests are that bridge, at the registry and through the FSM.
"""

from __future__ import annotations

import importlib

import pytest

from houndmind_ai.behavior.fsm import BehaviorModule, BehaviorState
from houndmind_ai.behavior.registry import BehaviorRegistry
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.intents import IntentBoard

T0 = 1000.0


def _module(monkeypatch, **behavior_settings):
    mod = BehaviorModule("behavior", enabled=True)
    ctx = RuntimeContext()
    ctx.set("intent_board", IntentBoard())
    settings = {
        "random_idle_chance": 0.0,
        "catalog": {
            "idle": ["sit"],
            "patrol": ["forward"],
            "explore": ["forward"],
            "interact": ["wag tail"],
            "play": ["stretch"],
            "rest": ["lie"],
        },
    }
    settings.update(behavior_settings)
    ctx.set("settings", {"behavior": settings})
    fsm_mod = importlib.import_module("houndmind_ai.behavior.fsm")
    monkeypatch.setattr(fsm_mod.time, "time", lambda: T0)
    return mod, ctx


def test_the_raw_registry_call_is_why_modes_were_unreachable() -> None:
    """The old call, pinned: a mode name is not an item name, so `pick_weighted` finds nothing."""
    registry = BehaviorRegistry()
    registry.register("patrol_behavior", lambda: "forward")

    assert registry.pick_weighted(["patrol"], {}) is None
    assert registry.pick_mode(["patrol"], {}) == "patrol"


def test_pick_mode_drops_a_mode_with_no_registered_item() -> None:
    registry = BehaviorRegistry()
    assert registry.pick_mode(["patrol"], {}) is None

    registry.register("patrol_behavior", lambda: "forward")
    assert registry.pick_mode(["nowhere"], {"patrol": 1.0}) is None


@pytest.mark.parametrize(
    ("mode", "state"),
    [
        ("patrol", BehaviorState.PATROL),
        ("explore", BehaviorState.EXPLORE),
        ("interact", BehaviorState.INTERACT),
        ("play", BehaviorState.PLAY),
        ("rest", BehaviorState.REST),
        ("idle", BehaviorState.IDLE),
    ],
)
def test_each_autonomy_mode_reaches_its_state(monkeypatch, mode, state) -> None:
    mod, ctx = _module(monkeypatch, autonomy_modes=[mode])
    mod.tick(ctx)
    assert mod.state is state


def test_a_mode_left_out_of_the_list_is_never_chosen(monkeypatch) -> None:
    mod, ctx = _module(monkeypatch, autonomy_modes=["patrol"])
    mod.tick(ctx)
    assert mod.state is BehaviorState.PATROL

    # The choice is held for `autonomy_interval_s` (8 s by default) and this tick is inside it.
    mod.tick(ctx)
    assert mod.state is BehaviorState.PATROL


def test_autonomy_off_stays_idle(monkeypatch) -> None:
    mod, ctx = _module(monkeypatch, autonomy_modes=["patrol"], autonomy_enabled=False)
    mod.tick(ctx)
    assert mod.state is BehaviorState.IDLE
