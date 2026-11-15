"""The motionless smoke run must not reach the HAL at all (#184).

The guide claimed "nothing can move" while `scanning` was still enabled and sweeping the head through
the HAL, so the claim was never true and nothing tested it. These cases build the tool's own module
list with the sanctioned fake and prove the promise instead of asserting it in prose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.hal.fake import FakeDogHAL
from tools.smoke_test import MOTIONLESS_MODULES, main

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config" / "settings.jsonc"

# No camera, microphone or network listener on a CI runner. `api` stays off for the reason
# `tests/test_runtime_tick.py` keeps it off: it binds a socket.
UNRUNNABLE = (
    "api",
    "vision",
    "vision_pi4",
    "voice",
    "face_recognition",
    "semantic_labeler",
    "slam_pi4",
)


@pytest.fixture
def headless(monkeypatch, tmp_path):
    """Point the tool at the shipped config, minus the modules a runner cannot start."""

    def patched(path):
        config = load_config(REPO_CONFIG)
        for name in UNRUNNABLE:
            entry = (config.modules or {}).get(name)
            if entry is not None and hasattr(entry, "enabled"):
                entry.enabled = False
        logging_settings = config.settings.setdefault("logging", {})
        logging_settings["event_log_file_enabled"] = False
        logging_settings["event_log_path"] = str(tmp_path / "events.jsonl")
        return config

    monkeypatch.setattr("tools.smoke_test.load_config", patched)
    return patched


def run(hal: FakeDogHAL, *extra: str) -> int:
    """Two cycles at 20 Hz: enough for a sensor reading, short enough for a unit test."""
    return main(["--cycles", "2", "--tick-hz", "20", *extra], hal=hal)


def test_the_motionless_run_never_reaches_the_hal(headless, capsys):
    hal = FakeDogHAL()
    hal.set_distance(41.7)

    assert run(hal) == 0

    assert hal.calls == [], f"a motionless run commanded the HAL: {hal.calls}"
    out = capsys.readouterr().out
    assert "[smoke] sensor_reading: OK" in out
    assert "[smoke] scan_latest: SKIPPED (scanning is disabled in the motionless run)" in out
    assert "[smoke] mapping_openings: SKIPPED" in out
    assert "[smoke] disabled:" in out
    assert "[smoke] PASS" in out


def test_scanning_is_in_the_motionless_set():
    """The regression this file exists for: `scanning` moves the head without `hal_motors`."""
    assert "scanning" in MOTIONLESS_MODULES
    assert "hal_motors" in MOTIONLESS_MODULES


def test_no_reading_from_the_hal_fails_the_run(headless, capsys, monkeypatch):
    """The key this mode does verify. An empty module list is the honest way to withhold it.

    A `SensorReading` object appears even when every sensor failed - the validity flags say which
    answered, and step 2 is where they are read - so the tool can only report whether the HAL
    published at all. This case covers the reporting, not the sensor stack.
    """
    monkeypatch.setattr("tools.smoke_test.build_modules", lambda config, hal=None: [])

    assert run(FakeDogHAL()) == 1

    out = capsys.readouterr().out
    assert "[smoke] sensor_reading: MISSING" in out
    assert "[smoke] FAIL" in out
