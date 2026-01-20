import logging
import os

from houndmind_ai.core.logging_setup import setup_logging


def test_setup_logging_respects_config(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "test_override.log")

    cfg = {
        "log_dir": log_dir,
        "log_file": log_file,
        "backup_count": 3,
        "level": "WARNING",
        "console_level": "DEBUG",
        "context": {"device_id": "cfg-test"},
    }

    filt = setup_logging(cfg)

    root = logging.getLogger()
    # root level should reflect `level`
    assert root.level == logging.WARNING

    # Rotating file handler should be present and have the configured backupCount
    file_h = next((h for h in root.handlers if getattr(h, "_houndmind_managed", False)), None)
    assert file_h is not None, "Expected a managed RotatingFileHandler"
    assert getattr(file_h, "backupCount", None) == 3

    # Console handler should be present and set to DEBUG
    console_h = next((h for h in root.handlers if getattr(h, "_houndmind_console", False)), None)
    assert console_h is not None, "Expected a managed console StreamHandler"
    assert console_h.level == logging.DEBUG

    # cleanup handlers so other tests are unaffected
    for h in list(root.handlers):
        try:
            root.removeHandler(h)
            h.close()
        except Exception:
            pass
