"""
HoundMind pidog shim

This module provides a drop-in simulation of the PiDog hardware library, but it
will defer to the real package when available unless explicitly overridden via
the HOUNDMIND_SIM environment variable.
"""
from __future__ import annotations

import os
import sys
import time
import random
import logging

_logger = logging.getLogger("pidog_shim")

def _truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}

_force_sim = _truthy(os.getenv("HOUNDMIND_SIM"))

# Try to import the real pidog by temporarily removing this repo's pidog path
_real_mod = None
if not _force_sim:
    try:
        this_dir = os.path.dirname(__file__)
        # Remove any sys.path entries that point to our pidog folder
        old_path = list(sys.path)
        try:
            sys.path = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(os.path.dirname(this_dir)) and os.path.abspath(p) != os.path.abspath(this_dir)]
        except Exception:
            pass
        try:
            _real_mod = __import__("pidog", fromlist=["Pidog"])  # actual installed package
        finally:
            sys.path = old_path
    except Exception:
        _real_mod = None

if _real_mod is not None and not _force_sim:
    try:
        Pidog = getattr(_real_mod, "Pidog")  # type: ignore[attr-defined]
    except Exception:
        Pidog = getattr(_real_mod, "PiDog")  # type: ignore[assignment]
    PiDog = Pidog
    for _name in dir(_real_mod):
        if _name.startswith("__"):
            continue
        if _name in globals():
            continue
        try:
            globals()[_name] = getattr(_real_mod, _name)
        except Exception:
            pass
    _logger.info("pidog shim: delegated to real hardware library")
else:
    class _Ultrasonic:
        def __init__(self, parent: "Pidog") -> None:
            self._parent = parent
            self._base = 120.0
        def read_distance(self) -> float:
            noise = random.uniform(-5.0, 5.0) if self._parent._randomize else 0.0
            return float(max(10.0, round(self._base + noise, 1)))

    class _DualTouch:
        def read(self) -> str:
            return "N"

    class _Ears:
        def isdetected(self) -> bool:
            return False
        def read(self) -> int:
            return -1

    class Pidog:
        def __init__(self) -> None:
            self.ultrasonic = _Ultrasonic(self)
            self.dual_touch = _DualTouch()
            self.ears = _Ears()
            self._randomize = _truthy(os.getenv("HOUNDMIND_SIM_RANDOM"))
            self.accData = (0.0, 0.0, 9.8)
            self.gyroData = (0.0, 0.0, 0.0)
            self._last_action = None
            _logger.info("pidog shim: using simulated PiDog")
        @property
        def distance(self) -> float:
            return self.ultrasonic.read_distance()
        def head_move(self, seq, speed: int = 60):
            time.sleep(0.02)
        def do_action(self, action: str, step_count: int = 1, speed: int = 60, **kwargs):
            self._last_action = (action, step_count, speed, kwargs)
            if self._randomize:
                self.accData = (
                    random.uniform(-0.2, 0.2),
                    random.uniform(-0.2, 0.2),
                    9.8 + random.uniform(-0.2, 0.2),
                )
                self.gyroData = (
                    random.uniform(-0.2, 0.2),
                    random.uniform(-0.2, 0.2),
                    random.uniform(-0.3, 0.3),
                )
            return True
        def body_stop(self):
            self._last_action = ("stop", 0, 0, {})
        def wait_all_done(self):
            time.sleep(0.01)
        def speak(self, sound: str, volume: int = 70):
            _logger.debug(f"[sim] speak: {sound} vol={volume}")
        def power_down(self):
            _logger.info("[sim] power_down invoked")
        def get_accelerometer_data(self):
            if self._randomize:
                return (
                    random.uniform(-0.5, 0.5),
                    random.uniform(-0.5, 0.5),
                    9.81 + random.uniform(-0.2, 0.2),
                )
            return self.accData
        def get_gyroscope_data(self):
            if self._randomize:
                return (
                    random.uniform(-0.1, 0.1),
                    random.uniform(-0.1, 0.1),
                    random.uniform(-0.1, 0.1),
                )
            return self.gyroData

    PiDog = Pidog

__all__ = ["Pidog", "PiDog"]
