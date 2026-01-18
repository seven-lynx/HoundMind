from houndmind_ai.safety.balance import BalanceModule


class DummyDog:
    def __init__(self):
        self.calls = []

    def set_rpy(self, roll=0, pitch=0, yaw=0, pid=True):
        self.calls.append((roll, pitch, yaw, pid))


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_balance_module_sets_rpy():
    ctx = DummyContext()
    ctx.set("pidog", DummyDog())
    ctx.set(
        "settings",
        {"balance": {"enabled": True, "update_hz": 100.0, "active_when_moving": False}},
    )
    ctx.set("sensor_reading", type("R", (), {"acc": (0.0, 0.0, 1.0)})())

    module = BalanceModule("balance")
    module.tick(ctx)

    dog = ctx.get("pidog")
    assert dog.calls, "set_rpy should be called when enabled"
