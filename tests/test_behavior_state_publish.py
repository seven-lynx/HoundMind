import importlib

from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.intents import IntentBoard

T0 = 1000.0


def _module(monkeypatch, **behavior_settings):
    mod = BehaviorModule("behavior", enabled=True)
    ctx = RuntimeContext()
    ctx.set("intent_board", IntentBoard())
    settings = {"autonomy_modes": ["idle"]}
    settings.update(behavior_settings)
    ctx.set("settings", {"behavior": settings})
    fsm_mod = importlib.import_module("houndmind_ai.behavior.fsm")
    monkeypatch.setattr(fsm_mod.time, "time", lambda: T0)
    return mod, ctx


def test_a_tick_publishes_the_fsm_state(monkeypatch):
    mod, ctx = _module(monkeypatch)
    mod.tick(ctx)
    assert ctx.get("behavior_state") == "idle"


def test_a_transition_republishes_the_new_state(monkeypatch):
    mod, ctx = _module(monkeypatch)
    # Energy under the rest threshold forces the rest mode, so the state leaves idle.
    ctx.set("energy_level", 0.1)
    mod.tick(ctx)
    assert ctx.get("behavior_state") == "rest"

    ctx.set("energy_level", 0.6)
    mod.tick(ctx)
    assert ctx.get("behavior_state") == "idle"


def test_the_state_is_published_before_a_habituated_tick_returns_early(monkeypatch):
    mod, ctx = _module(monkeypatch, habituation_enabled=True, habituation_threshold=2)
    # Start in rest, so the tick that returns early is also the tick that changes the state.
    ctx.set("energy_level", 0.1)
    mod.tick(ctx)
    assert ctx.get("behavior_state") == "rest"

    # Two touches reach the threshold; from then on the stimulus is treated as absent.
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    assert ctx.get("behavior_state") == "rest"

    # The third touch is suppressed, the state returns to idle, and the tick ends at the
    # habituated-stimulus return: a publish placed after that return would still say rest.
    ctx.set("energy_level", 0.6)
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    assert mod.state.value == "idle"
    assert ctx.get("behavior_state") == "idle"
