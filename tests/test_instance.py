"""One process at a time may own the servo bus (#213).

The bench symptom was a tool that printed nothing for 150 s and had to be killed: its `Pidog()`
construction blocked on a bus the runtime already held, and neither process could say so. These
cases pin the guard, and the reason a second process gets instead of a hang.
"""

from __future__ import annotations

import json
import logging
import os

import pytest

from houndmind_ai.core.instance import BusBusy, RunLock, SessionMarker


def test_a_second_owner_is_refused_and_named(tmp_path):
    path = tmp_path / "run.lock"
    first = RunLock(path)
    second = RunLock(path)

    first.acquire("runtime")
    try:
        with pytest.raises(BusBusy) as caught:
            second.acquire("hardware_checkup")
    finally:
        first.release()

    message = str(caught.value)
    assert "the servo bus is owned by" in message
    # The point of the file: the refusal says who, so the operator knows what to stop.
    assert "runtime" in message
    assert str(os.getpid()) in message


def test_the_lock_file_records_the_holder(tmp_path):
    path = tmp_path / "run.lock"
    lock = RunLock(path)

    lock.acquire("runtime")
    try:
        holder = path.read_text(encoding="utf-8").strip()
    finally:
        lock.release()

    assert holder == f"pid {os.getpid()} (runtime)"


def test_releasing_lets_the_next_owner_in(tmp_path):
    path = tmp_path / "run.lock"
    first = RunLock(path)
    second = RunLock(path)

    first.acquire("runtime")
    first.release()
    second.acquire("hardware_checkup")
    try:
        assert second.held
    finally:
        second.release()


def test_acquiring_twice_in_one_owner_is_a_no_op(tmp_path):
    """A tool holds the lock across a call that would otherwise take it again."""
    lock = RunLock(tmp_path / "run.lock")

    lock.acquire("runtime")
    lock.acquire("runtime")
    lock.release()

    assert not lock.held


def test_release_without_acquire_is_safe(tmp_path):
    RunLock(tmp_path / "run.lock").release()


def test_an_unusable_lock_path_warns_instead_of_stopping_the_dog(tmp_path):
    """The guard is a courtesy between processes, not a prerequisite for driving one."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    lock = RunLock(blocker / "run.lock")

    lock.acquire("runtime")

    assert not lock.held


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes; Windows ignores them")
def test_the_lock_file_is_private(tmp_path):
    path = tmp_path / "run.lock"
    lock = RunLock(path)

    lock.acquire("runtime")
    try:
        assert path.stat().st_mode & 0o077 == 0
    finally:
        lock.release()


# ---- the session marker (#214) -------------------------------------------------


def test_a_first_start_has_nothing_to_report(tmp_path):
    assert SessionMarker(tmp_path / "session.json", boot_id="boot-a").begin(pid=1) is None


def test_the_marker_records_the_session(tmp_path):
    path = tmp_path / "session.json"

    SessionMarker(path, boot_id="boot-a").begin(pid=4242, trace_id="abc", started_at=100.0)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "pid": 4242,
        "trace_id": "abc",
        "started_at": 100.0,
        "boot_id": "boot-a",
    }


def test_the_same_boot_means_the_process_died(tmp_path):
    path = tmp_path / "session.json"
    SessionMarker(path, boot_id="boot-a").begin(pid=4242, started_at=100.0)

    report = SessionMarker(path, boot_id="boot-a").begin(pid=4243, started_at=200.0)

    assert report is not None
    assert report.ending == "unclean"
    assert report.pid == 4242
    assert report.started_at == 100.0
    assert report.boot_changed is False
    # Inside one boot the supply did not change, so the command is not even asked.
    assert report.throttled is None


def test_a_new_boot_means_the_machine_went_away(tmp_path):
    path = tmp_path / "session.json"
    SessionMarker(path, boot_id="boot-a").begin(pid=4242, started_at=100.0)
    asked: list[str] = []

    def throttled() -> str:
        asked.append("get_throttled")
        return "0x50000"

    report = SessionMarker(path, boot_id="boot-b", throttled=throttled).begin(pid=4243)

    assert report is not None
    assert report.ending == "reboot"
    assert report.boot_changed is True
    assert report.throttled == "0x50000"
    assert asked == ["get_throttled"]


def test_a_clean_stop_leaves_nothing_to_explain(tmp_path):
    marker = SessionMarker(tmp_path / "session.json", boot_id="boot-a")
    marker.begin(pid=1)

    marker.end()

    assert marker.previous() is None
    assert SessionMarker(marker.path, boot_id="boot-a").begin(pid=2) is None


def test_an_unreadable_marker_is_reported_as_unknown(tmp_path):
    path = tmp_path / "session.json"
    path.write_text("{not json", encoding="utf-8")

    report = SessionMarker(path, boot_id="boot-a").begin(pid=1)

    assert report is not None
    assert report.ending == "unknown"


def test_a_marker_without_a_boot_id_is_unknown(tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"pid": 1, "started_at": 10.0}), encoding="utf-8")

    report = SessionMarker(path, boot_id="boot-a").begin(pid=2)

    assert report is not None
    assert report.ending == "unknown"


def test_the_previous_failure_is_logged_once(tmp_path, caplog):
    path = tmp_path / "session.json"
    SessionMarker(path, boot_id="boot-a").begin(pid=4242, started_at=100.0)

    with caplog.at_level(logging.WARNING, logger="houndmind_ai.core.instance"):
        SessionMarker(path, boot_id="boot-a").begin(pid=4243)

    messages = [record.getMessage() for record in caplog.records]
    assert any("did not stop cleanly" in message for message in messages)
