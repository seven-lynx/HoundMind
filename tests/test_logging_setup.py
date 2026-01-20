import json
import logging
import os
from pathlib import Path

from houndmind_ai.core.logging_setup import setup_logging


def test_setup_logging_creates_handlers_and_injects_context(tmp_path):
    root = logging.getLogger()
    # Backup existing handlers and filters
    orig_handlers = list(root.handlers)
    orig_filters = list(root.filters)

    try:
        # Start from a clean root logger to avoid interfering handlers from other tests
        root.handlers[:] = []
        root.filters[:] = []
        log_dir = tmp_path / "logs"
        cfg = {
            "log_dir": str(log_dir),
            "log_file": str(log_dir / "houndmind_test.log"),
            "level": "DEBUG",
            "console_level": "INFO",
            "backup_count": 1,
            "context": {"device_id": "test-device"},
        }

        context_filter = setup_logging(cfg)

        # Ensure handlers were added
        assert any(getattr(h, "_houndmind_managed", False) for h in root.handlers)
        assert any(getattr(h, "_houndmind_console", False) for h in root.handlers)

        # Emit a log entry and ensure JSON log file contains context fields
        logger = logging.getLogger("test_logging")
        logger.info("hello world")

        # Ensure file exists and contains JSON
        assert log_dir.exists(), "log_dir should be created"
        log_file = Path(cfg["log_file"])
        assert log_file.exists(), "log file should exist after logging"

        content = log_file.read_text(encoding="utf-8")
        # Expect at least one JSON object per line; parse first non-empty line
        first_line = next((l for l in content.splitlines() if l.strip()), None)
        assert first_line is not None
        obj = json.loads(first_line)
        assert obj.get("device_id") == "test-device"
        assert obj.get("message") == "hello world"

        # Update context and ensure subsequent logs reflect change
        context_filter.set_context({"device_id": "new-device", "runtime_tick": 123})
        logger.info("second")
        # Read last non-empty line
        lines = [l for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        last = json.loads(lines[-1])
        assert last.get("device_id") == "new-device"
        assert last.get("runtime_tick") == 123

    finally:
        # Restore handlers and filters
        root.handlers[:] = orig_handlers
        root.filters[:] = orig_filters
