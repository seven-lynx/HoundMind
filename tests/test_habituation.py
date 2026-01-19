from houndmind_ai.behavior.fsm import BehaviorModule
import time


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_habituation_suppresses_repeated_sound():
    ctx = DummyContext()
    # enable habituation with low threshold for test speed
    ctx.set("settings", {"behavior": {"habituation_enabled": True, "habituation_threshold": 2, "habituation_recovery_s": 0.5}})
    module = BehaviorModule("behavior")

    # first sound: should set behavior_action
    ctx.set("perception", {"sound": True})
    module.tick(ctx)
    assert ctx.get("behavior_action") is not None

    # clear action between ticks
    ctx.data.pop("behavior_action", None)

    # second sound: reaches threshold -> habituated (suppressed)
    ctx.set("perception", {"sound": True})
    module.tick(ctx)
    # habituation should suppress action (no new behavior_action set)
    assert ctx.get("behavior_action") is None
    assert ctx.get("behavior_habituation") is not None

    # wait for recovery and ensure sound is responded to again
    time.sleep(0.6)
    ctx.data.pop("behavior_habituation", None)
    ctx.set("perception", {"sound": True})
    module.tick(ctx)
    assert ctx.get("behavior_action") is not None
