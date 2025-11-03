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
        import importlib.util as _ilu
        from importlib.machinery import PathFinder as _PathFinder

        this_dir = os.path.abspath(os.path.dirname(__file__))
        repo_root = os.path.abspath(os.path.dirname(this_dir))

        # Build a search path that excludes this repo (both pidog folder and root)
        _filtered_path = []
        for p in sys.path:
            ap = os.path.abspath(p)
            if ap == this_dir or ap == repo_root:
                continue
            _filtered_path.append(p)

        _spec = _PathFinder.find_spec("pidog", _filtered_path)
        # Guard against resolving back to ourselves
        if _spec:
            _origin = getattr(_spec, "origin", None)
            if _origin is not None and os.path.abspath(_origin) != os.path.abspath(__file__):
                _mod = _ilu.module_from_spec(_spec)
                assert _spec.loader is not None
                _spec.loader.exec_module(_mod)
                _real_mod = _mod
    except Exception:
        _real_mod = None

if _real_mod is not None and not _force_sim:
    # Try common class name variants found in different releases
    _candidates = ("Pidog", "PiDog", "PIDog", "PIDOG")
    _cls = None
    for _name in _candidates:
        try:
            _cls = getattr(_real_mod, _name)
            break
        except Exception:
            _cls = None
    if _cls is None:
        # Last resort: scan attributes for a class that looks like the main hardware client
        for _name in dir(_real_mod):
            if _name.lower() == "pidog":
                try:
                    _maybe = getattr(_real_mod, _name)
                    if isinstance(_maybe, type):
                        _cls = _maybe
                        break
                except Exception:
                    pass
    if _cls is None:
        _logger.warning("pidog shim: real library found but no Pidog/PiDog class exposed; falling back to sim")
    else:
        Pidog = _cls  # type: ignore[assignment]
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
    if _cls is not None:
        _logger.info("pidog shim: delegated to real hardware library")
    else:
        _real_mod = None  # ensure we drop to sim
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

    class _RgbStrip:
        def set_mode(self, mode: str, color: str, **kwargs):
            _logger.debug(f"[sim] rgb_strip.set_mode({mode}, {color}, {kwargs})")
        def close(self):
            _logger.debug("[sim] rgb_strip.close()")

    class Pidog:
        def __init__(self) -> None:
            self.ultrasonic = _Ultrasonic(self)
            self.dual_touch = _DualTouch()
            self.ears = _Ears()
            self._rgb = _RgbStrip()
            self._randomize = _truthy(os.getenv("HOUNDMIND_SIM_RANDOM"))
            self.accData = (0.0, 0.0, 9.8)
            self.gyroData = (0.0, 0.0, 0.0)
            self._last_action = None
            _logger.info("pidog shim: using simulated PiDog")
        @property
        def distance(self) -> float:
            return self.ultrasonic.read_distance()
        def read_distance(self) -> float:
            return self.ultrasonic.read_distance()
        def head_move(self, seq, speed: int = 60):
            time.sleep(0.02)
        def wait_head_done(self):
            time.sleep(0.01)
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
        def stop_and_lie(self):
            _logger.debug("[sim] stop_and_lie()")
        def close(self):
            _logger.info("pidog shim: close() called")
        @property
        def rgb_strip(self):
            return self._rgb
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
