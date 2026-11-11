"""The interlock is the only thing standing between a command and a servo.

Every case here is hardware-free and instant: the fake HAL supplies the snapshot and the
clock is injected, so nothing sleeps and nothing moves.
"""

from __future__ import annotations

import pytest

from houndmind_ai.act.interlock import Interlock, InterlockLimits
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.kernel.commands import Command, Source


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


def make(limits: InterlockLimits | None = None) -> tuple[Interlock, Clock, FakeDogHAL]:
    clock = Clock()
    dog = FakeDogHAL(now=clock)
    return Interlock(limits or InterlockLimits(), now=clock), clock, dog


def test_stop_is_never_vetoed() -> None:
    interlock, clock, dog = make()
    dog.set_distance(1.0)
    dog.set_imu(89.0, 89.0)
    dog.set_battery(3.0)
    verdict = interlock.evaluate(Command("stop", issued_at=clock()), dog.read())
    assert verdict.accepted is True
    assert verdict.veto is None


def test_expired_command_is_refused_with_a_reason() -> None:
    interlock, clock, dog = make()
    dog.set_distance(200.0)
    command = Command("forward", issued_at=clock(), ttl_ms=300)
    clock.t = 1000.4
    verdict = interlock.evaluate(command, dog.read())
    assert verdict.accepted is False
    assert verdict.veto == "expired"
    assert verdict.detail


def test_unknown_action_is_refused() -> None:
    interlock, clock, dog = make()
    verdict = interlock.evaluate(Command("moonwalk", issued_at=clock()), dog.read())
    assert verdict.accepted is False
    assert verdict.veto == "unknown_action"
    assert "moonwalk" in (verdict.detail or "")


def test_forward_is_refused_at_the_emergency_distance() -> None:
    interlock, clock, dog = make()
    dog.set_distance(8.0)
    verdict = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert verdict.accepted is False
    assert verdict.veto == "obstacle"


def test_backward_is_allowed_at_the_emergency_distance() -> None:
    """Retreat must stay available when something is in front of the dog."""
    interlock, clock, dog = make()
    dog.set_distance(8.0)
    verdict = interlock.evaluate(Command("backward", issued_at=clock()), dog.read())
    assert verdict.accepted is True


def test_invalid_distance_never_vetoes() -> None:
    """A dead sensor must not pin the dog in place, and must not authorise a blind run."""
    interlock, clock, dog = make()
    dog.set_distance(None)
    verdict = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert verdict.accepted is True


def test_forward_is_allowed_past_the_emergency_distance() -> None:
    interlock, clock, dog = make()
    dog.set_distance(40.0)
    assert interlock.evaluate(Command("forward", issued_at=clock()), dog.read()).accepted


def test_tilt_latches_and_blocks_motion_until_cleared() -> None:
    interlock, clock, dog = make()
    dog.set_distance(100.0)
    dog.set_imu(60.0, 0.0)

    first = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert first.accepted is False
    assert first.veto == "tilt"
    assert interlock.tilt_latched is True

    # The dog is upright again but nobody cleared the latch: motion is still refused.
    dog.set_imu(0.0, 0.0)
    again = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert again.accepted is False
    assert again.veto == "tilt"

    interlock.clear_tilt()
    cleared = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert cleared.accepted is True
    assert interlock.tilt_latched is False


def test_invalid_imu_neither_latches_nor_clears() -> None:
    interlock, clock, dog = make()
    dog.set_distance(100.0)
    dog.set_imu(None, None)
    assert interlock.evaluate(Command("forward", issued_at=clock()), dog.read()).accepted
    assert interlock.tilt_latched is False


def test_low_voltage_blocks_motion_but_not_posture() -> None:
    interlock, clock, dog = make()
    dog.set_distance(100.0)
    dog.set_battery(5.9)
    refused = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert refused.accepted is False
    assert refused.veto == "low_voltage"

    allowed = interlock.evaluate(Command("lie", issued_at=clock()), dog.read())
    assert allowed.accepted is True


def test_speed_is_clamped_to_the_board_limit() -> None:
    interlock, clock, dog = make(InterlockLimits(max_speed=150))
    dog.set_distance(100.0)
    verdict = interlock.evaluate(
        Command("forward", params={"speed": 255}, issued_at=clock()), dog.read()
    )
    assert verdict.accepted is True
    assert verdict.params["speed"] == 150
    assert verdict.detail is not None


def test_clamp_is_reported_once_per_session() -> None:
    interlock, clock, dog = make(InterlockLimits(max_speed=150))
    dog.set_distance(100.0)
    first = interlock.evaluate(
        Command("forward", params={"speed": 255}, issued_at=clock()), dog.read()
    )
    second = interlock.evaluate(
        Command("forward", params={"speed": 255}, issued_at=clock()), dog.read()
    )
    assert first.detail is not None
    assert second.detail is None
    assert second.params["speed"] == 150


def test_speed_within_limit_is_untouched() -> None:
    interlock, clock, dog = make()
    dog.set_distance(100.0)
    verdict = interlock.evaluate(
        Command("forward", params={"speed": 90}, issued_at=clock()), dog.read()
    )
    assert verdict.params["speed"] == 90
    assert verdict.detail is None


def test_junk_speed_falls_back_to_the_limit() -> None:
    interlock, clock, dog = make(InterlockLimits(max_speed=120))
    dog.set_distance(100.0)
    verdict = interlock.evaluate(
        Command("forward", params={"speed": "fast"}, issued_at=clock()), dog.read()
    )
    assert verdict.accepted is True
    assert verdict.params["speed"] == 120


@pytest.mark.parametrize("action", ["lie", "sit", "stand", "stretch", "wag_tail"])
def test_postures_are_not_gated_by_distance_or_voltage(action: str) -> None:
    interlock, clock, dog = make()
    dog.set_distance(2.0)
    dog.set_battery(5.0)
    verdict = interlock.evaluate(Command(action, issued_at=clock()), dog.read())
    assert verdict.accepted is True


def test_veto_beats_source_priority() -> None:
    """A system-priority command is still refused by physics."""
    interlock, clock, dog = make()
    dog.set_distance(1.0)
    verdict = interlock.evaluate(
        Command("forward", source=Source.SYSTEM, issued_at=clock()), dog.read()
    )
    assert verdict.accepted is False
    assert verdict.veto == "obstacle"