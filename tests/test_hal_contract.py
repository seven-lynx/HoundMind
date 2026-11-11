"""The fake HAL must obey the same contract as the real one."""

from __future__ import annotations

import dataclasses

import pytest

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import DOG_ACTIONS, DogHAL, SensorSnapshot, as_float, as_int


def test_fake_satisfies_the_protocol() -> None:
    assert isinstance(FakeDogHAL(), DogHAL)


def test_snapshot_is_immutable() -> None:
    snapshot = SensorSnapshot(ts=1.0, distance_cm=10.0, distance_valid=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.distance_cm = 99.0  # type: ignore[misc]


def test_missing_distance_is_invalid_not_far() -> None:
    """The rule this platform must never break: no value without a validity flag."""
    dog = FakeDogHAL()
    dog.set_distance(None)
    reading = dog.read()
    assert reading.distance_valid is False
    assert reading.distance_cm is None


def test_distance_becomes_valid_when_set() -> None:
    dog = FakeDogHAL()
    dog.set_distance(42.5)
    reading = dog.read()
    assert reading.distance_valid is True
    assert reading.distance_cm == 42.5


def test_imu_validity_follows_both_axes() -> None:
    dog = FakeDogHAL()
    dog.set_imu(1.0, None)
    assert dog.read().imu_valid is False
    dog.set_imu(1.0, -2.0)
    reading = dog.read()
    assert reading.imu_valid is True
    assert reading.tilted is True


def test_snapshot_timestamp_uses_injected_clock() -> None:
    dog = FakeDogHAL(now=lambda: 1234.5)
    assert dog.read().ts == 1234.5


def test_actions_are_recorded_in_order() -> None:
    dog = FakeDogHAL()
    dog.action("forward", {"speed": 100})
    dog.stop()
    assert dog.calls == [("forward", {"speed": 100}), ("stop", {})]
    assert dog.stop_count == 1


def test_recorded_params_are_copied() -> None:
    """A caller mutating its dict afterwards must not rewrite history."""
    dog = FakeDogHAL()
    params = {"speed": 100}
    dog.action("forward", params)
    params["speed"] = 255
    assert dog.calls[0][1]["speed"] == 100


def test_close_is_idempotent() -> None:
    dog = FakeDogHAL()
    dog.close()
    dog.close()
    assert dog.closed is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 1.0), ("", 1.0), ("nope", 1.0), ("2.5", 2.5), (3, 3.0), (float("nan"), 1.0)],
)
def test_as_float_treats_nan_and_junk_as_missing(value: object, expected: float) -> None:
    assert as_float(value, 1.0) == expected


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 7), ("", 7), ("x", 7), ("4", 4), (4.9, 4)]
)
def test_as_int_coerces_with_default(value: object, expected: int) -> None:
    assert as_int(value, 7) == expected


def test_audio_is_recorded_not_played() -> None:
    """A test asserts the *choice* of effect, never wall-clock timing."""
    dog = FakeDogHAL()
    dog.sound("confused_2", 80)
    dog.speak("good morning", 70)
    assert dog.sounds == [("confused_2", 80)]
    assert dog.speeches == [("good morning", 70)]


def test_the_hal_advertises_the_audio_actions() -> None:
    """`/repertoire` is built from `actions()`, so a new primitive has to appear there."""
    expected = {"sound", "speak"}
    assert expected <= DOG_ACTIONS
    assert expected <= FakeDogHAL().actions()


def test_rgb_keeps_the_animation_rate() -> None:
    """RP-3: `bps` used to be dropped, so no caller could set an effect's rate."""
    dog = FakeDogHAL()
    params = {"style": "breath", "color": "green", "brightness": 0.8, "bps": 2.0}
    dog.action("rgb", params)
    assert dog.calls[-1] == ("rgb", params)
