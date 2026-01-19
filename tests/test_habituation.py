from houndmind_ai.behavior.habituation import HabituationModule


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_habituation_triggers_and_recovers(monkeypatch):
    # Control time within the module to simulate rapid events and recovery
    t = {"now": 0.0}

    monkeypatch.setattr(
        "houndmind_ai.behavior.habituation.time.time", lambda: t["now"]
    )

    ctx = DummyContext()
    ctx.set("settings", {"habituation": {"enabled": True, "stimuli": ["sound"], "window_s": 1.0, "threshold": 3, "recovery_s": 2.0}})
    module = HabituationModule("habituation")

    # First event
    ctx.set("perception", {"sound": True})
    module.tick(ctx)
    assert not ctx.get("habituation:sound:habituated")

    # Second event within window
    t["now"] += 0.5
    module.tick(ctx)
    assert not ctx.get("habituation:sound:habituated")

    # Third event within window -> should habituate
    t["now"] += 0.5
    module.tick(ctx)
    assert ctx.get("habituation:sound:habituated") is True

    # After recovery window with no events, habituation should clear
    t["now"] += 3.0
    ctx.set("perception", {"sound": False})
    module.tick(ctx)
    # Next tick should have cleared habituation (count reset)
    assert ctx.get("habituation:sound:habituated") in (False, None)
