"""A registry that answers "who provides this capability?" instead of "is this string set?".

`main.build_modules` was a 27-entry list, and everything downstream found its collaborators by
reading magic keys out of the shared context dict. The consequences were real:

- A module could be listed and never actually receive its siblings (`SensorHealthModule` and
  `WifiLocalizationModule` were not listed at all and nobody noticed).
- The actuator was reachable only as `context["pidog"]`, a vendor object, so no consumer above
  the HAL could be tested without one.
- Nothing could assert that exactly one module provides motion.

The registry makes ownership explicit and checkable. It is not a plugin system: the module
list stays compiled in (one runtime, one entry point), but registration is a typed act with a
capability label, and asking for a capability returns modules rather than a guess.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from houndmind_ai.core.module import Module

__all__ = ["Capability", "ModuleRegistry", "RegistryError"]


class RegistryError(RuntimeError):
    """Raised for a duplicate name or a capability with no provider."""


class Capability(StrEnum):
    """What a module can do for the rest of the runtime.

    A capability names what a module *produces*, not what it consumes: `perception` reads the
    sensor bus and publishes fused state, so it provides PERCEPTION, not SENSORS. That
    distinction is what lets `provider()` assert that exactly one module owns the servo bus.
    """

    SENSORS = "sensors"
    PERCEPTION = "perception"
    MOTION = "motion"
    BEHAVIOUR = "behaviour"
    NAVIGATION = "navigation"
    SAFETY = "safety"
    VISION = "vision"
    AUDIO = "audio"
    MAPPING = "mapping"
    TELEMETRY = "telemetry"
    DIAGNOSTICS = "diagnostics"
    CALIBRATION = "calibration"


class ModuleRegistry:
    """Name → module, plus capability → modules. Registration order is tick order."""

    def __init__(self) -> None:
        self._by_name: dict[str, Module] = {}
        self._by_capability: dict[Capability, list[str]] = {}
        self._caps_of: dict[str, tuple[Capability, ...]] = {}

    # ---- registration ------------------------------------------------------

    def register(self, module: Module, capabilities: Sequence[Capability] = ()) -> Module:
        if module.name in self._by_name:
            raise RegistryError(f"module name '{module.name}' is already registered")
        self._by_name[module.name] = module
        declared = tuple(dict.fromkeys(capabilities))  # de-duplicate, keep order
        self._caps_of[module.name] = declared
        for capability in declared:
            self._by_capability.setdefault(capability, []).append(module.name)
        return module

    # ---- lookup ------------------------------------------------------------

    def get(self, name: str) -> Module | None:
        return self._by_name.get(name)

    def require(self, name: str) -> Module:
        module = self._by_name.get(name)
        if module is None:
            raise RegistryError(f"no module named '{name}' is registered")
        return module

    def with_capability(self, capability: Capability) -> list[Module]:
        return [self._by_name[name] for name in self._by_capability.get(capability, ())]

    def provider(self, capability: Capability) -> Module | None:
        """The single module providing `capability`, or None when none is registered."""
        found = self.with_capability(capability)
        if not found:
            return None
        if len(found) > 1:
            names = ", ".join(module.name for module in found)
            raise RegistryError(f"capability '{capability}' has {len(found)} providers: {names}")
        return found[0]

    def capabilities_of(self, name: str) -> tuple[Capability, ...]:
        return self._caps_of.get(name, ())

    # ---- iteration ---------------------------------------------------------

    def modules(self) -> list[Module]:
        """Modules in registration order, which is tick order."""
        return list(self._by_name.values())

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __iter__(self) -> Iterator[Module]:
        return iter(self._by_name.values())

    def __repr__(self) -> str:
        return f"ModuleRegistry({len(self)} modules, {len(self._by_capability)} capabilities)"