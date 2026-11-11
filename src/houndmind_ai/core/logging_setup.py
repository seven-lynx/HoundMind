import json
import logging
import logging.handlers
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# The only context keys that reach a log record.
#
# This was previously every key in the runtime context, which meant each record carried the
# whole `Config`, the sensor history and the `pidog` handle, and `JsonFormatter` then ran
# `json.dumps` over each one. On a Pi that is the loop's entire budget spent in the log path,
# and it wrote the hardware object into the log file (H-04).
CONTEXT_FIELDS: tuple[str, ...] = ("device_id", "trace_id", "runtime_tick", "tick_ts")


def _safe_float(value: Any, default: float) -> float:
    """Coerce a config value, treating None/""/junk/NaN as missing."""
    try:
        if value is None or value == "":
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return number


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with a bounded field set."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Only the whitelisted context fields survive; anything else attached to the record
        # is dropped rather than serialised.
        for name in CONTEXT_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class ContextFilter(logging.Filter):
    """Attach a small, fixed set of runtime fields to every log record.

    `context` may be a plain dict (tests, one-off setups) or a callable that is asked for a
    field on demand. The callable form is what `main` uses: it reads through the context's
    lock, so a log line emitted from a background thread cannot race the loop and the values
    are always the ones current at the moment the record is formatted.
    """

    def __init__(
        self,
        context: dict[str, Any] | None = None,
        source: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__()
        self.context: dict[str, Any] = context or {}
        self.source = source

    def set_context(self, context: dict[str, Any]) -> None:
        self.context = context or {}
        self.source = None

    def set_context_source(self, source: Callable[[str], Any] | None) -> None:
        """Read fields from a live source, e.g. `runtime.context.get`."""
        self.source = source

    def filter(self, record: logging.LogRecord) -> bool:
        for name in CONTEXT_FIELDS:
            try:
                value = self.source(name) if self.source is not None else self.context.get(name)
            except Exception:  # noqa: BLE001 - logging must never raise
                value = None
            if value is not None:
                setattr(record, name, value)
        return True


class _ManagedFileHandler(logging.handlers.RotatingFileHandler):
    """Marker subclass so repeated `setup_logging` calls cannot duplicate handlers."""

    _houndmind_managed = True


class _ManagedConsoleHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Marker subclass, as above, for the console."""

    _houndmind_console = True


def setup_logging(config: dict[str, Any] | None = None) -> ContextFilter:
    """Configure root logging and return the filter that injects runtime context.

    Accepts the keys `config/settings.jsonc` actually ships, and still accepts the older
    names so existing callers and tests keep working:

    ``log_dir`` · ``log_file_name`` (or ``log_file``) · ``log_level`` (or ``level``) ·
    ``console_level`` · ``log_file_max_mb`` · ``log_file_backups`` (or ``backup_count``) ·
    ``enable_file`` · ``enable_console`` · ``context``

    Before this, the file read `log_file`/`level`/`backup_count` while the shipped config
    used `log_file_name`/`log_level`/`log_file_backups`, so the configured DEBUG level was
    silently ignored and rotation was always 10 MB (H-04).
    """
    cfg = config or {}
    log_dir = cfg.get("log_dir") or os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = cfg.get("log_file_name") or cfg.get("log_file") or os.path.join(
        log_dir, "houndmind.log"
    )
    if not os.path.isabs(log_file):
        log_file = os.path.join(log_dir, log_file)
    level_name = str(cfg.get("log_level") or cfg.get("level") or "INFO").upper()
    console_level_name = str(cfg.get("console_level") or level_name).upper()
    backup_count = int(cfg.get("log_file_backups") or cfg.get("backup_count") or 7)
    max_bytes = int(_safe_float(cfg.get("log_file_max_mb"), 10.0) * 1024 * 1024)
    enable_file = bool(cfg.get("enable_file", True))
    enable_console = bool(cfg.get("enable_console", True))

    level = getattr(logging, level_name, logging.INFO)
    console_level = getattr(logging, console_level_name, level)

    root = logging.getLogger()
    root.setLevel(level)

    context_filter = ContextFilter(cfg.get("context", {}))

    # Avoid adding duplicate handlers on repeated setup calls.
    if enable_file and not any(isinstance(h, _ManagedFileHandler) for h in root.handlers):
        file_handler = _ManagedFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        file_handler.setLevel(level)
        file_handler.setFormatter(JsonFormatter())
        # Attach the filter to the handler so formatted records include runtime context.
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)

    if enable_console and not any(isinstance(h, _ManagedConsoleHandler) for h in root.handlers):
        console = _ManagedConsoleHandler()
        console.setLevel(console_level)
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        console.addFilter(context_filter)
        root.addHandler(console)

    # Keep the filter on the root logger too, for any other consumer.
    root.addFilter(context_filter)

    return context_filter


__all__ = ["CONTEXT_FIELDS", "ContextFilter", "JsonFormatter", "setup_logging"]
