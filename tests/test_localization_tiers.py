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
