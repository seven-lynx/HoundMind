import json
import logging
import os
import shutil
import tempfile

from houndmind_ai.core.logging_setup import setup_logging


def test_logging_injects_required_fields(tmp_path):
    # Prepare a temporary directory for log output
    log_dir = str(tmp_path / "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "test_houndmind.log")

    # Setup logging with a known context
    ctx = {"device_id": "dev-42", "runtime_tick": 7, "trace_id": "trace-xyz"}
    filter_inst = setup_logging({"log_dir": log_dir, "log_file": log_file, "context": ctx, "level": "INFO"})

    # Emit a test log record
    logger = logging.getLogger("tests.logging_required_fields")
    logger.info("hello-world-test")

    # Ensure handler flushed by closing handlers attached by setup_logging
    for h in logging.getLogger().handlers:
        try:
            h.flush()
            h.close()
        except Exception:
            pass

    # Read the written log file and assert JSON contains our context fields
    assert os.path.exists(log_file), f"expected log file at {log_file}"
    with open(log_file, "r", encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    assert lines, "log file was empty"

    payload = json.loads(lines[-1])
    assert payload.get("device_id") == "dev-42"
    assert payload.get("runtime_tick") == 7
    assert payload.get("trace_id") == "trace-xyz"
    assert payload.get("message") == "hello-world-test"
