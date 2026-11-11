"""Restart policy for the resources that stop working — and the end of "lie down".

`safety/watchdog.py` and `safety/service_watchdog.py` watched the same heartbeats with different
cooldowns, different error handling and no shared idea of what a failure meant. Between them they
produced H-03: `module_names` lists *every* module while only started modules heartbeat, so a
device with the shipped config — where `safety`, `health`, `balance` and `sensor_health` all ship
disabled — had a permanently non-empty stale list, and the watchdog put the dog on its belly every
five seconds.

This module is policy only: no loop, no hardware, no `Module`. Given the status snapshot the
runtime already publishes, it decides which modules have earned a restart, which have earned a
give-up, and why. `safety/watchdog.py` applies the decision.

Two rules matter more than the rest:

- **Only modules that are enabled *and* started are candidates.** A module that is configured off,
  or that disabled itself because the HAL or the camera is missing, is not a failure to recover
  from. Restarting it on a timer is a loop, not a recovery.
- **A module that keeps failing is eventually left failed.** Backoff caps the retries, and the
  runtime stops being asked. A supervisor that retries forever hides the fault it is meant to
  report.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["RestartPolicy", "Supervisor", "SupervisorReport"]


def _number(value: Any, default: float | None = None) -> float | None:
    """Coerce a status field to float. `bool` is not a measurement, NaN is not a timestamp."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    return default if number != number else number


@dataclass(frozen=True)
class RestartPolicy:
    """Backoff and give-up thresholds. Loaded from `settings.watchdog`."""

    base_delay_s: float = 1.0
    factor: float = 2.0
    max_delay_s: float = 60.0
    max_restarts: int = 3
    healthy_after_s: float = 30.0

    def delay_for(self, attempt: int) -> float:
        """Exponential backoff, capped. `attempt` is 1-based."""
        if attempt < 1:
            return 0.0
        return min(self.max_delay_s, self.base_delay_s * (self.factor ** (attempt - 1)))


@dataclass(frozen=True)
class SupervisorReport:
    """What the supervisor decided this tick, and why. Always serialisable for `/health`."""

    restart: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "restart": list(self.restart),
            "failed": list(self.failed),
            "reasons": dict(self.reasons),
        }


@dataclass
class _Record:
    """Per-module memory. The supervisor is stateful on purpose: backoff needs history."""

    restarts: int = 0
    next_attempt_at: float = 0.0
    failed: bool = False
    last_error: str | None = None
    healthy_since: float | None = None


class Supervisor:
    """Turns a status snapshot into "restart these", "give up on these", "not yet"."""

    def __init__(
        self,
        policy: RestartPolicy | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.policy = policy or RestartPolicy()
        self._clock = clock or time.monotonic
        self._records: dict[str, _Record] = {}

    # ---- decisions ---------------------------------------------------------

    def decide(
        self,
        statuses: Mapping[str, Any],
        timeout_s: float,
        now: float | None = None,
        monitor: Mapping[str, Any] | None = None,
    ) -> SupervisorReport:
        """Decide, for one tick, which modules should be restarted.

        `statuses` is `context["module_statuses"]`; `monitor` is the optional allow-list from
        `settings.watchdog.monitor_modules`. An empty or absent allow-list means "every started
        module", which is what an operator expects from a watchdog.
        """
        stamp = self._clock() if now is None else now
        wanted = {str(name) for name in (monitor or ())}
        report = SupervisorReport()

        for name, raw in sorted(statuses.items()):
            if not isinstance(raw, dict):
                continue
            if wanted and str(name) not in wanted:
                continue
            record = self._records.setdefault(str(name), _Record())

            # Off, or gave up on itself during `start` (no HAL, no camera, missing wheel).
            # Neither is a failure to recover, and neither heartbeats — which is exactly why the
            # old watchdog reported every disabled module as stale, forever.
            if not raw.get("enabled", True) or not raw.get("started", False):
                record.healthy_since = None
                continue

            reason = self._reason(raw, record, timeout_s, stamp)

            if record.failed:
                # A module that keeps failing is left alone — but not forever. If it is running
                # again and stays up for a full healthy window, it earns a fresh budget rather
                # than carrying the old verdict into the rest of the session.
                if reason is not None:
                    report.failed.append(str(name))
                    report.reasons[str(name)] = "gave up after repeated failures"
                elif record.healthy_since is None:
                    record.healthy_since = stamp
                elif (stamp - record.healthy_since) >= self.policy.healthy_after_s:
                    record.failed = False
                    record.restarts = 0
                    record.next_attempt_at = 0.0
                    record.healthy_since = stamp
                continue

            if reason is None:
                if record.healthy_since is None:
                    record.healthy_since = stamp
                elif record.restarts and (stamp - record.healthy_since) >= self.policy.healthy_after_s:
                    # It stayed up long enough to be trusted with a fresh budget.
                    record.restarts = 0
                    record.next_attempt_at = 0.0
                continue

            record.healthy_since = None
            if stamp < record.next_attempt_at:
                report.reasons[str(name)] = f"{reason}; backing off"
                continue
            if record.restarts >= self.policy.max_restarts:
                record.failed = True
                report.failed.append(str(name))
                report.reasons[str(name)] = (
                    f"{reason}; gave up after {record.restarts} restart(s)"
                )
                continue
            record.restarts += 1
            record.next_attempt_at = stamp + self.policy.delay_for(record.restarts)
            report.restart.append(str(name))
            report.reasons[str(name)] = reason

        return report

    @staticmethod
    def _reason(
        status: Mapping[str, Any], record: _Record, timeout_s: float, now: float
    ) -> str | None:
        """`"error"`, `"stale"`, or None when the module looks healthy.

        A *new* error is the trigger, not the mere presence of one: `ModuleStatus.last_error` is
        never cleared, so "it errored once an hour ago" would otherwise restart the module until
        the end of time.
        """
        error = status.get("last_error")
        if error and str(error) != record.last_error:
            record.last_error = str(error)
            return "error"
        heartbeat = _number(status.get("last_heartbeat_ts"))
        if heartbeat is None:
            return "never ticked"
        if (now - heartbeat) > timeout_s:
            return "stale heartbeat"
        return None

    # ---- housekeeping ------------------------------------------------------

    def reset(self, names: Any = None) -> None:
        """Forget history, for every module or for a named few."""
        if names is None:
            self._records.clear()
            return
        for name in names:
            self._records.pop(str(name), None)

    def record(self, name: str) -> dict[str, object] | None:
        """A module's supervision state, for diagnostics and tests."""
        found = self._records.get(str(name))
        if found is None:
            return None
        return {
            "restarts": found.restarts,
            "failed": found.failed,
            "last_error": found.last_error,
            "next_attempt_at": found.next_attempt_at,
        }

    @property
    def watched(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))