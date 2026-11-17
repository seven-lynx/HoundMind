"""Step odometry: heading x counted steps -> a pose, and honesty about when it is not one."""

from __future__ import annotations

import math

import pytest

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.navigation.odometry import OdometryModule


def _context(**settings: object) -> RuntimeContext:
    context = RuntimeContext()
    context.set("settings", {"odometry": {"step_cm": 25.0, **settings}})
    return context


def _step(module: OdometryModule, context: RuntimeContext, seq: int, action: str = "forward"):
    context.set("motion_command", {"seq": seq, "canonical_action": action, "action": action})
    module.tick(context)
    return context.get("odometry")


def test_one_step_is_one_step_cm_along_the_heading() -> None:
    context = _context()
    context.set("current_heading", 0.0)
    odometry = _step(OdometryModule("odometry"), context, 1)

    assert odometry["steps"] == 1
    assert odometry["distance_cm"] == pytest.approx(25.0)
    assert odometry["x_cm"] == pytest.approx(25.0)
    assert odometry["y_cm"] == pytest.approx(0.0)
    assert odometry["pose_valid"] is True
    assert odometry["reason"] is None


def test_a_repeated_command_is_not_a_second_step() -> None:
    """The gateway re-keeps a repeated intent without re-issuing it, so `seq` stays put."""
    context = _context()
    context.set("current_heading", 0.0)
    module = OdometryModule("odometry")

    _step(module, context, 1)
    odometry = _step(module, context, 1)

    assert odometry["steps"] == 1
    assert odometry["distance_cm"] == pytest.approx(25.0)


def test_heading_ninety_degrees_walks_along_positive_y() -> None:
    context = _context()
    context.set("current_heading", 90.0)
    odometry = _step(OdometryModule("odometry"), context, 1)

    assert odometry["x_cm"] == pytest.approx(0.0, abs=1e-6)
    assert odometry["y_cm"] == pytest.approx(25.0)
    assert odometry["yaw_deg"] == pytest.approx(90.0)


def test_backward_is_a_signed_step() -> None:
    context = _context()
    context.set("current_heading", 0.0)
    odometry = _step(OdometryModule("odometry"), context, 1, action="backward")

    assert odometry["steps"] == 1
    assert odometry["distance_cm"] == pytest.approx(-25.0)
    assert odometry["x_cm"] == pytest.approx(-25.0)
    # Travelled distance is what expiry uses, so reversing does not undo it.
    assert odometry["travelled_cm"] == pytest.approx(25.0)


def test_backward_can_be_ignored() -> None:
    context = _context(track_backward=False)
    context.set("current_heading", 0.0)
    odometry = _step(OdometryModule("odometry"), context, 1, action="backward")

    assert odometry["steps"] == 0
    assert odometry["distance_cm"] == pytest.approx(0.0)


def test_a_turn_is_not_a_step() -> None:
    context = _context()
    context.set("current_heading", 0.0)
    odometry = _step(OdometryModule("odometry"), context, 1, action="turn left")

    assert odometry["steps"] == 0


def test_without_a_heading_the_step_is_counted_but_not_placed() -> None:
    context = _context()
    odometry = _step(OdometryModule("odometry"), context, 1)

    assert odometry["steps"] == 1
    assert odometry["distance_cm"] == pytest.approx(25.0)
    assert odometry["x_cm"] == pytest.approx(0.0)
    assert odometry["pose_valid"] is False
    assert "heading" in str(odometry["reason"])


def test_a_command_without_a_sequence_is_not_counted() -> None:
    """A payload cannot be counted honestly without knowing it is a *new* one."""
    context = _context()
    context.set("current_heading", 0.0)
    context.set("motion_command", {"canonical_action": "forward"})
    module = OdometryModule("odometry")
    module.tick(context)

    odometry = context.get("odometry")
    assert odometry["steps"] == 0
    assert "seq" in str(odometry["reason"])


def test_odometry_reset_reanchors_the_pose() -> None:
    context = _context()
    context.set("current_heading", 0.0)
    module = OdometryModule("odometry")
    _step(module, context, 1)

    context.set("odometry_reset", True)
    module.tick(context)

    odometry = context.get("odometry")
    assert odometry["steps"] == 0
    assert odometry["x_cm"] == pytest.approx(0.0)
    assert odometry["travelled_cm"] == pytest.approx(0.0)
