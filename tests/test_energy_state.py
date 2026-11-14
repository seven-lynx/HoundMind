from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.optional.energy_emotion import EnergyEmotionModule


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_energy_initial_and_decay():
    ctx = DummyContext()
    ctx.set("settings", {"energy": {"enabled": True, "initial": 0.5, "decay_per_tick": 0.1}})
    module = BehaviorModule("behavior")

    # first tick: energy initialized then decayed
    module.tick(ctx)
    energy = ctx.get("energy_level")
    assert energy is not None
    assert abs(energy - 0.4) < 1e-6


def test_energy_boost_on_touch_and_sound():
    ctx = DummyContext()
    ctx.set("settings", {"energy": {"enabled": True, "initial": 0.2, "decay_per_tick": 0.01, "boost_touch": 0.15, "boost_sound": 0.05}})
    module = BehaviorModule("behavior")

    # touch stimulus should increase energy then decay
    ctx.set("perception", {"touch": "T"})
    module.tick(ctx)
    e1 = ctx.get("energy_level")
    assert e1 is not None and e1 > 0.2

    # sound stimulus should increase energy then decay
    ctx.data.pop("perception", None)
    ctx.set("perception", {"sound": True})
    module.tick(ctx)
    e2 = ctx.get("energy_level")
    assert e2 is not None and e2 > e1


def test_an_obstacle_boosts_the_reading_like_the_other_stimuli():
    """The boost used to live in `energy_emotion`; one producer must not lose it (#85)."""
    ctx = DummyContext()
    ctx.set(
        "settings",
        {
            "energy": {
                "enabled": True,
                "initial": 0.5,
                "decay_per_tick": 0.0,
                "boost_obstacle": 0.1,
            }
        },
    )
    ctx.set("perception", {"obstacle": True})

    BehaviorModule("behavior").tick(ctx)

    assert abs(ctx.get("energy_level") - 0.6) < 1e-9


def test_the_emotion_module_derives_instead_of_producing():
    """It reads `energy_level` and publishes the hint and label; the reading itself is untouched."""
    ctx = DummyContext()
    ctx.set("settings", {"energy": {"enabled": True}, "emotion": {"led_enabled": False}})
    ctx.set("energy_level", 0.2)
    module = EnergyEmotionModule("energy_emotion")

    module.tick(ctx)

    assert ctx.get("energy_level") == 0.2
    assert ctx.get("energy_speed_hint") == "slow"
    assert ctx.get("emotion_state") == "tired"


def test_both_switched_on_still_decay_once_per_tick():
    """The bug #85 described: two producers, two decays, a rate that depended on module order."""
    ctx = DummyContext()
    ctx.set("settings", {"energy": {"enabled": True, "initial": 0.5, "decay_per_tick": 0.1}})
    behavior = BehaviorModule("behavior")
    emotion = EnergyEmotionModule("energy_emotion")

    behavior.tick(ctx)
    assert abs(ctx.get("energy_level") - 0.4) < 1e-9

    emotion.tick(ctx)
    assert abs(ctx.get("energy_level") - 0.4) < 1e-9, "the derived module must not decay it again"

    behavior.tick(ctx)
    assert abs(ctx.get("energy_level") - 0.3) < 1e-9


def test_the_emotion_module_without_a_reading_publishes_nothing(caplog):
    """No reading means nothing to derive, and one warning rather than an invented value."""
    ctx = DummyContext()
    ctx.set("settings", {"energy": {"enabled": False}})
    module = EnergyEmotionModule("energy_emotion")

    with caplog.at_level("WARNING"):
        module.tick(ctx)
        module.tick(ctx)

    assert ctx.get("energy_speed_hint") is None
    assert ctx.get("emotion_state") is None
    assert ctx.get("energy_level") is None
    warnings = [r for r in caplog.records if "energy_level" in r.getMessage()]
    assert len(warnings) == 1
