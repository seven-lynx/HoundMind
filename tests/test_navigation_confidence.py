"""`nav.confidence` is a number the navigator measured, or `null` when nothing did.

`services/state.py::_nav` read a `confidence` key the producer never wrote, so the field was
`null` on every tick on every profile (#51), and the `confidence` field of the decision record
(#44) inherited the same permanent null. The value the scan computes - the share of the confirm
window that agreed on a direction - now travels with the decision instead of being thrown away.

The tests here do not map `score` onto `confidence`: a scan score is a ranking value and a
probability invented from it would be worse than reporting none.
"""

from __future__ import annotations

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.navigation.obstacle_avoidance import ObstacleAvoidanceModule
from houndmind_ai.navigation.scanning import ScanReading
from houndmind_ai.services.state import build_state

SETTINGS = {
    "confirm_window": 2,
    "confirm_threshold": 2,
    "turn_confidence_min": 0.6,
    "min_gap_width_deg": 30,
    "min_score_cm": 60,
    "scan_yaw_max_deg": 60,
    "scan_min_valid_points": 3,
    "scan_min_valid_ratio": 0.5,
    "baseline_ema": 0.25,
}


def open_on_the_left() -> ScanReading:
    """Forward is inside the scoring threshold; left and right are clear."""
    return ScanReading(mode="three_way", data={"left": 100.0, "forward": 30.0, "right": 90.0}, timestamp=1.0)


def test_the_scan_reports_the_share_of_the_window_that_agreed() -> None:
    """One vote of a two-vote window is 0.5 and is not confirmed; two votes is 1.0 and is."""
    module = ObstacleAvoidanceModule("avoid_test")

    first = module._process_scan(open_on_the_left(), dict(SETTINGS))
    assert first is not None
    direction, _score, confirmed, confidence = first
    assert confidence == 0.5
    assert confirmed is False

    second = module._process_scan(open_on_the_left(), dict(SETTINGS))
    assert second is not None
    assert second[0] == direction
    assert second[2] is True
    assert second[3] == 1.0


def test_the_confidence_is_not_the_scan_score() -> None:
    """Two different numbers: the score ranks a gap, the confidence counts votes."""
    module = ObstacleAvoidanceModule("avoid_test")
    result = module._process_scan(open_on_the_left(), dict(SETTINGS))
    assert result is not None
    _direction, score, _confirmed, confidence = result
    assert confidence in (0.5, 1.0)
    assert score != confidence


def test_the_published_decision_carries_the_confidence() -> None:
    module = ObstacleAvoidanceModule("avoid_test")
    context = RuntimeContext()

    module._emit_navigation_decision(context, dict(SETTINGS), "left", 12.0, True, 0.75)

    decision = context.get("navigation_decision")
    assert decision["confidence"] == 0.75
    assert decision["score"] == 12.0


def test_a_decision_without_a_scan_reports_no_confidence() -> None:
    """A clear-path streak is not a measurement, so the key is `null` rather than a made-up 1.0."""
    module = ObstacleAvoidanceModule("avoid_test")
    context = RuntimeContext()

    module._emit_navigation_decision(context, dict(SETTINGS), "forward", 0.0, True, None)

    decision = context.get("navigation_decision")
    assert "confidence" in decision
    assert decision["confidence"] is None


def test_the_snapshot_reports_what_the_navigator_published() -> None:
    context = RuntimeContext()
    context.set(
        "navigation_decision", {"direction": "left", "score": 12.0, "confidence": 0.75}
    )

    snapshot = build_state(context, now=100.0)

    assert snapshot["nav"]["confidence"] == 0.75


def test_the_snapshot_stays_null_when_the_navigator_reported_none() -> None:
    context = RuntimeContext()
    context.set("navigation_decision", {"direction": "forward", "confidence": None})

    snapshot = build_state(context, now=100.0)

    assert snapshot["nav"]["confidence"] is None
