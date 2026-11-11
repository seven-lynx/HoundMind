"""The module that owns the dog.

Before this, four modules each opened their own handle: `hal/sensors.py` and `hal/motors.py`
both did `context.get("pidog")` and built a `Pidog()` if the key was empty, `navigation/
scanning.py` did it a third time, and whichever started last won the `pidog_owner` key that
decided who got to close it. On a real dog that is three `Pidog()` constructors racing over one
I2C bus.

`HalModule` is now the only place that opens hardware, and it publishes the handle as `hal`.
Everything else asks for `hal` and disables itself with a reason if it is absent, which is how
a workstation run degrades instead of crashing.
"""

from __future__ import annotations

import logging

from houndmind_ai.core.module import Module
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.hal.vendor import PidogHAL

logger = logging.getLogger(__name__)

__all__ = ["HalModule"]


class HalModule(Module):
    """Opens the dog, or publishes the injected fake.

    `hal` is the dependency-injection seam: `main.build_registry(config, hal=FakeDogHAL())`
    gives the whole runtime a scripted dog with no hardware, and `None` means "open the real
    one". A caller cannot accidentally get a fake on the device: the fake has to be passed in.
    """

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        required: bool = False,
        hal: DogHAL | None = None,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._injected = hal
        self.hal: DogHAL | None = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return

        hal = self._injected
        if hal is None:
            vendor_hal = PidogHAL(context.get("settings") or {})
            try:
                vendor_hal.start()
            except Exception as exc:  # noqa: BLE001 - a missing vendor package is not a crash
                self.disable(f"pidog unavailable: {exc}")
                return
            hal = vendor_hal

        self.hal = hal
        context.set("hal", hal)
        # `calibration/workflow.py` still speaks the vendor API directly; it is the last
        # consumer of the old key and goes away with the calibration wizard (Phase 5). Kept
        # published so a calibration run behaves exactly as it did before this refactor.
        vendor = getattr(hal, "vendor", None)
        if vendor is not None:
            context.set("pidog", vendor)

    def tick(self, context) -> None:
        """Nothing to do: the HAL is pulled by whoever needs a reading or an action."""

    def stop(self, context) -> None:
        if self.hal is not None:
            try:
                self.hal.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to close the HAL: %s", exc)
            self.hal = None
        context.set("hal", None)
        context.set("pidog", None)
        super().stop(context)