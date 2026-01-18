from houndmind_ai.logging.led_manager import LedManagerModule


class DummyStrip:
    def __init__(self):
        self.calls = []

    def set_mode(self, mode, color, brightness=0.7, bps=None):
        self.calls.append((mode, color, brightness, bps))


class DummyDog:
    def __init__(self):
        self.rgb_strip = DummyStrip()


class DummyContext:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_led_manager_priority_selection():
    ctx = DummyContext()
    ctx.set("pidog", DummyDog())
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
    assert dog.rgb_strip.calls, "LED manager should update strip"
    mode, color, _, _ = dog.rgb_strip.calls[-1]
    assert mode == "boom"
    assert color == "red"
