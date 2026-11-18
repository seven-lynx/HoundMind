"""The localization ladder: SLAM -> dead reckoning -> reactive, and the reason at each step."""

from __future__ import annotations

import pytest

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.navigation.localization import LocalizationModule, LocalizationTier


class _Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _setup(**settings: object) -> tuple[LocalizationModule, RuntimeContext, _Clock]:
    clock = _Clock()
    module = LocalizationModule("localization", enabled=True)
    module._clock = clock
    # Construction stamped the real monotonic clock; re-stamp on this one or every age goes negative.
    module._corrected_at = clock()
    context = RuntimeContext()
    context.set("settings", {"localization": settings})
    return module, context, clock


def _odometry(travelled_cm: float = 0.0, valid: bool = True, reason: str | None = None) -> dict:
    return {
        "travelled_cm": travelled_cm,
        "x_cm": 10.0,
        "y_cm": -5.0,
        "yaw_deg": 15.0,
        "pose_valid": valid,
        "reason": reason,
    }


def _slam(
    context: RuntimeContext,
    backend: str = "rtabmap",
    beat: object = 1.0,
    confidence: float = 0.9,
) -> None:
    context.set("slam_status", {"status": "ready", "backend": backend})
    context.set("module_heartbeat:slam_pi4", beat)
    context.set("slam_pose", {"x": 1.5, "y": 2.5, "yaw": 30.0, "confidence": confidence})


def test_without_slam_the_dog_reports_dead_reckoning() -> None:
    module, context, _ = _setup()
    context.set("odometry", _odometry())

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.DEAD_RECKONING)
    assert data["frame"] == "odometry"
    assert data["pose"] == {"x": 10.0, "y": -5.0, "yaw_deg": 15.0}
    assert data["confidence"] == pytest.approx(1.0)
    assert "no SLAM backend" in str(data["reason"])


def test_a_real_slam_backend_takes_the_top_tier() -> None:
    module, context, _ = _setup()
    context.set("odometry", _odometry())
    _slam(context)

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.SLAM)
    assert data["frame"] == "slam"
    assert data["pose"] == {"x": 1.5, "y": 2.5, "yaw_deg": 30.0}
    assert data["reason"] is None


def test_the_stub_is_not_the_slam_tier() -> None:
    """`backend: "stub"` is a gyro integrator whose pose never leaves the origin."""
    module, context, _ = _setup()
    context.set("odometry", _odometry())
    _slam(context, backend="stub")

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.DEAD_RECKONING)
    assert "stub" in str(data["reason"])


def test_a_stale_slam_pose_falls_back() -> None:
    module, context, clock = _setup(slam_max_age_s=2.0)
    context.set("odometry", _odometry())
    _slam(context, beat=1.0)
    module.tick(context)

    clock.advance(5.0)
    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.DEAD_RECKONING)
    assert "stale" in str(data["reason"])


def test_a_low_confidence_slam_pose_falls_back() -> None:
    module, context, _ = _setup(slam_min_confidence=0.2)
    context.set("odometry", _odometry())
    _slam(context, confidence=0.05)

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.DEAD_RECKONING)
    assert "confidence" in str(data["reason"])


def test_a_slam_backend_with_no_heartbeat_is_not_trusted() -> None:
    module, context, _ = _setup()
    context.set("odometry", _odometry())
    context.set("slam_status", {"status": "ready", "backend": "rtabmap"})
    context.set("slam_pose", {"x": 0.0, "y": 0.0, "yaw": 0.0, "confidence": 0.9})

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.DEAD_RECKONING)
    assert "heartbeat" in str(data["reason"])


def test_dead_reckoning_expires_into_reactive() -> None:
    module, context, _ = _setup(dead_reckoning_scale_m=10.0, confidence_floor=0.15)
    context.set("odometry", _odometry(travelled_cm=1000.0))

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.REACTIVE)
    assert data["pose"] is None
    assert data["confidence"] == pytest.approx(0.0)
    assert "expired" in str(data["reason"])


def test_no_pose_source_at_all_is_reactive() -> None:
    module, context, _ = _setup()
    context.set("odometry", _odometry(valid=False, reason="no heading for this step"))

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.REACTIVE)
    assert data["pose"] is None
    assert "heading" in str(data["reason"])


def test_the_transition_is_announced_once() -> None:
    module, context, _ = _setup()
    context.set("odometry", _odometry())

    module.tick(context)
    event = context.get("localization_event")
    assert event["from"] is None
    assert event["to"] == str(LocalizationTier.DEAD_RECKONING)

    context.set("localization_event", None)
    module.tick(context)
    assert context.get("localization_event") is None, "no change, no event"


def test_a_slam_fix_restores_the_drift_confidence() -> None:
    """An absolute fix is what expires dead reckoning, so it restarts the drift clock."""
    module, context, clock = _setup(dead_reckoning_scale_m=10.0, confidence_floor=0.15)
    context.set("odometry", _odometry(travelled_cm=1000.0))
    module.tick(context)
    assert context.get("localization")["tier"] == str(LocalizationTier.REACTIVE)

    _slam(context, beat=2.0)
    module.tick(context)
    assert context.get("localization")["tier"] == str(LocalizationTier.SLAM)

    # The backend goes away again; nothing was walked since the fix, so the pose comes back.
    context.set("slam_status", {"status": "ready", "backend": "stub"})
    clock.advance(1.0)
    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.DEAD_RECKONING)
    assert data["confidence"] > 0.9


def _place_fix(context: RuntimeContext, place_id: str = "kitchen", stamp: float = 5.0) -> None:
    context.set(
        "place_fix",
        {"ts": 1_700_000_000.0, "place_id": place_id, "confidence": 0.8, "frame_ts": stamp},
    )


def test_a_confirmed_place_match_outranks_dead_reckoning() -> None:
    """#297: a view match is an absolute fix, so the tier says which room the dog is in."""
    module, context, _ = _setup()
    context.set("odometry", _odometry())
    _place_fix(context)

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.PLACE)
    assert data["frame"] == "odometry", "the pose is still odometry, measured from the new anchor"
    assert data["reason"] == "kitchen"
    assert data["confidence"] == 0.8


def test_a_stale_place_fix_falls_back_to_dead_reckoning() -> None:
    module, context, clock = _setup(place_max_age_s=30.0)
    context.set("odometry", _odometry())
    _place_fix(context)
    module.tick(context)
    assert context.get("localization")["tier"] == str(LocalizationTier.PLACE)

    clock.advance(31.0)
    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.DEAD_RECKONING)
    assert "stale" in data["reason"]


def test_a_place_fix_without_a_pose_is_not_a_tier() -> None:
    """The view says which room; only odometry can say where in it, and its absence is reported."""
    module, context, _ = _setup()
    context.set("odometry", _odometry(valid=False, reason="no heading"))
    _place_fix(context)

    module.tick(context)

    data = context.get("localization")
    assert data["tier"] == str(LocalizationTier.REACTIVE)
    assert data["pose"] is None
    assert "no odometry pose" in data["reason"]


def test_slam_still_wins_over_a_place_match() -> None:
    module, context, _ = _setup()
    context.set("odometry", _odometry())
    _slam(context)
    _place_fix(context)

    module.tick(context)

    assert context.get("localization")["tier"] == str(LocalizationTier.SLAM)


def _anchor(stamp: object = 1.0, x_cm: float = 10.0, y_cm: float = -5.0) -> dict:
    return {"source": "user", "x_cm": x_cm, "y_cm": y_cm, "frame_ts": stamp}


def test_a_position_the_user_confirmed_is_the_top_tier() -> None:
    """M5: the console's correction has to reach the ladder, or the drag changed nothing."""
    module, context, _ = _setup()
    odometry = _odometry()
    odometry["anchor"] = _anchor()
    context.set("odometry", odometry)

    module.tick(context)

    localization = context.get("localization")
    assert localization["tier"] == str(LocalizationTier.USER)
    assert localization["pose"]["x"] == pytest.approx(10.0)
    assert localization["frame"] == "odometry"
    assert "confirmed" in (localization["reason"] or "")


def test_a_fresh_correction_outranks_a_live_slam_pose() -> None:
    """The correction is the one claim that says the map's frame is wrong - that is why M5 exists."""
    module, context, _ = _setup()
    odometry = _odometry()
    odometry["anchor"] = _anchor()
    context.set("odometry", odometry)
    _slam(context)

    module.tick(context)

    assert context.get("localization")["tier"] == str(LocalizationTier.USER)


def test_a_user_position_expires_like_any_other_anchor() -> None:
    """Bounded in age, or a correction made once becomes a claim the dog never gives up."""
    module, context, clock = _setup()
    odometry = _odometry()
    odometry["anchor"] = _anchor()
    context.set("odometry", odometry)
    module.tick(context)

    clock.advance(31.0)
    module.tick(context)

    assert context.get("localization")["tier"] == str(LocalizationTier.DEAD_RECKONING)


def test_a_correction_without_a_pose_behind_it_is_not_a_tier() -> None:
    """A position with no heading is a point on a canvas, not a pose the dog can plan from."""
    module, context, _ = _setup()
    odometry = _odometry(valid=False, reason="no heading for this step")
    odometry["anchor"] = _anchor()
    context.set("odometry", odometry)

    module.tick(context)

    localization = context.get("localization")
    assert localization["tier"] == str(LocalizationTier.REACTIVE)
    assert localization["pose"] is None


def test_the_walk_is_recorded_once_the_dog_has_moved() -> None:
    """M6: a breadcrumb per five centimetres, not per tick - a still dog is not a walk."""
    module, context, _ = _setup()
    odometry = _odometry()
    context.set("odometry", odometry)

    module.tick(context)
    assert len(context.get("pose_trail")) == 1

    odometry["x_cm"] = 40.0  # thirty centimetres on
    context.set("odometry", odometry)
    module.tick(context)

    trail = context.get("pose_trail")
    assert len(trail) == 2
    assert trail[-1]["x_cm"] == pytest.approx(40.0)


def test_a_pose_that_barely_moved_is_not_a_second_breadcrumb() -> None:
    module, context, _ = _setup()
    odometry = _odometry()
    context.set("odometry", odometry)
    module.tick(context)

    odometry["x_cm"] = 12.0  # two centimetres
    context.set("odometry", odometry)
    module.tick(context)

    assert len(context.get("pose_trail")) == 1


def test_slam_points_are_not_mixed_into_the_odometry_trail() -> None:
    """A trail with two frames on it draws a walk through rooms the dog was never in."""
    module, context, _ = _setup()
    context.set("odometry", _odometry())
    _slam(context)

    module.tick(context)

    assert context.get("pose_trail") is None


def test_a_correction_empties_the_trail_it_invalidated() -> None:
    """Every point before the correction is in the origin that correction just replaced."""
    module, context, _ = _setup()
    odometry = _odometry()
    context.set("odometry", odometry)
    module.tick(context)
    odometry["x_cm"] = 40.0
    context.set("odometry", odometry)
    module.tick(context)
    assert len(context.get("pose_trail")) == 2

    corrected = _odometry()
    corrected["anchor"] = _anchor(stamp=2.0)
    context.set("odometry", corrected)
    module.tick(context)

    trail = context.get("pose_trail")
    assert len(trail) == 1
    assert trail[0]["tier"] == str(LocalizationTier.USER)

