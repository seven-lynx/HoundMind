"""The interlock is the only thing standing between a command and a servo.

Every case here is hardware-free and instant: the fake HAL supplies the snapshot and the
clock is injected, so nothing sleeps and nothing moves.
"""

from __future__ import annotations

import pytest

from houndmind_ai.act.interlock import Interlock, InterlockLimits
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.kernel.actions import build_repertoire
from houndmind_ai.kernel.commands import Command, Source


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


def make(
    limits: InterlockLimits | None = None, repertoire: dict | None = None
) -> tuple[Interlock, Clock, FakeDogHAL]:
    clock = Clock()
    dog = FakeDogHAL(now=clock)
    loaded = build_repertoire(repertoire) if repertoire is not None else None
    return Interlock(limits or InterlockLimits(), now=clock, repertoire=loaded), clock, dog


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


def test_trot_is_refused_at_the_emergency_distance() -> None:
    """A trot is a forward gait: the sonar gate covers it exactly as it covers `forward`."""
    interlock, clock, dog = make()
    dog.set_distance(8.0)
    verdict = interlock.evaluate(Command("trot", issued_at=clock()), dog.read())
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


def test_low_voltage_blocks_motion_and_posture_but_not_non_motion() -> None:
    """The battery floor outranks everything that moves the dog, a sit included.

    A pack that cannot hold a gait should not be asked to hold a posture either. What it must still
    do is let the dog say so: `rgb`, `sound`, `speak` and `head` are `non_motion`, so a flat battery
    cannot stop it whining about the flat battery.
    """
    interlock, clock, dog = make()
    dog.set_distance(100.0)
    dog.set_battery(5.9)
    refused = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert refused.accepted is False
    assert refused.veto == "low_voltage"

    posture = interlock.evaluate(Command("lie", issued_at=clock()), dog.read())
    assert posture.accepted is False
    assert posture.veto == "low_voltage"

    for action in ("rgb", "sound", "speak", "head", "stop"):
        verdict = interlock.evaluate(Command(action, issued_at=clock()), dog.read())
        assert verdict.accepted is True, action


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
def test_postures_are_not_gated_by_distance(action: str) -> None:
    """A sit with a wall 2 cm away is still a sit. Only the forward family answers to the sonar."""
    interlock, clock, dog = make()
    dog.set_distance(2.0)
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


# ------------------------------------------------------------------ the classes
# One case per class. The class, not the name, decides which limits apply
# (`kernel/actions.py`); these are the four answers it can give.


def test_a_classified_catalog_action_is_admitted() -> None:
    """A catalog gesture stops being `unknown_action` once the classification says what it is."""
    interlock, clock, dog = make(repertoire={"high five": {"class": "posture"}})
    verdict = interlock.evaluate(Command("high five", issued_at=clock()), dog.read())
    assert verdict.accepted is True


def test_an_unclassified_name_is_refused_with_a_reason() -> None:
    """The catalog is the vocabulary: a spelling nothing classifies must not reach a servo."""
    interlock, clock, dog = make(repertoire={"high five": {"class": "posture"}})
    verdict = interlock.evaluate(Command("moonwalk", issued_at=clock()), dog.read())
    assert verdict.accepted is False
    assert verdict.veto == "unknown_action"


def test_expression_is_not_gated_by_sonar_but_is_by_battery_and_tilt() -> None:
    """A bark needing clear sonar in front of it would not be a bark."""
    interlock, clock, dog = make()
    dog.set_distance(2.0)
    assert interlock.evaluate(Command("bark", issued_at=clock()), dog.read()).accepted is True

    dog.set_battery(5.0)
    battery = interlock.evaluate(Command("bark", issued_at=clock()), dog.read())
    assert battery.accepted is False
    assert battery.veto == "low_voltage"

    dog.set_battery(7.4)
    dog.set_imu(70.0, 0.0)
    tilted = interlock.evaluate(Command("bark", issued_at=clock()), dog.read())
    assert tilted.accepted is False
    assert tilted.veto == "tilt"


def test_tilt_latches_from_a_posture_command_too() -> None:
    """The latch is a property of the dog, not of the action that happened to notice the tilt."""
    interlock, clock, dog = make()
    dog.set_imu(60.0, 0.0)
    verdict = interlock.evaluate(Command("sit", issued_at=clock()), dog.read())
    assert verdict.veto == "tilt"
    assert interlock.tilt_latched is True


@pytest.mark.parametrize("action", ["backward", "turn_left", "turn_right"])
def test_retreat_and_turns_stay_available_at_the_emergency_distance(action: str) -> None:
    """Only the forward family answers to the sonar; the way out of a corner is not blocked."""
    interlock, clock, dog = make()
    dog.set_distance(8.0)
    assert interlock.evaluate(Command(action, issued_at=clock()), dog.read()).accepted is True


def test_non_motion_still_spends_its_deadman() -> None:
    """A stale LED request is as wrong as a stale gait."""
    interlock, clock, dog = make()
    command = Command("rgb", issued_at=clock(), ttl_ms=300)
    clock.t = 1000.4
    verdict = interlock.evaluate(command, dog.read())
    assert verdict.accepted is False
    assert verdict.veto == "expired"


def test_non_motion_is_never_vetoed_by_a_sensor() -> None:
    """Distance, tilt and voltage are all hostile here; none may block a non-motion action."""
    interlock, clock, dog = make()
    dog.set_distance(1.0)
    dog.set_imu(89.0, 89.0)
    dog.set_battery(3.0)
    for action in ("rgb", "sound", "speak", "head", "rpy"):
        verdict = interlock.evaluate(Command(action, issued_at=clock()), dog.read())
        assert verdict.accepted is True, action


def test_the_locomotion_floor_survives_a_config_that_tries_to_weaken_it() -> None:
    """A class map is not a way to switch the obstacle stop off."""
    interlock, clock, dog = make(repertoire={"forward": {"class": "non_motion"}})
    dog.set_distance(5.0)
    verdict = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert verdict.accepted is False
    assert verdict.veto == "obstacle"
