from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.logging.led_manager import LedManagerModule


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_led_manager_priority_selection():
    ctx = DummyContext()
    hal = FakeDogHAL()
    ctx.set("hal", hal)
    # The legacy vendor handle is present and must be ignored: the LED path goes via `hal`.
    ctx.set("pidog", type("Legacy", (), {})())
    ctx.set(
        "settings",
        {
            "led": {
                "enabled": True,
                "priority": ["safety", "navigation"],
                "cooldown_s": 0.0,
                "brightness": 0.7,
                "safety_color": "red",
                "safety_mode": "boom",
                "nav_mode": "breath",
            },
            "navigation": {"led_patrol_color": "green"},
        },
    )
    ctx.set("led_request:navigation", {"mode": "patrol"})
    ctx.set("led_request:safety", {"mode": "emergency"})

    module = LedManagerModule("led_manager")
    module.tick(ctx)

    dog = ctx.get("pidog")
    assert dog is not None, "the legacy handle should still be untouched by the LED module"
    rgb_calls = [params for name, params in hal.calls if name == "rgb"]
    assert rgb_calls, "LED manager should update the strip"
    assert rgb_calls[-1]["style"] == "boom"
    assert rgb_calls[-1]["color"] == "red"
