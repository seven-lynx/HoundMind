"""The latest-value worker: one owned thread, newest wins, and it never dies on a bad job."""

from __future__ import annotations

import threading
import time

from houndmind_ai.kernel.scheduler import LatestJobWorker


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_a_submitted_job_runs() -> None:
    worker = LatestJobWorker("test")
    worker.start()
    try:
        done = threading.Event()
        worker.submit("scan", done.set)
        assert done.wait(2.0), "the job never ran"
        assert worker.completed == 1
    finally:
        worker.stop()


def test_a_second_submit_for_the_same_key_replaces_the_first() -> None:
    """Queueing both would run a scan whose result is already superseded."""
    worker = LatestJobWorker("test")
    gate = threading.Event()
    ran: list[str] = []

    worker.start()
    try:
        worker.submit("scan", lambda: gate.wait(2.0))
        assert wait_until(lambda: worker.busy)
        worker.submit("scan", lambda: ran.append("second"))
        gate.set()

        assert wait_until(lambda: "second" in ran), ran
        assert worker.replaced == 1
    finally:
        gate.set()
        worker.stop()


def test_different_keys_are_kept_separately() -> None:
    worker = LatestJobWorker("test")
    ran: list[str] = []
    worker.start()
    try:
        worker.submit("a", lambda: ran.append("a"))
        worker.submit("b", lambda: ran.append("b"))
        assert wait_until(lambda: len(ran) == 2), ran
        assert set(ran) == {"a", "b"}
        assert worker.replaced == 0
    finally:
        worker.stop()


def test_a_failing_job_does_not_kill_the_worker() -> None:
    worker = LatestJobWorker("test")
    ran: list[str] = []
    worker.start()
    try:
        worker.submit("boom", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert wait_until(lambda: worker.failed == 1)
        worker.submit("next", lambda: ran.append("next"))
        assert wait_until(lambda: "next" in ran), ran
        assert worker.last_error == "boom"
    finally:
        worker.stop()


def test_stop_drops_pending_work_and_joins() -> None:
    worker = LatestJobWorker("test")
    gate = threading.Event()
    worker.start()
    worker.submit("slow", lambda: gate.wait(2.0))
    assert wait_until(lambda: worker.busy)
    worker.submit("queued", lambda: None)

    gate.set()
    worker.stop(timeout=2.0)

    assert worker.busy is False
    assert worker.submit("late", lambda: None) is False, "a stopped worker accepts nothing"


def test_busy_reports_queued_and_running_work() -> None:
    worker = LatestJobWorker("test")
    gate = threading.Event()
    assert worker.busy is False

    worker.start()
    try:
        worker.submit("slow", lambda: gate.wait(2.0))
        assert wait_until(lambda: worker.busy)
        gate.set()
        assert wait_until(lambda: not worker.busy)
    finally:
        gate.set()
        worker.stop()