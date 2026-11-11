"""Logging must be cheap, bounded, and configured by the keys the config actually ships.

Two distinct problems are pinned here:

- `ContextFilter` copied *every* runtime context key onto every record, then `JsonFormatter`
  ran `json.dumps` over each one. On a Pi that put the whole config, the sensor history and the
  vendor hardware handle into the log path on every line.
- `setup_logging` read `log_file`/`level`/`backup_count` while `config/settings.jsonc` ships
  `log_file_name`/`log_level`/`log_file_backups`, so the configured DEBUG level was ignored and
  rotation was always 10 MB.
"""

from __future__ import annotations

import json
import logging

import pytest

from houndmind_ai.core.logging_setup import CONTEXT_FIELDS, ContextFilter, setup_logging


@pytest.fixture
def clean_root():
    root = logging.getLogger()
    handlers = list(root.handlers)
    filters = list(root.filters)
    root.handlers[:] = []
    root.filters[:] = []
    try:
        yield root
    finally:
        for handler in root.handlers:
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass
        root.handlers[:] = handlers
        root.filters[:] = filters


def test_only_whitelisted_fields_reach_a_record() -> None:
    context = {
        "device_id": "dev-1",
        "trace_id": "trace-1",
        "runtime_tick": 5,
        "settings": {"navigation": {"huge": "section"}},
        "sensor_history": [{"distance": 1.0}] * 500,
        "pidog": object(),
    }
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hi", None, None)
    ContextFilter(context).filter(record)

    assert record.device_id == "dev-1"
    assert record.runtime_tick == 5
    # The expensive and unsafe ones must not be attached at all.
    assert not hasattr(record, "settings")
    assert not hasattr(record, "sensor_history")
    assert not hasattr(record, "pidog")


def test_whitelist_is_the_documented_set() -> None:
    assert CONTEXT_FIELDS == ("device_id", "trace_id", "runtime_tick", "tick_ts")


def test_a_failing_source_does_not_break_logging() -> None:
    """A logging filter that raises takes the caller down with it."""

    def source(key: str):
        raise RuntimeError("boom")

    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hi", None, None)
    assert ContextFilter(source=source).filter(record) is True


def test_a_live_source_is_read_per_record() -> None:
    values = {"device_id": "first"}
    context_filter = ContextFilter(source=values.get)
    first = logging.LogRecord("t", logging.INFO, __file__, 1, "a", None, None)
    context_filter.filter(first)
    values["device_id"] = "second"
    second = logging.LogRecord("t", logging.INFO, __file__, 1, "b", None, None)
    context_filter.filter(second)
    assert first.device_id == "first"
    assert second.device_id == "second"


def test_shipped_key_names_configure_the_level(clean_root, tmp_path) -> None:
    """`log_level` is what settings.jsonc ships; `level` was the name the code wanted."""
    setup_logging({"log_dir": str(tmp_path), "log_level": "WARNING"})
    assert clean_root.level == logging.WARNING


def test_console_can_be_disabled(clean_root, tmp_path) -> None:
    setup_logging({"log_dir": str(tmp_path), "enable_console": False})
    assert not any(getattr(h, "_houndmind_console", False) for h in clean_root.handlers)


def test_file_rotation_uses_the_configured_size(clean_root, tmp_path) -> None:
    setup_logging(
        {
            "log_dir": str(tmp_path),
            "log_file_name": "hm.log",
            "log_file_max_mb": 2,
            "log_file_backups": 4,
        }
    )
    handler = next(h for h in clean_root.handlers if getattr(h, "_houndmind_managed", False))
    assert handler.maxBytes == 2 * 1024 * 1024
    assert handler.backupCount == 4


def test_file_name_is_relative_to_the_log_dir(clean_root, tmp_path) -> None:
    setup_logging({"log_dir": str(tmp_path), "log_file_name": "hm.log"})
    handler = next(h for h in clean_root.handlers if getattr(h, "_houndmind_managed", False))
    assert str(tmp_path) in handler.baseFilename
    assert handler.baseFilename.endswith("hm.log")


def test_json_payload_carries_no_catch_all_fields(clean_root, tmp_path) -> None:
    context_filter = setup_logging({"log_dir": str(tmp_path), "log_file_name": "hm.log"})
    context_filter.set_context({"device_id": "dev-9", "unrelated": "secret"})
    logging.getLogger("tests.whitelist").warning("line")

    for handler in clean_root.handlers:
        handler.flush()
    text = (tmp_path / "hm.log").read_text(encoding="utf-8")
    payload = json.loads(next(line for line in text.splitlines() if line.strip()))
    assert payload["device_id"] == "dev-9"
    assert "unrelated" not in payload
    assert payload["message"] == "line"