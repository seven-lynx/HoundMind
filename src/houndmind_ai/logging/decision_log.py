"""The decision feed: the last few seconds of decisions, plus an optional JSONL mirror.

`logging/event_logger.py` already writes a JSONL, and this is deliberately not that module. It
samples at `event_log_interval_s` (0.5 s) and returns immediately when `event_log_enabled` is
false, so it cannot answer "what did the dog decide on tick N" — at 10 Hz it sees one tick in
five, and on a device that turned the event log off it sees none. The decision feed is a UI
surface: `/decisions` and the `decision` socket event read this ring, so it has its own flag, its
own cadence (every loop tick) and its own file.

Three rules:

1. **One append per record, not per timestamp.** A `ts` can repeat when the clock is coarse or a
   test froze it, and two ticks would then collapse into one row. The gateway builds a fresh
   frozen `DecisionRecord` per tick (`act/gateway.py` has the single publish site), so identity is
   exact where a float is not: the ring appends when the object is new. Clients still diff on
   `ts` — that rule is about the wire, not about this module.
2. **The ring outlives the file.** `decision_log_file_enabled` defaults to `false`: a ~250-byte
   record ten times a second is ~9 MB an hour, and a dog left running would rewrite its own SD
   card. The ring is what the control plane reads; the file is a post-mortem tool, switched on
   deliberately.
3. **A failed write is a warning, not a crash.** The ring is already correct in memory, so a full
   or read-only filesystem costs the file, never the runtime.

The JSONL rotation rule (one generation, capped by `decision_log_max_mb`) is copied from
`EventLoggerModule._rotate_if_needed` on purpose: the two modules own different config keys, and
sharing the helper would mean editing the event logger and its rotation tests. When a third writer
appears, extract it then.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.hal.iface import as_int
from houndmind_ai.kernel.decisions import (
    DEFAULT_MAX_ENTRIES,
    DecisionRecord,
    DecisionRing,
)

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_MAX_MB", "DEFAULT_PATH", "DecisionLogModule"]

DEFAULT_PATH = "logs/houndmind_decisions.jsonl"
DEFAULT_MAX_MB = 5.0


def _safe_float(value: Any, default: float) -> float:
    """Coerce a config value, treating None/""/junk/NaN as missing."""
    try:
        if value is None or value == "":
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else number


class DecisionLogModule(Module):
    """Keep the recent decisions in a bounded ring, and mirror them to JSONL when asked."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._ring: DecisionRing | None = None
        self._last_record: DecisionRecord | None = None
        self._warned_type: type | None = None

    def start(self, context) -> None:
        super().start(context)
        # Allocate from config once, at start: the size is a setting, and a ring that resized
        # itself mid-run would drop records silently.
        self._ensure_ring(self._settings(context))

    def tick(self, context) -> None:
        settings = self._settings(context)
        ring = self._ensure_ring(settings)
        # Published before the flag is read: "no decisions yet" and "no feed at all" are
        # different answers, and `/decisions` has to be able to tell them apart.
        context.set("decision_ring", ring)

        if not settings.get("decision_log_enabled", True):
            return

        record = context.get("decision_record")
        if record is None or record is self._last_record:
            return
        if not isinstance(record, DecisionRecord):
            # The gateway is the only writer, so this is a bug above this module. Warn once per
            # offending type rather than ten times a second, and keep the ring typed.
            if type(record) is not self._warned_type:
                self._warned_type = type(record)
                logger.warning("Ignoring decision_record of type %s", type(record).__name__)
            return

        self._last_record = record
        ring.append(record)
        if settings.get("decision_log_file_enabled", False):
            self._write_jsonl(record.to_dict(), settings)

    @staticmethod
    def _settings(context) -> dict[str, Any]:
        return (context.get("settings") or {}).get("logging", {})

    def _ensure_ring(self, settings: dict[str, Any]) -> DecisionRing:
        """Build the ring once, from the configured size. One construction site."""
        if self._ring is None:
            self._ring = DecisionRing(
                as_int(settings.get("decision_log_max_entries"), DEFAULT_MAX_ENTRIES)
            )
        return self._ring

    def _write_jsonl(self, record: dict[str, Any], settings: dict[str, Any]) -> None:
        try:
            path = Path(str(settings.get("decision_log_path", DEFAULT_PATH)))
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[3] / path
            path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(path, settings)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "decision", **record}) + "\n")
        except Exception as exc:  # noqa: BLE001
            # A full or read-only filesystem must not take the runtime down with it.
            logger.warning("Failed to write decision log: %s", exc)

    @staticmethod
    def _rotate_if_needed(path: Path, settings: dict[str, Any]) -> None:
        """Keep one previous generation, so a dog left running cannot fill the SD card.

        Same rule as the event log (H-04): at `decision_log_max_mb` the file becomes `.1` and a
        fresh one is started, which bounds the disk cost at twice the cap. A second copy is
        enough to answer "what happened just before this".
        """
        max_mb = _safe_float(settings.get("decision_log_max_mb"), DEFAULT_MAX_MB)
        max_bytes = int(max_mb * 1024 * 1024)
        if max_bytes <= 0 or not path.exists():
            return
        try:
            if path.stat().st_size < max_bytes:
                return
            rotated = path.with_suffix(path.suffix + ".1")
            rotated.unlink(missing_ok=True)
            path.rename(rotated)
            logger.info("Decision log rotated at %d bytes: %s", max_bytes, rotated)
        except OSError as exc:
            logger.warning("Decision log rotation failed: %s", exc)
