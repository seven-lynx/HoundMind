"""The whole loop, on a machine with no dog attached.

Every module is constructed from the shipped config and the runtime ticks on a `FakeDogHAL`.
There is no `HARDWARE_MODULES` exclusion list any more: the sensor, scan, LED, head and posture
paths all go through the HAL, so the fake is enough. What is still switched off is the modules
that need something the fake cannot provide — a camera, a microphone, a network listener or an
optional wheel — and that list is about *hardware*, not about the refactor.

This is the closest thing to a smoke test CI can run: it catches a module whose `start` needs
hardware it should not need, a context key nobody publishes, and a gateway that was registered
but never reached.
"""

from __future__ import annotations

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.core.module import Module
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.main import build_modules

# Camera, microphone, network listeners and optional wheels: the fake HAL says nothing about
# these, so they stay off in CI. `api` is here because it *binds a socket*: binding 0.0.0.0 in a
# test would put a listening port on a CI runner. It has its own tests, on loopback only.
OPTIONAL_MODULES = frozenset(
    {
        "api",
        "vision",
        "vision_pi4",
        "voice",
        "face_recognition",
        "semantic_labeler",
        "slam_pi4",
    }
)


@pytest.fixture
def headless(tmp_path):
    """A config plus the fake dog the runtime will use."""
    config = load_config()
    for name, entry in (config.modules or {}).items():
        if hasattr(entry, "enabled"):
            entry.enabled = name not in OPTIONAL_MODULES
    logging_settings = config.settings.setdefault("logging", {})
    logging_settings["event_log_file_enabled"] = False
    logging_settings["event_log_path"] = str(tmp_path / "events.jsonl")
    # The continuous scan runs on its own thread with fixed settle times; a runtime test wants
    # the loop, not a three-second sweep. The scan path itself is covered in test_hal_wiring.
    config.settings.setdefault("navigation", {})["scan_continuous"] = False
    return config, FakeDogHAL()


@pytest.fixture
def runtime(headless):
    config, hal = headless
    instance = HoundMindRuntime(config, build_modules(config, hal=hal))
    instance.start()
    try:
        instance.tick()
        yield instance, hal
    finally:
        instance.stop()


def test_the_runtime_starts_and_ticks(runtime) -> None:
    instance, _ = runtime
    started = [module.name for module in instance.modules if module.status.started]
    assert started, "no module started at all"
    assert "hal" in started
    assert "hal_sensors" in started
    assert "hal_motors" in started, "the fake dog is enough for the motors to start"


def test_the_gateway_is_reached_by_the_loop(runtime) -> None:
    """A module registered but never ticked is the failure this catches."""
    instance, _ = runtime
    assert "motion_verdict" in instance.context
    assert "motion_command" in instance.context
    assert "tilt_latched" in instance.context


def test_the_fake_dog_publishes_sensor_readings(headless) -> None:
    config, hal = headless
    hal.set_distance(150.0)
    hal.set_touch("L")
    hal.set_gyro((0.0, 0.0, 1.0))
    hal.set_acc((0.0, 0.0, 1.0))

    instance = HoundMindRuntime(config, build_modules(config, hal=hal))
    instance.start()
    try:
        instance.tick()
        instance.tick()
        reading = instance.context.get("sensor_reading")
        assert reading is not None, "the sensor module should have published a reading"
        assert reading.distance_valid is True
        assert reading.touch == "L"
        assert instance.context.get("sensors")["distance"] == 150.0
    finally:
        instance.stop()


def test_no_enabled_module_records_an_error(runtime) -> None:
    instance, _ = runtime
    broken = {
        module.name: module.status.last_error
        for module in instance.modules
        if module.status.enabled and module.status.last_error
    }
    assert not broken, broken


def test_a_module_with_no_hal_is_disabled_not_fatal() -> None:
    """`required=True` belongs to the pieces that cannot work at all, so nothing here may abort."""
    config = load_config()
    # The control plane would bind a port; this test is about the missing dog.
    config.modules["api"].enabled = False
    instance = HoundMindRuntime(config, build_modules(config, hal=None))
    try:
        instance.start()
        # HalModule is the one that discovers the missing dog; nobody else may crash on it.
        reason = {
            module.name: module.status.disabled_reason for module in instance.modules
        }
        assert reason.get("hal") is not None
    finally:
        instance.stop()


def test_a_module_that_disables_itself_in_start_is_not_ticked() -> None:
    """`disable(reason)` inside `start` must leave the module out of the loop, not half in it."""

    class GivesUp(Module):
        def __init__(self) -> None:
            super().__init__("gives_up")
            self.ticks = 0

        def start(self, context) -> None:
            self.disable("no hardware")

        def tick(self, context) -> None:
            self.ticks += 1

    config = load_config()
    module = GivesUp()
    instance = HoundMindRuntime(config, [module])
    instance.start()
    try:
        instance.tick()
    finally:
        instance.stop()

    assert module.status.disabled_reason == "no hardware"
    assert module.status.started is False
    assert module.ticks == 0
    statuses = instance.context.get("module_statuses")
    assert statuses["gives_up"]["enabled"] is False
    assert statuses["gives_up"]["started"] is False


def test_the_shipped_config_still_has_the_safety_modules_off() -> None:
    """Turning safety on by default is a product decision, not a side effect of a refactor."""
    for name in ("safety", "health", "balance", "sensor_health"):
        entry = load_config().modules.get(name)
        assert entry is not None, f"{name} should be declared in the shipped config"
        assert entry.enabled is False, f"{name} must ship disabled"