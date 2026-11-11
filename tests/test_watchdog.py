"""The watchdog: hold motion on stale data, and never pose the dog.

H-03's headline was "it lies the dog down every five seconds". These tests pin the replacement:
a stale reading produces a `stop` intent (which the gateway judges like any other), and a
*candidate list of enabled, started modules only* — so the shipped config, where four safety
modules are off, is silent.
"""

from __future__ import annotations

import time

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.intents import IntentBoard
from houndmind_ai.navigation.scanning import ScanReading
from houndmind_ai.safety.watchdog import WatchdogModule


SETTINGS = {
    "watchdog": {
        "enabled": True,
        "sensor_timeout_s": 2.0,
        "scan_timeout_s": 2.0,
        "module_timeout_s": 4.0,
        "monitor_modules": [],
        "ignore_modules": [],
        "restart_cooldown_s": 1.0,
        "restart_backoff_factor": 2.0,
        "restart_max_delay_s": 60.0,
        "max_restarts": 3,
        "healthy_after_s": 30.0,
    }
}


def reading(ts: float | None = None) -> SensorReading:
    return SensorReading(
        distance_cm=100.0,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=(0.0, 0.0, 9.8),
        gyro=(0.0, 0.0, 0.0),
        timestamp=time.time() if ts is None else ts,
        distance_valid=True,
        touch_valid=True,
        sound_valid=True,
        imu_valid=True,
    )


def scan(ts: float | None = None) -> ScanReading:
    return ScanReading(mode="sweep", data={0: 100.0}, timestamp=time.time() if ts is None else ts)


def build(settings: dict | None = None, now: float | None = None):
    context = RuntimeContext()
    board = IntentBoard()
    module = WatchdogModule("watchdog")
    module.start(context)
    context.set("settings", settings or SETTINGS)
    context.set("intent_board", board)
    context.set("module_statuses", {})
    return module, context, board


def status(**overrides):
    base = {
        "enabled": True,
        "required": False,
        "started": True,
        "disabled_reason": None,
        "last_heartbeat_ts": time.time(),
        "last_error": None,
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ data staleness


def test_a_healthy_dog_with_nothing_asked_is_left_alone() -> None:
    """The H-03 regression: a shipped config must not produce a recovery every few seconds."""
    module, context, board = build()
    context.set("sensor_reading", reading())
    context.set("scan_reading", scan())
    module.tick(context)
    assert board.latest() == []
    assert context.get("watchdog_hold") is None


def test_a_stale_sensor_holds_a_dog_that_is_trying_to_move() -> None:
    module, context, board = build()
    context.set("sensor_reading", reading(ts=time.time() - 60.0))
    context.set("scan_reading", scan())
    board.publish("forward", Source.NAVIGATION)

    module.tick(context)

    assert board.find(Source.WATCHDOG).action == "stop"
    assert context.get("watchdog_hold")["reason"] == "sensor stale"


def test_a_stale_sensor_does_not_disturb_a_dog_that_is_already_still() -> None:
    module, context, board = build()
    context.set("sensor_reading", reading(ts=time.time() - 60.0))
    context.set("scan_reading", scan())

    module.tick(context)

    assert board.latest() == [], "nothing was moving, so nothing should be stopped"


def test_the_hold_is_released_when_the_data_is_fresh_again() -> None:
    module, context, board = build()
    context.set("sensor_reading", reading(ts=time.time() - 60.0))
    context.set("scan_reading", scan())
    board.publish("forward", Source.NAVIGATION)
    module.tick(context)
    assert board.find(Source.WATCHDOG) is not None

    context.set("sensor_reading", reading())
    module.tick(context)

    assert board.find(Source.WATCHDOG) is None
    assert context.get("watchdog_hold") is None


def test_a_slow_scan_is_not_called_stale() -> None:
    """A sweep takes ~2.6 s at the shipped settings; a 0.8 s window called it stale forever."""
    module, context, board = build()
    context.set("scan_duration_s", 2.6)
    context.set("sensor_reading", reading())
    context.set("scan_reading", scan(ts=time.time() - 3.0))
    board.publish("forward", Source.NAVIGATION)

    module.tick(context)

    assert board.find(Source.WATCHDOG) is None, "3 s old for a 2.6 s scan is fresh"


def test_a_scan_older_than_its_own_duration_is_stale() -> None:
    module, context, board = build()
    context.set("scan_duration_s", 2.6)
    context.set("sensor_reading", reading())
    context.set("scan_reading", scan(ts=time.time() - 10.0))
    board.publish("forward", Source.NAVIGATION)

    module.tick(context)

    assert board.find(Source.WATCHDOG).action == "stop"


def test_the_hold_does_not_flap_while_a_tick_is_slow() -> None:
    """A producer's intent can expire mid-tick; the hold must outlast it."""
    module, context, board = build()
    context.set("sensor_reading", reading(ts=time.time() - 60.0))
    context.set("scan_reading", scan())
    board.publish("forward", Source.NAVIGATION)
    module.tick(context)
    assert board.find(Source.WATCHDOG).action == "stop"

    # The producer's intent is gone (a slow tick let it expire), the data is still bad.
    board.retract(Source.NAVIGATION)
    module.tick(context)

    assert board.find(Source.WATCHDOG).action == "stop", "the hold must not be released by silence"


def test_the_watchdog_never_asks_for_a_pose() -> None:
    """The old recovery default was `lie`. A fault must never move the dog."""
    module, context, board = build()
    context.set("sensor_reading", reading(ts=time.time() - 60.0))
    context.set("scan_reading", scan())
    board.publish("forward", Source.NAVIGATION)

    module.tick(context)

    requested = {command.action for command in board.latest()}
    assert requested <= {"forward", "stop"}, requested


# ------------------------------------------------------------------ module liveness


def test_a_disabled_module_is_not_reported_as_stale() -> None:
    """`module_names` lists every module; only started ones heartbeat. That was H-03."""
    module, context, board = build()
    context.set("sensor_reading", reading())
    context.set("scan_reading", scan())
    context.set(
        "module_statuses",
        {
            "safety": status(enabled=False, started=False, last_heartbeat_ts=None),
            "health": status(enabled=False, started=False, last_heartbeat_ts=None),
        },
    )

    module.tick(context)

    assert context.get("restart_modules") is None
    assert context.get("watchdog_status")["restart"] == []


def test_a_module_that_stopped_ticking_is_restarted() -> None:
    module, context, board = build()
    context.set("sensor_reading", reading())
    context.set("scan_reading", scan())
    context.set(
        "module_statuses",
        {"scanning": status(last_heartbeat_ts=time.time() - 60.0)},
    )

    module.tick(context)

    assert context.get("restart_modules") == ["scanning"]


def test_the_watchdog_never_restarts_itself() -> None:
    module, context, board = build()
    context.set("sensor_reading", reading())
    context.set("scan_reading", scan())
    context.set(
        "module_statuses",
        {"watchdog": status(last_heartbeat_ts=time.time() - 60.0)},
    )

    module.tick(context)

    assert context.get("restart_modules") is None


def test_a_disabled_watchdog_does_nothing() -> None:
    settings = {"watchdog": {**SETTINGS["watchdog"], "enabled": False}}
    module, context, board = build(settings)
    context.set("sensor_reading", reading(ts=time.time() - 60.0))
    context.set("scan_reading", scan())
    board.publish("forward", Source.NAVIGATION)

    module.tick(context)

    assert board.find(Source.WATCHDOG) is None