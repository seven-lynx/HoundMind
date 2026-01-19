from houndmind_ai.behavior.habituation import HabituationModule


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_habituation_multiple_stimuli_and_thresholds(monkeypatch):
    t = {"now": 0.0}
    monkeypatch.setattr("houndmind_ai.behavior.habituation.time.time", lambda: t["now"]) 

    ctx = DummyContext()
    # configure both sound and touch with different thresholds
    ctx.set(
        "settings",
        {
            "habituation": {
                "enabled": True,
                "stimuli": ["sound", "touch"],
                "window_s": 1.0,
                "threshold": 2,
                "recovery_s": 2.0,
            }
        },
    )
    module = HabituationModule("habituation")

    # Sound events: two quick events -> habituated
    ctx.set("perception", {"sound": True, "touch": False})
    module.tick(ctx)
    assert not ctx.get("habituation:sound:habituated")
    t["now"] += 0.3
    module.tick(ctx)
    assert ctx.get("habituation:sound:habituated") is True

    # Touch events should be independent and not yet habituated
    ctx.set("perception", {"sound": False, "touch": True})
    t["now"] += 0.1
    module.tick(ctx)
    assert not ctx.get("habituation:touch:habituated")

    # Second touch within window should habituate touch
    t["now"] += 0.2
    module.tick(ctx)
    assert ctx.get("habituation:touch:habituated") is True

    # Verify LED request and telemetry snapshot exist for sound and touch
    assert ctx.get("led_request:habituation:sound") is not None
    assert ctx.get("telemetry:habituation:sound") is not None
    assert ctx.get("led_request:habituation:touch") is not None
    assert ctx.get("telemetry:habituation:touch") is not None

    # Advance beyond recovery and ensure flags clear
    t["now"] += 3.0
    ctx.set("perception", {"sound": False, "touch": False})
    module.tick(ctx)
    assert ctx.get("habituation:sound:habituated") in (False, None)
    assert ctx.get("habituation:touch:habituated") in (False, None)
