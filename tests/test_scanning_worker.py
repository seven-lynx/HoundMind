"""Scanning runs off the decision loop (H-01, #13).

A sweep is nine head moves and 27 distance samples — ~2.6 s at the shipped settings against a
200 ms budget. These tests hold the worker inside a head move and prove the tick returns anyway.
"""

from __future__ import annotations

import logging
import threading
import time

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.navigation.scanning import ScanReading, ScanningModule, ScanningService


class BlockingHAL(FakeDogHAL):
    """A fake dog that hangs in a head move until the test lets it go."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()

    def action(self, name, params):  # type: ignore[override]
        if name == "head":
            self.gate.wait(5.0)
        super().action(name, params)


def settings(**overrides):
    base = {
        "scan_mode": "three_way",
        "scan_yaw_max_deg": 30,
        "scan_samples": 1,
        "scan_settle_s": 0.0,
        "scan_between_reads_s": 0.0,
        "head_scan_speed": 70,
        "scan_interval_s": 0.2,
        "scan_interval_min_s": 0.2,
        "scan_interval_max_s": 2.0,
        "scan_history_size": 5,
        "scan_continuous": True,
    }
    base.update(overrides)
    return {"navigation": base}


def build(hal=None, **overrides):
    hal = hal or FakeDogHAL()
    hal.set_distance(120.0)
    context = RuntimeContext()
    context.set("settings", settings(**overrides))
    context.set("hal", hal)
    module = ScanningModule("scanning")
    module.start(context)
    return module, context, hal


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_a_tick_does_not_wait_for_the_scan() -> None:
    """The whole point of H-01: the loop keeps ticking while the head is still moving."""
    hal = BlockingHAL()
    module, context, _ = build(hal)
    try:
        started = time.monotonic()
        module.tick(context)
        elapsed = time.monotonic() - started

        assert elapsed < 0.5, f"tick blocked for {elapsed:.2f}s"
        assert context.get("scan_in_flight") is True
        assert context.get("scan_reading") is None

        hal.gate.set()
        assert wait_until(lambda: context.get("scan_reading") is not None)
        assert context.get("scan_in_flight") is False
    finally:
        hal.gate.set()
        module.stop(context)


def test_the_scan_result_is_published_after_it_finishes() -> None:
    module, context, hal = build()
    try:
        module.tick(context)
        assert wait_until(lambda: context.get("scan_reading") is not None)

        reading = context.get("scan_reading")
        assert isinstance(reading, ScanReading)
        assert reading.data["forward"] == 120.0
        assert context.get("scan_latest")["mode"] == "three_way"
        assert context.get("scan_duration_s") is not None
        assert context.get("scan_history")
        assert context.get("scan_quality")["valid_ratio"] == 1.0
    finally:
        module.stop(context)


def test_a_second_tick_while_scanning_does_not_queue_another_scan() -> None:
    hal = BlockingHAL()
    module, context, _ = build(hal)
    try:
        module.tick(context)
        module.tick(context)
        module.tick(context)
        hal.gate.set()
        assert wait_until(lambda: context.get("scan_reading") is not None)
        module.tick(context)
        assert wait_until(lambda: context.get("scan_in_flight") is False)
    finally:
        hal.gate.set()
        module.stop(context)


def test_the_worker_is_owned_and_stopped() -> None:
    module, context, _ = build()
    worker = context.get("scan_worker")
    assert worker is not None
    module.stop(context)
    assert context.get("scan_worker") is None
    assert context.get("scan_in_flight") is False


def test_scan_continuous_false_scans_only_while_moving() -> None:
    """The old flag disabled scanning entirely while walking, which is when it is needed."""
    module, context, _ = build(**{"scan_continuous": False})
    try:
        module.tick(context)
        assert context.get("scan_in_flight") is False, "an idle dog has nothing to scan for"

        context.set("motion_command", {"action": "forward", "canonical_action": "forward"})
        module.tick(context)
        assert wait_until(lambda: context.get("scan_reading") is not None)
    finally:
        module.stop(context)


def test_the_service_records_a_bounded_history() -> None:
    service = ScanningService(FakeDogHAL(), {"scan_history_size": 3})
    for index in range(5):
        service.record(ScanReading(mode="sweep", data={0: float(index)}, timestamp=float(index)))

    assert len(service.history()) == 3
    assert service.latest().data == {0: 4.0}
    assert [entry.data for entry in service.history()] == [{0: 2.0}, {0: 3.0}, {0: 4.0}]


# ------------------------------------------------------------------ validity (#400) and head (#398)


class FailingRecentreHAL(FakeDogHAL):
    """A dog whose head will not come back to straight ahead after the second move to zero."""

    def __init__(self) -> None:
        super().__init__()
        self.zero_calls = 0

    def action(self, name, params):  # type: ignore[override]
        if name == "head" and int(params.get("yaw", 0)) == 0:
            self.zero_calls += 1
            if self.zero_calls > 1:
                raise RuntimeError("servo bus silent")
        super().action(name, params)


def test_a_failed_distance_read_is_zero_and_flagged_invalid() -> None:
    """#400: "no echo" and "a wall at zero centimetres" must not be the same JSON."""
    hal = FakeDogHAL()
    hal.set_distance(None)
    service = ScanningService(hal, settings()["navigation"])

    reading = service.scan_three_way()

    assert reading.data == {"forward": 0.0, "right": 0.0, "left": 0.0}
    assert reading.valid == {"forward": False, "right": False, "left": False}
    payload = reading.to_dict()
    assert payload["valid"] == {"forward": False, "right": False, "left": False}
    assert payload["head_centered"] is True


def test_a_measured_zero_is_valid() -> None:
    """A real zero-centimetre echo is a wall, not a failure - the flag has to tell them apart."""
    hal = FakeDogHAL()
    hal.set_distance(0.0)
    service = ScanningService(hal, settings()["navigation"])

    reading = service.scan_three_way()

    assert reading.data == {"forward": 0.0, "right": 0.0, "left": 0.0}
    assert reading.valid == {"forward": True, "right": True, "left": True}


def test_a_failed_recentre_is_on_the_reading_and_logged_once(caplog) -> None:
    """#398: the reading is real, the head did not come back, and that must be visible."""
    hal = FailingRecentreHAL()
    hal.set_distance(120.0)
    service = ScanningService(hal, settings()["navigation"])

    with caplog.at_level(logging.WARNING, logger="houndmind_ai.navigation.scanning"):
        reading = service.scan_three_way()

    assert reading.head_centered is False
    assert reading.to_dict()["head_centered"] is False
    assert reading.data["forward"] == 120.0, "the bearings it did take are still real"
    assert len([r for r in caplog.records if "head re-centre" in r.getMessage()]) == 1

    # The head stays broken: one transition, so no second warning.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="houndmind_ai.navigation.scanning"):
        assert service._center_head(70) is False
        assert service._center_head(70) is False

    assert [r for r in caplog.records if "head re-centre" in r.getMessage()] == []
