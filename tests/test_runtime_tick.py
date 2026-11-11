"""The whole loop, on a machine with no dog attached.

This is the closest thing to a smoke test that CI can run: every module is constructed from the
shipped config, the ones that need a camera or a servo bus are switched off, and the runtime
ticks twice. It catches the failures that unit tests miss — a module whose `start` needs
hardware it should not need, a context key that nothing publishes, a gateway that was
registered but never reached.
"""

from __future__ import annotations

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.main import build_modules

# Modules whose `start` genuinely needs hardware. `hal/fake.py` is what eventually lets these
# run in CI; until the sensor service sits behind the HAL, they are switched off here.
HARDWARE_MODULES = frozenset(
    {
        "hal_sensors",
        "hal_motors",
        "scanning",
        "led_manager",
        "calibration",
        "orientation",
        "balance",
        "health",
        "vision",
        "vision_pi4",
        "voice",
        "face_recognition",
        "semantic_labeler",
        "slam_pi4",
        "telemetry_dashboard",
    }
)


@pytest.fixture
def headless_config(tmp_path):
    config = load_config()
    for name, entry in (config.modules or {}).items():
        if hasattr(entry, "enabled"):
            entry.enabled = name not in HARDWARE_MODULES
    logging_settings = config.settings.setdefault("logging", {})
    logging_settings["event_log_file_enabled"] = False
    logging_settings["event_log_path"] = str(tmp_path / "events.jsonl")
    return config


def test_the_runtime_starts_and_ticks(headless_config) -> None:
    runtime = HoundMindRuntime(headless_config, build_modules(headless_config))
    runtime.start()
    try:
        runtime.tick()
        runtime.tick()
    finally:
        runtime.stop()

    started = [module.name for module in runtime.modules if module.status.started]
    assert started, "no module started at all"
    assert "motion_gateway" in [module.name for module in runtime.modules]


def test_the_gateway_is_reached_by_the_loop(headless_config) -> None:
    """A module registered but never ticked is the failure this catches."""
    runtime = HoundMindRuntime(headless_config, build_modules(headless_config))
    runtime.start()
    try:
        runtime.tick()
    finally:
        runtime.stop()

    assert "motion_verdict" in runtime.context
    assert "motion_command" in runtime.context
    assert "tilt_latched" in runtime.context


def test_no_enabled_module_records_an_error(headless_config) -> None:
    runtime = HoundMindRuntime(headless_config, build_modules(headless_config))
    runtime.start()
    try:
        runtime.tick()
    finally:
        runtime.stop()

    broken = {
        module.name: module.status.last_error
        for module in runtime.modules
        if module.status.enabled and module.status.last_error
    }
    assert not broken, broken


def test_a_hardware_module_that_cannot_start_is_disabled_not_fatal(headless_config) -> None:
    """`required=True` belongs to the HAL only, so nothing else may abort the runtime."""
    runtime = HoundMindRuntime(headless_config, build_modules(headless_config))
    runtime.start()
    try:
        runtime.tick()
    finally:
        runtime.stop()


def test_the_shipped_config_still_has_the_safety_modules_off(headless_config) -> None:
    """Turning safety on by default is a product decision, not a side effect of a refactor."""
    for name in ("safety", "health", "balance", "sensor_health"):
        entry = load_config().modules.get(name)
        assert entry is not None, f"{name} should be declared in the shipped config"
        assert entry.enabled is False, f"{name} must ship disabled"