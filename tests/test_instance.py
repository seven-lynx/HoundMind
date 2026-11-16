"""One process at a time may own the servo bus (#213).

The bench symptom was a tool that printed nothing for 150 s and had to be killed: its `Pidog()`
construction blocked on a bus the runtime already held, and neither process could say so. These
cases pin the guard, and the reason a second process gets instead of a hang.
"""

from __future__ import annotations

import os

import pytest

from houndmind_ai.core.instance import BusBusy, RunLock


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
