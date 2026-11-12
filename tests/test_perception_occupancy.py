"""Occupancy: whether someone is in front of the dog, and what the FSM does with it.

Two halves, and they fail differently on purpose.

- **The fact** (`perception/fusion.py`). A dropped frame, an absent detector and a stale payload
  all read as *unknown* - never as an empty room. Claiming somebody is there needs consecutive
  frames; dropping the claim needs a release window, so a blink does not flap the drive. An empty
  frame from an unknown start is believed at once, because nobody-has-appeared is not a claim.
- **The bias** (`behavior/fsm.py`). Presence raises the `interact` weight in the autonomy draw
  beside `personality.sociability`, decays when the sight is lost, and is *inert* when the reading
  is not valid. A camera that did not answer must leave the weight table exactly as it was.

The settings used here are the shipped defaults unless a test says otherwise, so a change to
`config/settings.jsonc` that silently retunes the segment breaks a test.
"""

from __future__ import annotations

import random

import pytest

from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.behavior.registry import BehaviorRegistry
from houndmind_ai.core.config import load_config
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.perception.fusion import (
    DEFAULT_OCCUPANCY_MIN_FRAMES,
    PerceptionModule,
    _safe_float,
)


class DummyContext:
    """The runtime context, minus the locking: these tests are single-threaded."""

    def __init__(self, settings: dict) -> None:
        self.data: dict = {"settings": settings}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def reading(distance_cm: float | None = 200.0, timestamp: float = 1_000.0) -> SensorReading:
    """One sensor poll. `perception` is only published when one of these exists today."""
    return SensorReading(
        distance_cm=distance_cm,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=(0.0, 0.0, 1.0),
        gyro=(0.0, 0.0, 0.0),
        timestamp=timestamp,
        distance_valid=distance_cm is not None,
        touch_valid=False,
        sound_valid=False,
        imu_valid=False,
    )


def settings_for(**occupancy) -> dict:
    """The shipped settings with the occupancy knobs overridable per test."""
    settings = dict(load_config().settings)
    section = dict(settings.get("perception", {}))
    section["occupancy"] = {**section.get("occupancy", {}), **occupancy}
    settings["perception"] = section
    return settings


class Detector:
    """A perception module plus a context, on a clock the test owns.

    The clock is injected rather than slept through: `faces` staleness is a comparison against
    "now", and a test that waits a second for it is a test that flakes.
    """

    def __init__(self, now: float = 1_000.0, **occupancy) -> None:
        self.now = now
        self.stamp_seq = 0
        self.context = DummyContext(settings_for(**occupancy))
        self.module = PerceptionModule("perception", clock=lambda: self.now)
        self.module.start(self.context)
        self.frames = 0

    def poll(self, faces: dict | None = None) -> dict:
        """One tick with a sensor reading, and whatever the detector has published."""
        self.frames += 1
        self.context.set("sensor_reading", reading(timestamp=self.now))
        if faces is not None:
            self.context.set("faces", faces)
        self.module.tick(self.context)
        return self.context.get("perception") or {}

    def frame(self, *, people: int = 1, age_s: float = 0.0) -> dict:
        """A frame from the detector: `people` faces, `age_s` seconds old, unique each call."""
        self.stamp_seq += 1
        stamp = self.now - age_s + self.stamp_seq / 1000.0
        return {"timestamp": stamp, "backend": "opencv", "detected": [{}] * people}

    def nobody(self, *, age_s: float = 0.0) -> dict:
        """A fresh frame with nobody in it: genuinely empty, not a dropped frame."""
        return self.frame(people=0, age_s=age_s)



# ------------------------------------------------------------------- the fact


def test_no_detector_is_unknown_not_empty() -> None:
    """A dog with presence disabled is blind to people, not alone in the room."""
    perception = Detector().poll()
    assert perception["occupancy"] is None
    assert perception["occupancy_valid"] is False


def test_a_stale_frame_is_unknown() -> None:
    """The camera stopped answering: that is not a reading of an empty room."""
    rig = Detector()
    perception = rig.poll(rig.nobody(age_s=900.0))
    assert perception["occupancy"] is None
    assert perception["occupancy_valid"] is False


def test_an_empty_frame_from_unknown_is_believed_at_once() -> None:
    """Nobody-has-appeared needs no evidence; somebody-is-here does."""
    rig = Detector()
    perception = rig.poll(rig.nobody())
    assert perception["occupancy"] is False
    assert perception["occupancy_valid"] is True
    assert perception["occupancy_frames"] == 1


def test_presence_needs_consecutive_frames() -> None:
    rig = Detector(min_frames=DEFAULT_OCCUPANCY_MIN_FRAMES)
    for _ in range(DEFAULT_OCCUPANCY_MIN_FRAMES - 1):
        perception = rig.poll(rig.frame())
        assert perception["occupancy"] is None, "one flicker is not a person"
        assert perception["occupancy_valid"] is True, "the reading is still valid"
    perception = rig.poll(rig.frame())
    assert perception["occupancy"] is True
    assert perception["occupancy_frames"] == DEFAULT_OCCUPANCY_MIN_FRAMES


def test_a_repeated_frame_is_not_counted_twice() -> None:
    """`faces` is republished unchanged between frames; counting it again would fake hysteresis."""
    rig = Detector(min_frames=3)
    frame = rig.frame()
    rig.poll(frame)
    perception = rig.poll(frame)
    assert perception["occupancy"] is None
    assert perception["occupancy_frames"] == 1


def test_losing_sight_releases_after_the_window() -> None:
    rig = Detector(min_frames=2, release_frames=3)
    rig.poll(rig.frame())
    assert rig.poll(rig.frame())["occupancy"] is True
    for _ in range(2):
        assert rig.poll(rig.nobody())["occupancy"] is True, "a blink must not drop the claim"
    assert rig.poll(rig.nobody())["occupancy"] is False


def test_the_fused_keys_survive_the_merge() -> None:
    """Occupancy rides the perception dict; it must not cost the keys already in it."""
    perception = Detector().poll(Detector().nobody())
    assert perception["distance"] == 200.0
    assert perception["obstacle"] is False
    assert perception["touch"] == "N"
    assert perception["sound"] is False


def test_a_nan_is_a_missing_number() -> None:
    """A NaN is not a reading (`10-python.md`: `None`, `""` and NaN are all missing)."""
    assert _safe_float(float("nan"), 20.0) == 20.0
    assert _safe_float("nonsense", 20.0) == 20.0
    assert _safe_float(12.5, 20.0) == 12.5


# ------------------------------------------------------------------- the bias


MODES = ("idle", "patrol", "explore", "interact", "play", "rest")


def behavior_settings(**overrides) -> dict:
    """The shipped behaviour section with an even weight table and no interval gate."""
    settings = dict(load_config().settings["behavior"])
    settings["autonomy_modes"] = list(MODES)
    settings["autonomy_weights"] = {mode: 1.0 for mode in MODES}
    settings["autonomy_interval_s"] = 0.0
    settings.update(overrides)
    return settings


def behavior_module() -> BehaviorModule:
    """The FSM with a registry that answers like the runtime's (`<mode>_behavior`, #82)."""
    module = BehaviorModule("behavior")
    registry = BehaviorRegistry()
    for mode in MODES:
        registry.register(f"{mode}_behavior", lambda mode=mode: mode)
    module.registry = registry
    return module


def context_for() -> DummyContext:
    """Personality off, so a test that sees a weight move knows occupancy moved it."""
    return DummyContext({"personality": {"apply_to_autonomy": False}})


def test_the_social_factor_is_inert_without_a_reading() -> None:
    """No detector, an unknown answer and a confident *empty* room all leave the draw alone."""
    settings = behavior_settings()
    for perception in (
        {},
        {"occupancy": None, "occupancy_valid": False},
        {"occupancy": False, "occupancy_valid": True},
    ):
        module = behavior_module()
        module._update_social_level(perception, settings, now=100.0)
        assert module._interact_social_factor(settings) == 1.0


def test_presence_raises_the_factor_to_the_peak() -> None:
    settings = behavior_settings()
    module = behavior_module()
    module._update_social_level({"occupancy": True, "occupancy_valid": True}, settings, now=100.0)
    assert module._interact_social_factor(settings) == pytest.approx(settings["social_bias_peak"])


def test_the_bias_can_be_switched_off() -> None:
    settings = behavior_settings(social_bias_enabled=False)
    module = behavior_module()
    module._update_social_level({"occupancy": True, "occupancy_valid": True}, settings, now=100.0)
    assert module._interact_social_factor(settings) == 1.0


def test_the_level_decays_when_the_sight_is_lost() -> None:
    """A dog that just lost sight of you stays interested for a moment, then stops."""
    settings = behavior_settings()
    module = behavior_module()
    module._update_social_level({"occupancy": True, "occupancy_valid": True}, settings, now=100.0)
    half = 100.0 + float(settings["social_decay_s"]) / 2.0
    module._update_social_level({"occupancy": None, "occupancy_valid": False}, settings, now=half)
    assert module._social_level == pytest.approx(0.5, abs=0.02)
    gone = 100.0 + float(settings["social_decay_s"]) + 1.0
    module._update_social_level({"occupancy": None, "occupancy_valid": False}, settings, now=gone)
    assert module._social_level == 0.0
    assert module._interact_social_factor(settings) == 1.0


def test_presence_makes_interact_more_likely() -> None:
    """The segment's whole claim, measured on the draw rather than asserted in prose."""
    random.seed(7)
    settings = behavior_settings()
    context = context_for()

    def draws(perception, trials: int = 400) -> int:
        module = behavior_module()
        module._update_social_level(perception, settings, now=100.0)
        hits = 0
        for _ in range(trials):
            module._autonomy_mode = None
            module._last_autonomy_ts = 0.0
            if module._select_autonomy_mode(settings, context) == "interact":
                hits += 1
        return hits

    without = draws({"occupancy": None, "occupancy_valid": False})
    with_people = draws({"occupancy": True, "occupancy_valid": True})
    assert without > 0, "the baseline must reach interact, or the comparison proves nothing"
    assert with_people > without + 40, f"presence={with_people} baseline={without}"


def test_an_absent_interact_mode_is_left_alone() -> None:
    """The bias multiplies a weight the table offers; it does not add a mode of its own."""
    settings = behavior_settings()
    settings["autonomy_modes"] = ["idle", "patrol"]
    settings["autonomy_weights"] = {"idle": 1.0, "patrol": 1.0}
    module = behavior_module()
    module._update_social_level({"occupancy": True, "occupancy_valid": True}, settings, now=100.0)
    for _ in range(50):
        module._autonomy_mode = None
        module._last_autonomy_ts = 0.0
        assert module._select_autonomy_mode(settings, context_for()) in {"idle", "patrol"}


