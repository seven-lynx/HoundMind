from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.safety.balance import BalanceModule


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_balance_module_sets_rpy():
    ctx = DummyContext()
    hal = FakeDogHAL()
    ctx.set("hal", hal)
    ctx.set(
        "settings",
        {"balance": {"enabled": True, "update_hz": 100.0, "active_when_moving": False}},
    )
    ctx.set("sensor_reading", type("R", (), {"acc": (0.0, 0.0, 1.0)})())

    module = BalanceModule("balance")
    module.tick(ctx)

    rpy_calls = [params for name, params in hal.calls if name == "rpy"]
    assert rpy_calls, "set_rpy should be reached when balance is enabled"
