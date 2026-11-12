from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.commands import Source

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _intent(context, source: Source) -> str | None:
    """What `source` is currently asking for, or None when it has no live intent.

    The snapshot used to read four context keys that the producers wrote when they felt like
    it. Those keys are gone; the board is the one place that knows what every producer wants,
    and it only reports intents that are still being refreshed.
    """
    board = context.get("intent_board")
    if board is None:
        return None
    command = board.find(source)
    return None if command is None else command.action


def _safe_float(value: Any, default: float) -> float:
    """Coerce a config value, treating None/""/junk/NaN as missing."""
    try:
        if value is None or value == "":
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else number


class EventLoggerModule(Module):
    """Lightweight event logger with in-memory ring buffer and optional JSONL file."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._events: list[dict[str, Any]] = []
        self._last_snapshot: dict[str, Any] = {}
        self._last_log_ts = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("logging", {})
        if not settings.get("event_log_enabled", True):
            return

        interval_s = float(settings.get("event_log_interval_s", 0.5))
        now = time.time()
        if now - self._last_log_ts < interval_s:
            return
        self._last_log_ts = now

        snapshot = {
            "behavior_action": _intent(context, Source.BEHAVIOUR),
            "navigation_action": _intent(context, Source.NAVIGATION),
            "place_action": _intent(context, Source.PLACE),
            "navigation_decision": context.get("navigation_decision"),
            "safety_action": _intent(context, Source.SYSTEM),
            "watchdog_action": _intent(context, Source.WATCHDOG),
            "motion_action": (context.get("motion_command") or {}).get("canonical_action"),
            "stuck_recovery": context.get("stuck_recovery"),
            "scan_latest": context.get("scan_latest"),
            "mapping_openings": context.get("mapping_openings"),
            "mapping_hint": context.get("mapping_hint"),
            "health_degraded": context.get("health_degraded"),
            "module_statuses": context.get("module_statuses"),
        }
        if snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot

        event = {
            "type": "snapshot",
            "schema_version": SCHEMA_VERSION,
            "timestamp": now,
            "behavior_action": snapshot["behavior_action"],
            "navigation_action": snapshot["navigation_action"],
            "place_action": snapshot["place_action"],
            "navigation_decision": snapshot["navigation_decision"],
            "safety_action": snapshot["safety_action"],
            "watchdog_action": snapshot["watchdog_action"],
            "motion_action": snapshot["motion_action"],
            "stuck_recovery": snapshot["stuck_recovery"],
            "scan_result": snapshot["scan_latest"],
            "mapping_hint": snapshot["mapping_hint"],
            "health_degraded": snapshot["health_degraded"],
            "module_status_summary": self._summarize_module_statuses(
                snapshot["module_statuses"]
            ),
        }
        self._append_event(event, settings)

    def stop(self, context) -> None:
        settings = (context.get("settings") or {}).get("logging", {})
        report = self._generate_report()
        context.set("event_log_report", report)
        if settings.get("event_log_file_enabled", True):
            self._write_jsonl({"type": "summary", **report}, settings)

    def _append_event(self, event: dict[str, Any], settings: dict[str, Any]) -> None:
        max_entries = int(settings.get("event_log_max_entries", 1000))
        self._events.append(event)
        if len(self._events) > max_entries:
            self._events = self._events[-max_entries:]
        if settings.get("event_log_file_enabled", True):
            self._write_jsonl(event, settings)

    def _write_jsonl(self, event: dict[str, Any], settings: dict[str, Any]) -> None:
        try:
            path = Path(
                str(settings.get("event_log_path", "logs/houndmind_events.jsonl"))
            )
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[3] / path
            path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(path, settings)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write event log: %s", exc)

    @staticmethod
    def _rotate_if_needed(path: Path, settings: dict[str, Any]) -> None:
        """Keep one previous generation so the JSONL cannot grow without bound.

        The in-memory ring buffer was already capped by `event_log_max_entries`, but the file
        was opened in append mode forever: a dog left running filled the SD card (H-04). One
        rotated generation is deliberate — a second copy is enough to answer "what happened
        just before this", and it bounds the disk cost to twice the limit.
        """
        max_bytes = int(_safe_float(settings.get("event_log_max_mb"), 5.0) * 1024 * 1024)
        if max_bytes <= 0 or not path.exists():
            return
        try:
            if path.stat().st_size < max_bytes:
                return
            rotated = path.with_suffix(path.suffix + ".1")
            rotated.unlink(missing_ok=True)
            path.rename(rotated)
            logger.info("Event log rotated at %d bytes: %s", max_bytes, rotated)
        except OSError as exc:
            # A full or read-only filesystem must not take the runtime down with it.
            logger.warning("Event log rotation failed: %s", exc)

    def _generate_report(self) -> dict[str, Any]:
        total = len(self._events)
        stuck_events = sum(1 for e in self._events if e.get("stuck_recovery"))
        safety_events = sum(1 for e in self._events if e.get("safety_action"))
        watchdog_events = sum(1 for e in self._events if e.get("watchdog_action"))
        # Aggregate navigation actions for quick tuning insight.
        nav_action_counts = self._count_actions("navigation_action")
        # Count mapping hint usage (only when present).
        mapping_hint_events = sum(1 for e in self._events if e.get("mapping_hint"))
        return {
            "schema_version": SCHEMA_VERSION,
            "timestamp": time.time(),
            "total_events": total,
            "stuck_events": stuck_events,
            "safety_events": safety_events,
            "watchdog_events": watchdog_events,
            "mapping_hint_events": mapping_hint_events,
            "navigation_action_counts": nav_action_counts,
        }

    def _count_actions(self, key: str) -> dict[str, int]:
        # Count distinct action strings found under the provided key.
        counts: dict[str, int] = {}
        for event in self._events:
            value = event.get(key)
            if not value:
                continue
            name = str(value)
            counts[name] = counts.get(name, 0) + 1
        return counts

    @staticmethod
    def _summarize_module_statuses(statuses: Any) -> dict[str, Any] | None:
        if not isinstance(statuses, dict):
            return None
        enabled = 0
        disabled = 0
        errors: dict[str, str] = {}
        for name, status in statuses.items():
            if not isinstance(status, dict):
                continue
            if status.get("enabled"):
                enabled += 1
            else:
                disabled += 1
            last_error = status.get("last_error")
            if last_error:
                errors[str(name)] = str(last_error)
        return {
            "enabled": enabled,
            "disabled": disabled,
            "errors": errors,
        }
