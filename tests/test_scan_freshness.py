"""One staleness window for a scan, shared by the watchdog and the navigator (#22).

`navigation.scan_stale_s` shipped as 0.8 s while a sweep at the shipped settings takes ~2.6 s, so
`_scan_open_space` rejected a healthy reading and then fell back to `scan_service.latest()` with no
timestamp check at all: the guard was dead code and the fallback chose the direction. The rule now
lives in `navigation/scanning.py::scan_freshness_window_s`, the watchdog publishes the number it
used as `scan_stale_after_s`, and the navigator prefers that number over a second calculation.
"""

from __future__ import annotations

import time

import pytest

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.navigation.obstacle_avoidance import ObstacleAvoidanceModule
from houndmind_ai.navigation.scanning import ScanReading, scan_freshness_window_s

SETTINGS = {
    "navigation": {
        "confirm_window": 2,
        "confirm_threshold": 1,
        "turn_confidence_min": 0.6,
        "min_gap_width_deg": 30,
        "min_score_cm": 60,
        "scan_yaw_max_deg": 60,
        "scan_min_valid_points": 3,
        "scan_min_valid_ratio": 0.5,
        "baseline_ema": 0.25,
    },
    "watchdog": {"enabled": True, "scan_timeout_s": 2.0},
}


def reading(age_s: float) -> ScanReading:
    """A scan whose forward lane is blocked, so a direction decision has to be made."""
    return ScanReading(
        mode="three_way",
        data={"left": 100.0, "forward": 30.0, "right": 90.0},
        timestamp=time.time() - age_s,
    )


def context_with(**extra: object) -> RuntimeContext:
    context = RuntimeContext()
    context.set("settings", SETTINGS)
    for key, value in extra.items():
        context.set(key, value)
    return context


class FakeScanService:
    """`latest()` and nothing else: the navigator must not start a sweep from its tick."""

    def __init__(self, latest: ScanReading | None) -> None:
        self._latest = latest

    def latest(self) -> ScanReading | None:
        return self._latest


def open_space(context: RuntimeContext):
    module = ObstacleAvoidanceModule("avoid_test")
    return module._scan_open_space(context, SETTINGS["navigation"], time.time())


def test_the_window_is_the_floor_or_one_and_a_half_sweeps() -> None:
    assert scan_freshness_window_s(2.0, 2.6) == pytest.approx(3.9)
    assert scan_freshness_window_s(2.0, 0.0) == 2.0
    assert scan_freshness_window_s(2.0, None) == 2.0
    # No configured floor, and a value a broken config could hand over: the module constant.
    assert scan_freshness_window_s(None, 4.0) == 6.0
    assert scan_freshness_window_s(0, 0) == 2.0
    assert scan_freshness_window_s("nonsense", "nonsense") == 2.0


def test_a_three_second_old_scan_is_a_basis_for_a_direction() -> None:
    """The acceptance case: 3.0 s old with a 2.6 s measured sweep is fresh (window 3.9 s)."""
    context = context_with(scan_duration_s=2.6, scan_reading=reading(3.0))
    assert open_space(context) is not None


def test_a_reading_older_than_the_window_is_not_used() -> None:
    context = context_with(scan_duration_s=2.6, scan_reading=reading(10.0))
    assert open_space(context) is None


def test_a_stale_service_reading_is_rejected_and_not_published() -> None:
    """The fallback used to publish it into `scan_reading`, so nothing downstream could tell."""
    context = context_with(scan_duration_s=2.6, scan_service=FakeScanService(reading(10.0)))
    assert open_space(context) is None
    assert context.get("scan_reading") is None, "a rejected reading must not be laundered"
    assert context.get("scan_latest") is None


def test_a_fresh_service_reading_is_still_used() -> None:
    """The fallback is not disabled, only guarded."""
    fresh = reading(1.0)
    context = context_with(scan_duration_s=2.6, scan_service=FakeScanService(fresh))
    assert open_space(context) is not None
    assert context.get("scan_reading") is fresh


def test_the_watchdogs_published_window_wins() -> None:
    """Two calculations that happen to agree are not one rule; prefer the published number."""
    # The watchdog said 10 s; the derived rule would say 3.9 s. 5 s old is inside the first.
    fresh_by_watchdog = context_with(
        scan_stale_after_s=10.0, scan_duration_s=2.6, scan_reading=reading(5.0)
    )
    assert open_space(fresh_by_watchdog) is not None

    # The watchdog said 1 s; 2 s old is outside it, whatever the measured sweep says.
    stale_by_watchdog = context_with(
        scan_stale_after_s=1.0, scan_duration_s=2.6, scan_reading=reading(2.0)
    )
    assert open_space(stale_by_watchdog) is None
