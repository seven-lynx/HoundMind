"""Validity beside value: a flag for every measurement in the fused snapshot.

`perception/fusion.py::_update_from_reading` publishes `distance_valid`, `touch_valid` and
`sound_valid` from the reading's own flags, plus `obstacle_valid`, which is the qualification the
`obstacle` bool never carried. The rule the platform is built on (`20-hardware.md`) is that a
failed read stays distinguishable from a real one: `distance_cm=100` with `distance_valid=False` is
not "clear at one metre", and a sonar that never answered is `obstacle: False,
obstacle_valid: False` -- unproven, never permission to keep driving.

Why a file of its own rather than a case in `test_perception_occupancy.py`: that file owns the
occupancy fact and the behavioural bias it feeds, and its `reading()` helper pins every flag to
`False`. These tests vary the flags themselves, which is the whole point of the segment.

The settings are the shipped ones with `obstacle_cm` pinned, so the threshold a case compares
against is written in the case rather than in `config/settings.jsonc`.
"""

from __future__ import annotations

from types import SimpleNamespace

from houndmind_ai.core.config import load_config
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.perception.fusion import PerceptionModule

# The shipped threshold, restated here so a change to `config/settings.jsonc` cannot silently
# re-point what these cases call "near" and "far".
OBSTACLE_CM = 20.0


class DummyContext:
    """The runtime context, minus the locking: these tests are single-threaded."""

    def __init__(self, settings: dict) -> None:
        self.data: dict = {"settings": settings}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def settings_for(obstacle_cm: float = OBSTACLE_CM) -> dict:
    """The shipped settings, with the obstacle threshold pinned by the test."""
    settings = dict(load_config().settings)
    section = dict(settings.get("perception", {}))
    section["obstacle_cm"] = obstacle_cm
    settings["perception"] = section
    return settings


def reading(
    distance_cm: float | None = 200.0,
    *,
    distance_valid: bool | None = None,
    touch: str = "N",
    touch_valid: bool = False,
    sound_detected: bool = False,
    sound_valid: bool = False,
    timestamp: float = 1_000.0,
) -> SensorReading:
    """One sensor poll, with every validity flag under the test's control.

    `distance_valid` defaults to "the HAL produced a range", which is what a sonar that answered
    sets. A case that wants the 100 cm-and-invalid reading says so explicitly rather than relying
    on that default.
    """
    return SensorReading(
        distance_cm=distance_cm,
        touch=touch,
        sound_detected=sound_detected,
        sound_direction=None,
        acc=(0.0, 0.0, 1.0),
        gyro=(0.0, 0.0, 0.0),
        timestamp=timestamp,
        distance_valid=distance_cm is not None if distance_valid is None else distance_valid,
        touch_valid=touch_valid,
        sound_valid=sound_valid,
        imu_valid=False,
    )


class Rig:
    """A perception module plus a context, on the shipped settings."""

    def __init__(self, obstacle_cm: float = OBSTACLE_CM) -> None:
        self.context = DummyContext(settings_for(obstacle_cm))
        self.module = PerceptionModule("perception", clock=lambda: 1_000.0)
        self.module.start(self.context)

    def poll(self, polled) -> dict:
        """One tick with `polled` as the sensor reading; the published snapshot comes back."""
        self.context.set("sensor_reading", polled)
        self.module.tick(self.context)
        return self.context.get("perception") or {}



# ------------------------------------------------------------- the sonar and the obstacle


def test_a_silent_sonar_is_unproven_not_clear() -> None:
    """The case the segment exists for: a range with a false flag proves nothing."""
    perception = Rig().poll(reading(100.0, distance_valid=False))
    assert perception["obstacle"] is False
    assert perception["obstacle_valid"] is False
    assert perception["distance"] == 100.0, "the value is carried, not zeroed"
    assert perception["distance_valid"] is False


def test_no_range_at_all_is_unproven_too() -> None:
    """A sonar that never answered is the same shape, not a different one."""
    perception = Rig().poll(reading(None))
    assert perception["obstacle"] is False
    assert perception["obstacle_valid"] is False
    assert perception["distance"] is None
    assert perception["distance_valid"] is False


def test_a_valid_range_beyond_the_threshold_proves_the_way() -> None:
    perception = Rig().poll(reading(200.0))
    assert perception["obstacle"] is False
    assert perception["obstacle_valid"] is True, "a validated range is the proof a consumer needs"


def test_a_valid_range_under_the_threshold_is_an_obstacle() -> None:
    perception = Rig().poll(reading(OBSTACLE_CM / 2))
    assert perception["obstacle"] is True
    assert perception["obstacle_valid"] is True


def test_an_unproven_range_is_reported_but_not_believed() -> None:
    """`obstacle` is not recomputed from the flag; the flag is what says it proved nothing."""
    perception = Rig().poll(reading(OBSTACLE_CM / 2, distance_valid=False))
    assert perception["obstacle"] is True
    assert perception["obstacle_valid"] is False


def test_the_obstacle_stays_a_bool() -> None:
    """Additive inside v1: a client that reads the bool keeps a bool, it just learns the flag."""
    for polled in (reading(5.0), reading(200.0), reading(None), reading(5.0, distance_valid=False)):
        assert isinstance(Rig().poll(polled)["obstacle"], bool)


def test_the_threshold_moves_with_the_config() -> None:
    """`obstacle_cm` is the setting, not a constant: a 15 cm dog and a 30 cm dog disagree."""
    perception = Rig(obstacle_cm=15.0).poll(reading(25.0))
    assert perception["obstacle"] is False
    assert perception["obstacle_valid"] is True


# ------------------------------------------------------------------- touch and sound


def test_touch_carries_its_own_flag() -> None:
    """A pad that answered and a pad that did not look the same in `touch`, so the flag says."""
    proven = Rig().poll(reading(touch="P", touch_valid=True))
    assert (proven["touch"], proven["touch_valid"]) == ("P", True)
    unproven = Rig().poll(reading(touch="P", touch_valid=False))
    assert (unproven["touch"], unproven["touch_valid"]) == ("P", False)


def test_sound_carries_its_own_flag() -> None:
    """`sound: False` is a clap nobody heard only when `sound_valid` is true."""
    proven = Rig().poll(reading(sound_detected=True, sound_valid=True))
    assert (proven["sound"], proven["sound_valid"]) == (True, True)
    quiet = Rig().poll(reading(sound_detected=False, sound_valid=True))
    assert (quiet["sound"], quiet["sound_valid"]) == (False, True)
    unproven = Rig().poll(reading(sound_detected=True, sound_valid=False))
    assert (unproven["sound"], unproven["sound_valid"]) == (True, False)


def test_a_reading_without_flags_is_unproven_everywhere() -> None:
    """The producer reads every flag with `getattr(..., False)`: a bare reading is not trusted."""
    bare = SimpleNamespace(distance_cm=OBSTACLE_CM / 2, touch="P", sound_detected=True)
    perception = Rig().poll(bare)
    assert perception["obstacle_valid"] is False
    assert perception["distance_valid"] is False
    assert perception["touch_valid"] is False
    assert perception["sound_valid"] is False


def test_the_new_flags_cost_none_of_the_keys_already_there() -> None:
    """One snapshot, one writer: the flags ride beside the values, they do not replace them."""
    perception = Rig().poll(reading(200.0, touch="N", touch_valid=True, sound_valid=True))
    for key in (
        "obstacle",
        "obstacle_valid",
        "distance",
        "distance_valid",
        "touch",
        "touch_valid",
        "sound",
        "sound_valid",
        "sound_direction",
        "occupancy",
        "occupancy_valid",
        "occupancy_frames",
    ):
        assert key in perception, key
