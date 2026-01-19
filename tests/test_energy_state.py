from houndmind_ai.behavior.fsm import BehaviorModule


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_energy_initial_and_decay():
    ctx = DummyContext()
    ctx.set("settings", {"energy": {"initial": 0.5, "decay_per_tick": 0.1}})
    module = BehaviorModule("behavior")

    # first tick: energy initialized then decayed
    module.tick(ctx)
    energy = ctx.get("energy_level")
    assert energy is not None
    assert abs(energy - 0.4) < 1e-6


def test_energy_boost_on_touch_and_sound():
    ctx = DummyContext()
    ctx.set("settings", {"energy": {"initial": 0.2, "decay_per_tick": 0.01, "boost_touch": 0.15, "boost_sound": 0.05}})
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
