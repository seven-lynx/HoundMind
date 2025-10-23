from __future__ import annotations
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any
import json
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", "canine_core")

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extras
        for k, v in record.__dict__.items():
            if k in ("args", "msg", "levelname", "levelno", "pathname", "filename", "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs", "relativeCreated", "thread", "threadName", "processName", "process"):
                continue
            payload[k] = v
        # Ensure subsystem tag
        payload.setdefault("subsystem", "canine_core")
        return json.dumps(payload, ensure_ascii=False)

def setup_logging(level: Optional[str] = None, *, max_mb: Optional[int] = None, backups: Optional[int] = None) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("canine_core")
    if getattr(logger, "_configured", False):
        return

    logger.setLevel(getattr(logging, (level or os.getenv("CANINECORE_LOG_LEVEL", "INFO")).upper(), logging.INFO))

    file_path = os.path.join(LOG_DIR, "core.jsonl")
    max_bytes_mb = max_mb if max_mb is not None else int(os.getenv("CANINECORE_LOG_FILE_MAX_MB", "5") or 5)
    backup_count = backups if backups is not None else int(os.getenv("CANINECORE_LOG_FILE_BACKUPS", "7") or 7)
    file_handler = RotatingFileHandler(file_path, maxBytes=max_bytes_mb * 1024 * 1024, backupCount=backup_count, encoding="utf-8")
    file_handler.setFormatter(JSONFormatter())

    # Minimal console for dev; plain text
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console)
    setattr(logger, "_configured", True)
