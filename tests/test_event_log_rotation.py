"""The event log is written on a Pi's SD card for months at a time.

The in-memory ring buffer was capped, but the JSONL file was opened in append mode with no
limit at all: a dog left running filled the card, and the failure mode is a boot loop rather
than an error message.
"""

from __future__ import annotations

from pathlib import Path

from houndmind_ai.logging.event_logger import EventLoggerModule


def test_event_log_is_written(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    module = EventLoggerModule("event_log")
    module._write_jsonl({"type": "x"}, {"event_log_path": str(path)})
    assert path.read_text(encoding="utf-8").strip() == '{"type": "x"}'


def test_event_log_rotates_once_at_the_cap(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    settings = {"event_log_path": str(path), "event_log_max_mb": 0.001}  # ~1 KB
    module = EventLoggerModule("event_log")

    for index in range(200):
        module._write_jsonl({"type": "snapshot", "n": index}, settings)
        if (tmp_path / "events.jsonl.1").exists():
            break

    rotated = path.with_suffix(path.suffix + ".1")
    assert rotated.exists(), "the log should have rotated"
    assert path.exists(), "a fresh log should have replaced it"


def test_a_second_rotation_replaces_the_previous_generation(tmp_path: Path) -> None:
    """One generation, not an unbounded chain: disk cost stays bounded at twice the cap."""
    path = tmp_path / "events.jsonl"
    rotated = path.with_suffix(path.suffix + ".1")
    rotated.write_text("old\n", encoding="utf-8")
    path.write_text("x" * 2048, encoding="utf-8")

    EventLoggerModule._rotate_if_needed(path, {"event_log_max_mb": 0.001})
    assert rotated.read_text(encoding="utf-8") == "x" * 2048


def test_rotation_is_a_no_op_below_the_cap(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("small\n", encoding="utf-8")
    EventLoggerModule._rotate_if_needed(path, {"event_log_max_mb": 5})
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".1").exists()


def test_rotation_survives_a_missing_file(tmp_path: Path) -> None:
    EventLoggerModule._rotate_if_needed(tmp_path / "absent.jsonl", {"event_log_max_mb": 5})


def test_zero_cap_disables_rotation(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("x" * 2048, encoding="utf-8")
    EventLoggerModule._rotate_if_needed(path, {"event_log_max_mb": 0})
    assert not path.with_suffix(path.suffix + ".1").exists()