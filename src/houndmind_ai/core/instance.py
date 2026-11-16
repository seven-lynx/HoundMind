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
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["BusBusy", "DEFAULT_LOCK_PATH", "DEFAULT_SESSION_PATH", "RunLock", "SessionMarker", "SessionReport"]

DEFAULT_LOCK_PATH = "~/.houndmind/run.lock"
DEFAULT_SESSION_PATH = "~/.houndmind/session.json"
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
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            os.lseek(fd, _LOCK_BYTES, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]

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

# ---- how the last session ended ------------------------------------------------


def _read_boot_id() -> str | None:
    """The kernel's per-boot identifier, or None where there is no `/proc` (a dev machine)."""
    try:
        text = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _read_throttled() -> str | None:
    """`vcgencmd get_throttled`, or None. Bits 16-18 are sticky for the life of the boot."""
    try:
        completed = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (completed.stdout or "").strip()
    if "=" not in text:
        return None
    return text.split("=", 1)[1].strip() or None


@dataclass(frozen=True)
class SessionReport:
    """How the previous session ended.

    `ending` is `unclean` (the process died, the machine did not), `reboot` (the machine went away
    under it) or `unknown` (a marker exists but cannot be attributed - a half-written file, or a
    machine with no boot id to compare).
    """

    ending: str
    started_at: float | None = None
    pid: int | None = None
    trace_id: str | None = None
    boot_changed: bool = False
    throttled: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "previous_ending": self.ending,
            "previous_started_at": self.started_at,
            "previous_pid": self.pid,
            "boot_changed": self.boot_changed,
            "throttled": self.throttled,
        }



class SessionMarker:
    """`~/.houndmind/session.json`: written at start, removed on a clean stop (#214).

    A crash and a power cut used to leave exactly the same trace - nothing - so a reboot could not
    be explained afterwards. The marker is the missing half of that pair: present at the next start
    means the last session did not stop itself, and the boot id says whether the machine went away
    under it (with `get_throttled` as the under-voltage fingerprint) or only the process did.

    It reports; it never resumes. A previous session is evidence, not a plan - motion never survives
    a restart, because the intent board and `motion_command` are context-only and intents expire.
    """

    def __init__(
        self,
        path: str | Path = DEFAULT_SESSION_PATH,
        boot_id: str | None = None,
        throttled: Callable[[], str | None] | None = None,
    ) -> None:
        self.path = Path(os.path.expanduser(str(path)))
        self._boot_id = boot_id if boot_id is not None else _read_boot_id()
        self._throttled = throttled or _read_throttled

    # ---- lifecycle ---------------------------------------------------------

    def begin(
        self,
        *,
        pid: int | None = None,
        trace_id: str | None = None,
        started_at: float | None = None,
    ) -> SessionReport | None:
        """Record this session and report the last one. None means it stopped cleanly."""
        report = self.previous()
        self._write(
            {
                "pid": os.getpid() if pid is None else pid,
                "trace_id": trace_id,
                "started_at": time.time() if started_at is None else started_at,
                "boot_id": self._boot_id,
            }
        )
        if report is not None:
            self._log(report)
        return report

    # ---- reading -----------------------------------------------------------

    def previous(self) -> SessionReport | None:
        """Whoever left a marker behind, or None when the last session closed itself."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return SessionReport("unknown")
        try:
            data = json.loads(raw)
        except ValueError:
            # A marker that cannot be parsed is still evidence that something died mid-write.
            return SessionReport("unknown")
        if not isinstance(data, dict):
            return SessionReport("unknown")

        previous_boot = data.get("boot_id")
        comparable = isinstance(previous_boot, str) and self._boot_id is not None
        same_boot = comparable and previous_boot == self._boot_id
        if same_boot:
            ending = "unclean"
        elif comparable:
            ending = "reboot"
        else:
            ending = "unknown"
        started_at = data.get("started_at")
        pid = data.get("pid")
        return SessionReport(
            ending=ending,
            started_at=started_at if isinstance(started_at, (int, float)) else None,
            pid=pid if isinstance(pid, int) else None,
            trace_id=data.get("trace_id") if isinstance(data.get("trace_id"), str) else None,
            boot_changed=ending == "reboot",
            # Asked only when the machine changed: an unclean stop inside one boot is a process
            # problem, and the throttle bits would say nothing about it.
            throttled=self._throttled() if ending == "reboot" else None,
        )

    def _log(self, report: SessionReport) -> None:
        started = f"{report.started_at:.0f}" if report.started_at is not None else "unknown"
        if report.ending == "unclean":
            logger.warning(
                "Previous run (pid %s, started %s) did not stop cleanly",
                report.pid if report.pid is not None else "unknown",
                started,
            )
        elif report.ending == "reboot":
            logger.warning(
                "Previous session (started %s) ended with a reboot; get_throttled=%s",
                started,
                report.throttled or "unavailable",
            )
        else:
            logger.warning(
                "Previous session left a marker this build cannot attribute: %s", self.path
            )

    # ---- writing -----------------------------------------------------------

    def _write(self, payload: dict[str, object]) -> None:
        """Write atomically, 0600 - the shape the routine and place stores use."""
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            # Losing the marker costs the next session its explanation; it must not cost this one
            # its run.
            logger.warning(
                "Cannot write %s (%s); this session will not be recorded", self.path, exc
            )
            with contextlib.suppress(OSError):
                tmp.unlink()

    def end(self) -> None:
        """A clean stop: the next start has nothing to explain."""
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

