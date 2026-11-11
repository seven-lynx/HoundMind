"""One owned worker for the work that blocks, with latest-value semantics.

`ScanningModule.tick` used to run a head sweep itself. A sweep is nine head moves, nine settle
sleeps and 27 distance samples: ~2.6 s of blocking against a 200 ms tick budget, every time a scan
came due (H-01, #13). The decision loop read stale sensors for two seconds, the watchdog called the
scan stale while it was still running, and the loop's own overrun warning fired on schedule.

Two things are needed to fix that, and neither is a thread pool:

- **The decision path submits, never waits.** `submit` returns immediately and the module keeps
  ticking.
- **Latest value wins.** If a scan is asked for while one is still running, the *newer* request is
  what matters; queueing the older one would run a scan whose result is already stale. So a key
  holds at most one pending job, and a second submit with the same key replaces it.

The worker is owned: `start()` begins it, `stop()` joins it. `daemon=True` with no owner is the
pattern ARCHITECTURE §3 rule 4 forbids.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

__all__ = ["LatestJobWorker"]

logger = logging.getLogger(__name__)


class LatestJobWorker:
    """A single background thread that runs at most one job per key, newest first."""

    def __init__(self, name: str, clock: Callable[[], float] | None = None) -> None:
        self.name = name
        self._clock = clock or time.monotonic
        self._condition = threading.Condition()
        self._pending: dict[str, Callable[[], None]] = {}
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._running = False
        # Diagnostics: a replacement means work was superseded before it started, and a rising
        # count is the honest way to say "the loop is asking faster than the worker can answer".
        self.replaced = 0
        self.completed = 0
        self.failed = 0
        self.last_error: str | None = None
        self.last_started_at = 0.0
        self.last_finished_at = 0.0

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._condition:
            self._stopping = False
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._condition:
            self._stopping = True
            self._pending.clear()
            self._condition.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
            if thread.is_alive():
                # A job that will not finish is reported, not hidden: the loop keeps running and
                # the supervisor can see the worker is stuck.
                logger.warning("%s did not stop within %.1f s", self.name, timeout)
        self._thread = None

    # ---- work --------------------------------------------------------------

    def submit(self, key: str, job: Callable[[], None]) -> bool:
        """Queue `job`, replacing anything still pending under `key`. Never blocks on the job."""
        with self._condition:
            if self._stopping:
                return False
            if key in self._pending:
                self.replaced += 1
            self._pending[key] = job
            self._condition.notify_all()
        return True

    @property
    def busy(self) -> bool:
        """True while a job is running or queued."""
        with self._condition:
            return self._running or bool(self._pending)

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait(0.2)
                if self._stopping:
                    return
                key, job = self._pending.popitem()
                self._running = True
                self.last_started_at = self._clock()
            try:
                job()
            except Exception as exc:  # noqa: BLE001 - a worker must never die on one job
                self.failed += 1
                self.last_error = str(exc)
                logger.exception("%s failed a job (%s)", self.name, key)
            else:
                self.completed += 1
            finally:
                with self._condition:
                    self._running = False
                    self.last_finished_at = self._clock()
                    self._condition.notify_all()

    def __repr__(self) -> str:
        return (
            f"LatestJobWorker({self.name!r}, busy={self.busy}, completed={self.completed}, "
            f"replaced={self.replaced}, failed={self.failed})"
        )