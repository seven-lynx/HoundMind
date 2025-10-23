from __future__ import annotations
from dataclasses import dataclass
import logging
from ...utils.logging_setup import setup_logging


@dataclass
class LoggingService:
    prefix: str = "CanineCore"

    def __post_init__(self) -> None:
        # Idempotent init
        setup_logging()
        self._logger = logging.getLogger("canine_core")

    def info(self, msg: str, **extra: object) -> None:
        self._logger.info(str(msg), extra={"component": self.prefix, **extra, "subsystem": "canine_core"})

    def warning(self, msg: str, **extra: object) -> None:
        self._logger.warning(str(msg), extra={"component": self.prefix, **extra, "subsystem": "canine_core"})

    def error(self, msg: str, **extra: object) -> None:
        self._logger.error(str(msg), extra={"component": self.prefix, **extra, "subsystem": "canine_core"})
