from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import logging
from ...utils.logging_setup import setup_logging


@dataclass
class LoggingService:
    prefix: str = "CanineCore"
    config: Optional[object] = None

    def __post_init__(self) -> None:
        # Idempotent init; prefer config-driven settings when provided
        level = None
        max_mb = None
        backups = None
        if self.config is not None:
            try:
                level = getattr(self.config, "LOG_LEVEL", None)
                max_mb = getattr(self.config, "LOG_FILE_MAX_MB", None)
                backups = getattr(self.config, "LOG_FILE_BACKUPS", None)
            except Exception:
                level = None; max_mb = None; backups = None
        setup_logging(level=level, max_mb=max_mb, backups=backups)
        self._logger = logging.getLogger("canine_core")

    def info(self, msg: str, **extra: object) -> None:
        self._logger.info(str(msg), extra={"component": self.prefix, **extra, "subsystem": "canine_core"})

    def warning(self, msg: str, **extra: object) -> None:
        self._logger.warning(str(msg), extra={"component": self.prefix, **extra, "subsystem": "canine_core"})

    def error(self, msg: str, **extra: object) -> None:
        self._logger.error(str(msg), extra={"component": self.prefix, **extra, "subsystem": "canine_core"})
