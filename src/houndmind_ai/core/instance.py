"""One process at a time may own the servo bus (#213).

Two `Pidog()` instances is not a failure either side can report: the second construction blocks on
the bus the first one holds, so a bench tool started while the runtime is up produces **no output at
all** — 150 s of nothing, then a `timeout` kill, and nothing to diagnose it with.

This is an advisory file lock, not a pid file, because the kernel drops it when the process goes
away: a `kill -9` cannot leave a stale owner behind the way a written pid can. The file sits with
the rest of the device's state (`~/.houndmind/`), and it records who holds it only so the *next*
process can say so instead of hanging.

The lock belongs to the **entry point**, not to `HoundMindRuntime`: a tool that constructs the
vendor HAL takes it first, and a tool handed a `FakeDogHAL` takes nothing, which keeps the test
suite off the home directory.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["BusBusy", "DEFAULT_LOCK_PATH", "RunLock"]

DEFAULT_LOCK_PATH = "~/.houndmind/run.lock"
# Windows denies reads of a locked range, and the holder's name has to stay readable by whoever is
# being told to stop, so the locked byte sits far past the text.
_LOCK_BYTES = 1024


class BusBusy(RuntimeError):
    """Another process owns the servo bus.

    Carries the holder's own words (`pid 1234 (runtime)`) so a caller can print a reason rather
    than a stack trace.
    """

    def __init__(self, holder: str, path: Path) -> None:
        self.holder = holder
        self.path = path
        super().__init__(f"the servo bus is owned by {holder}")


if os.name == "nt":  # pragma: no cover - the Windows half of a POSIX-first guard
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            os.lseek(fd, _LOCK_BYTES, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            os.lseek(fd, _LOCK_BYTES, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _holder_of(path: Path) -> str | None:
    """Whoever wrote the file last, or None. Best effort: this is a hint for a message."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


class RunLock:
    """The servo bus, held exclusively for the life of a process.

    Two instances over the same path are two owners, and the second raises `BusBusy` — that is the
    case the class exists for. The same instance acquired twice is a no-op, so a tool can hold the
    lock across a call that would otherwise take it again.
    """

    def __init__(self, path: str | Path = DEFAULT_LOCK_PATH) -> None:
        self.path = Path(os.path.expanduser(str(path)))
        self._fd: int | None = None
        self._holder: str | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    @property
    def holder(self) -> str | None:
        return self._holder

    def acquire(self, holder: str) -> None:
        """Take the lock, or raise `BusBusy` naming the process that has it."""
        if self._fd is not None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            # A read-only home is not a reason to refuse to drive the dog. The guard is a
            # courtesy between two processes, not a prerequisite for running one.
            logger.warning(
                "Cannot open %s (%s); running without the single-instance guard", self.path, exc
            )
            return
        if not _try_lock(fd):
            previous = _holder_of(self.path) or "another process"
            with contextlib.suppress(OSError):
                os.close(fd)
            raise BusBusy(previous, self.path)
        stamp = f"pid {os.getpid()} ({holder})"
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, (stamp + "\n").encode("utf-8"))
        self._fd = fd
        self._holder = stamp

    def release(self) -> None:
        """Give the bus up. Safe to call when it was never taken.

        The file is left in place on purpose: unlinking a lock file that another process may have
        just opened hands out a second lock on an inode nobody else can see.
        """
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        self._holder = None
        _unlock(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
