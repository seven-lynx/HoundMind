"""The registry exists so "which module does this?" is answerable and testable.

`main.build_modules` was a list, and the only way to find the actuator was a magic context key
holding a vendor object. Both an unwired module (`SensorHealthModule`) and a dead capability
(`wifi_localization`) went unnoticed for that reason.
"""

from __future__ import annotations

import pytest

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.registry import Capability, ModuleRegistry, RegistryError


def test_register_and_lookup() -> None:
    registry = ModuleRegistry()
    motor = Module("hal_motors")
    registry.register(motor, [Capability.MOTION])
    assert registry.get("hal_motors") is motor
    assert registry.require("hal_motors") is motor
    assert "hal_motors" in registry
    assert len(registry) == 1


def test_duplicate_name_is_rejected() -> None:
    registry = ModuleRegistry()
    registry.register(Module("motion_gateway"))
    with pytest.raises(RegistryError, match="already registered"):
        registry.register(Module("motion_gateway"))


def test_require_unknown_name_raises() -> None:
    with pytest.raises(RegistryError, match="no module named"):
        ModuleRegistry().require("ghost")


def test_capability_resolves_to_the_provider() -> None:
    registry = ModuleRegistry()
    motor = Module("hal_motors")
    registry.register(motor, [Capability.MOTION])
    assert registry.provider(Capability.MOTION) is motor


def test_absent_capability_has_no_provider() -> None:
    assert ModuleRegistry().provider(Capability.VISION) is None


def test_two_providers_for_one_capability_is_an_error() -> None:
    """Two modules owning the servo bus is a configuration bug, not a preference."""
    registry = ModuleRegistry()
    registry.register(Module("motor_a"), [Capability.MOTION])
    registry.register(Module("motor_b"), [Capability.MOTION])
    with pytest.raises(RegistryError, match="2 providers"):
        registry.provider(Capability.MOTION)


def test_with_capability_returns_all_in_registration_order() -> None:
    registry = ModuleRegistry()
    first = Module("safety")
    second = Module("balance")
    registry.register(first, [Capability.SAFETY])
    registry.register(second, [Capability.SAFETY])
    assert registry.with_capability(Capability.SAFETY) == [first, second]


def test_modules_are_kept_in_registration_order() -> None:
    registry = ModuleRegistry()
    names = ["hal_sensors", "motion_gateway", "hal_motors"]
    for name in names:
        registry.register(Module(name))
    assert [module.name for module in registry.modules()] == names


def test_duplicate_capabilities_are_collapsed() -> None:
    registry = ModuleRegistry()
    registry.register(Module("telemetry"), [Capability.TELEMETRY, Capability.TELEMETRY])
    assert registry.capabilities_of("telemetry") == (Capability.TELEMETRY,)
    assert len(registry.with_capability(Capability.TELEMETRY)) == 1


def test_unregistered_module_has_no_capabilities() -> None:
    assert ModuleRegistry().capabilities_of("ghost") == ()