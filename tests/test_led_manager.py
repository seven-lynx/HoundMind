"""`logging/led_manager.py`: priority selection, request expiry and the return to idle.

The clock is injected rather than slept on: P3 L1 is about deadlines, and a test that waits 900 ms to
cross one is both slower and flakier than one that owns the clock — the same route
`kernel/intents.py` takes for an intent's hold window.
"""

from __future__ import annotations

from typing import Any

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.logging.led_manager import LedManagerModule


class DummyContext:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.writes: list[tuple[str, Any]] = []

    def set(self, key, value):
        self.data[key] = value
        self.writes.append((key, value))

    def get(self, key, default=None):
        return self.data.get(key, default)


class RacingContext(DummyContext):
    """A producer that refreshes the key between the manager's read and its clear (the H-02 window)."""

    def __init__(self, key: str, first: dict, second: dict) -> None:
        super().__init__()
        self.target = key
        self.queue = [first, second]

    def get(self, key, default=None):
        if key == self.target and self.queue:
            return self.queue.pop(0)
        return super().get(key, default)


class Clock:
    """A monotonic clock the test owns."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def led_settings(**overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "led": {
            "enabled": True,
            "priority": ["safety", "navigation"],
            "cooldown_s": 0.0,
            "brightness": 0.7,
            "default_color": "blue",
            "safety_color": "red",
            "safety_mode": "boom",
            "nav_mode": "breath",
            "idle_mode": "breath",
        },
        "navigation": {"led_patrol_color": "green"},
    }
    settings["led"].update(overrides)
    return settings


def build(settings: dict[str, Any], clock: Clock | None = None) -> tuple[LedManagerModule, DummyContext]:
    ctx = DummyContext()
    ctx.set("hal", FakeDogHAL())
    ctx.set("settings", settings)
    return LedManagerModule("led_manager", clock=clock or Clock()), ctx


def rgb_calls(ctx: DummyContext) -> list[dict[str, Any]]:
    return [params for name, params in ctx.get("hal").calls if name == "rgb"]


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
    calls = [params for name, params in hal.calls if name == "rgb"]
    assert calls, "LED manager should update the strip"
    assert calls[-1]["style"] == "boom"
    assert calls[-1]["color"] == "red"

def test_an_expired_high_priority_request_loses_to_a_live_one() -> None:
    clock = Clock()
    module, ctx = build(led_settings(), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency", "until_ts": clock() - 1.0})
    ctx.set("led_request:navigation", {"mode": "patrol"})

    module.tick(ctx)

    last = rgb_calls(ctx)[-1]
    assert (last["style"], last["color"]) == ("breath", "green")


def test_a_live_high_priority_request_still_wins() -> None:
    clock = Clock()
    module, ctx = build(led_settings(), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency", "until_ts": clock() + 0.9})
    ctx.set("led_request:navigation", {"mode": "patrol"})

    module.tick(ctx)

    last = rgb_calls(ctx)[-1]
    assert (last["style"], last["color"]) == ("boom", "red")


def test_a_request_without_a_deadline_stands() -> None:
    """The second half of L1's contract: nothing that shipped before P3 changes behaviour."""
    clock = Clock()
    module, ctx = build(led_settings(), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency"})

    module.tick(ctx)
    clock.advance(600.0)
    module.tick(ctx)

    assert ctx.get("led_request:safety") is not None
    assert rgb_calls(ctx)[-1]["style"] == "boom"


def test_an_expired_request_is_cleared_from_the_context() -> None:
    clock = Clock()
    module, ctx = build(led_settings(), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency", "until_ts": clock() - 1.0})

    module.tick(ctx)

    assert ctx.get("led_request:safety") is None
    assert rgb_calls(ctx) == [], "nothing is live, so nothing should be applied"


def test_a_refresh_during_the_clear_window_is_not_clobbered() -> None:
    """The producer refreshed between the read and the clear; the clear must stand down."""
    clock = Clock()
    module = LedManagerModule("led_manager", clock=clock)
    expired = {"mode": "emergency", "until_ts": clock() - 1.0}
    refreshed = {"mode": "emergency", "until_ts": clock() + 1.0}
    ctx = RacingContext("led_request:safety", expired, refreshed)

    assert module._select_request(ctx, ["safety"]) is None
    assert ctx.writes == []


def test_a_request_colour_and_rate_reach_the_hal() -> None:
    """`{mode, color, bps}` is the timed form §5.2 needs: amber, 3 bps, until the deadline."""
    clock = Clock()
    settings = led_settings(priority=["attention"], attention_color="cyan", attention_mode="listen")
    module, ctx = build(settings, clock=clock)
    ctx.set("led_request:attention", {"mode": "blink", "color": "amber", "bps": 3})

    module.tick(ctx)

    last = rgb_calls(ctx)[-1]
    assert last["color"] == "amber", "a request's own colour must win over the source's"
    assert last["bps"] == 3.0
    assert last["style"] == "listen"


def test_the_rate_falls_back_to_the_led_map() -> None:
    clock = Clock()
    module, ctx = build(led_settings(bps={"safety": 4}), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency"})

    module.tick(ctx)

    assert rgb_calls(ctx)[-1]["bps"] == 4.0


def test_no_rate_is_sent_when_nothing_supplies_one() -> None:
    """Absent means absent: the HAL's own default applies, as it did before the key existed."""
    clock = Clock()
    module, ctx = build(led_settings(), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency"})

    module.tick(ctx)

    assert "bps" not in rgb_calls(ctx)[-1]


def test_the_strip_returns_to_idle_once_after_the_request_expires() -> None:
    clock = Clock()
    module, ctx = build(led_settings(), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency", "until_ts": clock() + 0.9})
    module.tick(ctx)
    assert rgb_calls(ctx)[-1]["style"] == "boom"

    clock.advance(1.0)
    module.tick(ctx)
    idle = rgb_calls(ctx)[-1]
    assert (idle["style"], idle["color"]) == ("breath", "blue")

    clock.advance(1.0)
    module.tick(ctx)
    assert len(rgb_calls(ctx)) == 2, "the fallback is a transition, not a per-tick write"


def test_the_cooldown_still_dedupes_the_same_request() -> None:
    clock = Clock()
    module, ctx = build(led_settings(cooldown_s=5.0), clock=clock)
    ctx.set("led_request:safety", {"mode": "emergency"})

    module.tick(ctx)
    module.tick(ctx)

    assert len(rgb_calls(ctx)) == 1

