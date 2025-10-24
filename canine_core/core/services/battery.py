from __future__ import annotations
from typing import Any, Optional, Callable


class BatteryService:
    """Monitor battery level/state if hardware exposes it.

    Publishes low/critical events via provided publish callable when thresholds are crossed.
    Sim-safe: if battery unavailable, methods return None and do nothing.
    """

    def __init__(self, hardware: Any, publish: Optional[Callable[[str, dict], None]] = None,
                 low_pct: float = 20.0, critical_pct: float = 10.0) -> None:
        self._hardware = hardware
        self._publish = publish or (lambda *_args, **_kw: None)
        self.low_pct = float(low_pct)
        self.critical_pct = float(critical_pct)

    def read_percentage(self) -> Optional[float]:
        dog = getattr(self._hardware, "dog", None)
        if dog is None:
            return None
        try:
            # Many platforms expose voltage; map to percentage loosely if needed
            if hasattr(dog, "get_battery"):  # hypothetical API
                return float(dog.get_battery())
            if hasattr(dog, "battery_percent"):
                return float(dog.battery_percent())
        except Exception:
            return None
        return None

    def check_and_publish(self) -> Optional[float]:
        pct = self.read_percentage()
        if pct is None:
            return None
        if pct <= self.critical_pct:
            self._publish("battery_critical", {"pct": pct})
        elif pct <= self.low_pct:
            self._publish("battery_low", {"pct": pct})
        return pct
