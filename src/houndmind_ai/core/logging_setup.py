import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # include any extra fields attached to the record
        for k, v in record.__dict__.items():
            if k in ("name", "msg", "args", "levelname", "levelno", "pathname", "lineno", "exc_info", "exc_text", "stack_info", "created", "msecs", "relativeCreated", "thread", "threadName", "processName", "process"):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except Exception:
                payload[k] = repr(v)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class ContextFilter(logging.Filter):
    """Inject runtime context into every log record.

    Provide a dict-like `context` with optional keys: `device_id`, `runtime_tick`, `trace_id`, `mission_id`.
    """

    def __init__(self, context: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.context = context or {}

    def set_context(self, context: Dict[str, Any]) -> None:
        self.context = context or {}

    def filter(self, record: logging.LogRecord) -> bool:
        for k, v in self.context.items():
            setattr(record, k, v)
        return True


def setup_logging(config: Optional[Dict[str, Any]] = None) -> ContextFilter:
    """Centralized logging setup.

    Args:
        config: optional dict with keys `log_dir`, `log_file`, `level`, `backup_count`, `console_level`.

    Returns:
        The `ContextFilter` instance attached to the root logger so callers can update runtime fields.
    """

    cfg = config or {}
    log_dir = cfg.get("log_dir", os.path.join(os.getcwd(), "logs"))
    os.makedirs(log_dir, exist_ok=True)
    log_file = cfg.get("log_file", os.path.join(log_dir, "houndmind.log"))
    level_name = (cfg.get("level") or "INFO").upper()
    console_level_name = (cfg.get("console_level") or level_name).upper()
    backup_count = int(cfg.get("backup_count", 7))

    root = logging.getLogger()
    root.setLevel(getattr(logging, level_name, logging.INFO))

    # create the context filter early so we can attach it to handlers directly
    context_filter = ContextFilter(cfg.get("context", {}))

    # Avoid adding duplicate handlers on repeated setup calls
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, "_houndmind_managed", False) for h in root.handlers):
        file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=backup_count)
        file_handler.setLevel(getattr(logging, level_name, logging.INFO))
        file_handler.setFormatter(JsonFormatter())
        # attach context filter directly to handler so formatted records include runtime context
        file_handler.addFilter(context_filter)
        # mark handler so repeated setup_logging calls won't duplicate
        setattr(file_handler, "_houndmind_managed", True)
        root.addHandler(file_handler)

    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_houndmind_console", False) for h in root.handlers):
        console = logging.StreamHandler()
        console.setLevel(getattr(logging, console_level_name, logging.INFO))
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        # attach context filter to console as well for consistency
        console.addFilter(context_filter)
        setattr(console, "_houndmind_console", True)
        root.addHandler(console)

    # keep the filter on the root logger too for any other consumers
    root.addFilter(context_filter)

    return context_filter


__all__ = ["setup_logging", "JsonFormatter", "ContextFilter"]
