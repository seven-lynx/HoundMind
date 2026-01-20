import importlib
from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.core.runtime import RuntimeContext


def test_behavior_action_cooldown(monkeypatch):
    mod = BehaviorModule("behavior", enabled=True)
    ctx = RuntimeContext()
    # minimal settings: enable autonomy so idle actions are chosen
    ctx.set("settings", {"behavior": {"action_cooldown_s": 0.5}})

    # control time inside the behavior module
    fsm_mod = importlib.import_module("houndmind_ai.behavior.fsm")
    t0 = 1000.0
    monkeypatch.setattr(fsm_mod.time, "time", lambda: t0)

    # first tick: should emit an action
    mod.tick(ctx)
    first = ctx.get("behavior_action")
    assert isinstance(first, str) and first

    # small advance, with a stimulus that would change the action
    monkeypatch.setattr(fsm_mod.time, "time", lambda: t0 + 0.1)
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    # still the same action due to cooldown
    assert ctx.get("behavior_action") == first

    # after cooldown, change should be allowed
    monkeypatch.setattr(fsm_mod.time, "time", lambda: t0 + 1.0)
    mod.tick(ctx)
    assert ctx.get("behavior_action") != first
