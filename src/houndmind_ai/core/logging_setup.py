from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


def setup_logging(settings: dict[str, Any]) -> None:
    level_name = str(settings.get("log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    if getattr(root, "_houndmind_configured", False):
        return

    enable_console = bool(settings.get("enable_console", True))
    enable_file = bool(settings.get("enable_file", True))

    if enable_console:
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(console)

    if enable_file:
        log_dir = Path(str(settings.get("log_dir", "logs")))
        if not log_dir.is_absolute():
            log_dir = Path(__file__).resolve().parents[3] / log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        file_path = log_dir / str(settings.get("log_file_name", "houndmind.log"))
        max_mb = int(settings.get("log_file_max_mb", 10))
        backups = int(settings.get("log_file_backups", 5))
        handler = RotatingFileHandler(
            file_path,
            maxBytes=max_mb * 1024 * 1024,
            backupCount=backups,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(handler)

    setattr(root, "_houndmind_configured", True)
