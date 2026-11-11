"""The gateway is where precedence and the interlock meet.

Both directions matter. A test suite that only checks "the safety action wins" would pass on a
gateway that never lets anything else through, and one that only checks "navigation moves the
dog" would pass on a gateway that ignores its input.
"""

from __future__ import annotations

from typing import Any

from houndmind_ai.act.gateway import MotionGatewayModule, canonical_action, legacy_action
from houndmind_ai.act.interlock import Interlock, InterlockLimits
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.sensors import SensorReading


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build(
    reading: SensorReading | None = None, **limits: Any
) -> tuple[MotionGatewayModule, RuntimeContext]:
    clock = Clock()
    interlock = Interlock(
        limits=InterlockLimits(**limits) if limits else None,
        now=clock,
    )
    gateway = MotionGatewayModule("motion_gateway", interlock=interlock, clock=clock)
    context = RuntimeContext()
    if reading is not None:
        context.set("sensor_reading", reading)
    return gateway, context


def reading(distance_cm: float | None, valid: bool = True) -> SensorReading:
    return SensorReading(
        distance_cm=distance_cm,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=(0.0, 0.0, 9.8),
        gyro=(0.0, 0.0, 0.0),
        timestamp=1000.0,
        distance_valid=valid,
        touch_valid=True,
        sound_valid=True,
        imu_valid=True,
    )


# ------------------------------------------------------------------ resolution


def test_no_producer_publishes_nothing() -> None:
    gateway, context = build()
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict") is None


def test_navigation_alone_wins() -> None:
    gateway, context = build()
    context.set("navigation_action", "forward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_safety_overrides_navigation() -> None:
    gateway, context = build()
    context.set("navigation_action", "forward")
    context.set("safety_action", "backward")
    gateway.tick(context)
    command = context.get("motion_command")
    assert command["action"] == "backward"
    assert command["source"] == "system"


def test_watchdog_overrides_navigation_but_not_safety() -> None:
    gateway, context = build()
    context.set("navigation_action", "forward")
    context.set("watchdog_action", "stop")
    gateway.tick(context)
    assert context.get("motion_command")["source"] == "watchdog"

    context.set("safety_action", "backward")
    gateway.tick(context)
    assert context.get("motion_command")["source"] == "system"


def test_behaviour_is_lowest_priority() -> None:
    gateway, context = build()
    context.set("behavior_action", "sit")
    context.set("navigation_action", "forward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_same_upstream_intent_is_not_reissued_every_tick() -> None:
    """Re-issuing would bypass the motor cooldown and flood the action queue."""
    gateway, context = build()
    context.set("navigation_action", "forward")
    gateway.tick(context)
    first = context.get("motion_command")
    gateway.tick(context)
    gateway.tick(context)
    assert context.get("motion_command") == first


def test_a_new_intent_is_issued() -> None:
    gateway, context = build()
    context.set("navigation_action", "forward")
    gateway.tick(context)
    first_id = context.get("motion_command")["id"]
    context.set("navigation_action", "turn left")
    gateway.tick(context)
    command = context.get("motion_command")
    assert command["id"] != first_id
    # pidog's spelling is what reaches the motors.
    assert command["action"] == "turn left"
    assert command["canonical_action"] == "turn_left"


def test_a_cleared_producer_publishes_none() -> None:
    """A producer that stops asking must stop the dog on the next tick."""
    gateway, context = build()
    context.set("navigation_action", "forward")
    gateway.tick(context)
    context.set("navigation_action", None)
    gateway.tick(context)
    assert context.get("motion_command") is None


# ------------------------------------------------------------------ the interlock


def test_obstacle_vetoes_forward_and_says_why() -> None:
    gateway, context = build(reading(8.0), emergency_stop_cm=12.0)
    context.set("navigation_action", "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None
    verdict = context.get("motion_verdict")
    assert verdict["accepted"] is False
    assert verdict["veto"] == "obstacle"
    assert "8.0 cm" in verdict["detail"]


def test_obstacle_blocks_forward_but_not_backward() -> None:
    gateway, context = build(reading(8.0), emergency_stop_cm=12.0)
    context.set("navigation_action", "backward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "backward"


def test_an_invalid_reading_does_not_veto() -> None:
    """A dead sensor must not pin the dog in place forever."""
    gateway, context = build(reading(3.0, valid=False), emergency_stop_cm=12.0)
    context.set("navigation_action", "forward")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_a_high_priority_command_is_still_vetoed_by_the_interlock() -> None:
    """Precedence decides who is heard; the interlock decides whether anyone moves."""
    gateway, context = build(reading(5.0), emergency_stop_cm=12.0)
    context.set("safety_action", "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict")["veto"] == "obstacle"


def test_stop_is_never_vetoed() -> None:
    gateway, context = build(reading(5.0), emergency_stop_cm=12.0)
    context.set("safety_action", "stop")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "stop"


def test_tilt_latches_motion_until_cleared() -> None:
    gateway, context = build()
    context.set("tilt_warning", {"pitch": 60.0, "roll": 0.0})
    context.set("navigation_action", "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("tilt_latched") is True

    # Righting the dog does not clear the latch; a human decides that.
    context.set("tilt_warning", {"pitch": 0.0, "roll": 0.0})
    gateway.tick(context)
    assert context.get("motion_command") is None

    gateway.interlock.clear_tilt()
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "forward"


def test_tilt_does_not_block_posture() -> None:
    gateway, context = build()
    context.set("tilt_warning", {"pitch": 60.0, "roll": 0.0})
    context.set("behavior_action", "sit")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "sit"


def test_low_voltage_blocks_motion_but_not_posture() -> None:
    gateway, context = build(min_battery_v=6.4)
    context.set("battery_voltage", 5.9)
    context.set("navigation_action", "forward")
    gateway.tick(context)
    assert context.get("motion_command") is None
    assert context.get("motion_verdict")["veto"] == "low_voltage"

    context.set("navigation_action", None)
    context.set("behavior_action", "sit")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "sit"


def test_unknown_posture_actions_are_not_refused() -> None:
    """The dog's repertoire is the HAL's business, not this module's.
    Refusing here would silently delete behaviours nobody listed in KNOWN_ACTIONS."""
    gateway, context = build()
    context.set("behavior_action", "high five")
    gateway.tick(context)
    assert context.get("motion_command")["action"] == "high five"


# ------------------------------------------------------------------ spelling


def test_legacy_and_canonical_spellings_round_trip() -> None:
    assert canonical_action("Turn Left") == "turn_left"
    assert canonical_action("forward") == "forward"
    assert legacy_action("turn_left") == "turn left"
    assert legacy_action("wag_tail") == "wag tail"