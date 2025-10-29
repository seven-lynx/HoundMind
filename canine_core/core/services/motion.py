from __future__ import annotations
from typing import Any
import time


class MotionService:
    """Reusable movement helpers with sim-safety.

    Adds optional global speed scaling to help conserve power when battery is low.
    Only affects calls made via MotionService.act(); direct dog.do_action() calls
    in behaviors are unaffected.
    """
    def __init__(self, hardware: Any) -> None:
        self.hardware = hardware
        self._speed_scale: float = 1.0  # 0.0..1.0 typically; clamped in act()

    def set_speed_scale(self, scale: float) -> None:
        try:
            self._speed_scale = float(scale)
        except Exception:
            self._speed_scale = 1.0
        # clamp
        if not (0.0 < self._speed_scale <= 2.0):
            self._speed_scale = min(max(self._speed_scale, 0.05), 2.0)

    def get_speed_scale(self) -> float:
        return float(self._speed_scale)

    def act(self, action: str, **kwargs) -> None:
        dog = getattr(self.hardware, "dog", None)
        if dog is None:
            return
        try:
            # Apply speed scaling if a speed kwarg is present
            if "speed" in kwargs:
                try:
                    scaled = int(max(1, round(float(kwargs["speed"]) * self._speed_scale)))
                    kwargs["speed"] = scaled
                except Exception:
                    pass
            dog.do_action(action, **kwargs)
        except Exception:
            pass

    def wait(self) -> None:
        dog = getattr(self.hardware, "dog", None)
        if dog is None:
            return
        try:
            dog.wait_all_done()
        except Exception:
            pass

    # --- helpers ---
    def turn_by_angle(
        self,
        degrees: float,
        speed: int,
        ctx: Any | None = None,
        tolerance_deg: float = 5.0,
        timeout_s: float = 3.0,
    ) -> None:
        """Turn in place by the requested angle.

        If an orientation service is available on ctx (ctx.orientation), uses IMU-based
        closed-loop steps until within tolerance. Otherwise, falls back to fixed-step
        turns using TURN_DEGREES_PER_STEP from config (default 15 deg/step).
        """
        dog = getattr(self.hardware, "dog", None)
        if dog is None:
            return
        # Try IMU-based precise turning when possible
        orientation = getattr(ctx, "orientation", None) if ctx is not None else None
        if orientation is not None and hasattr(orientation, "get_heading"):
            try:
                start = float(orientation.get_heading())
                def ang_diff(a: float, b: float) -> float:
                    d = (a - b + 180.0) % 360.0 - 180.0
                    return d
                end_time = time.time() + float(timeout_s)
                while time.time() < end_time:
                    current = float(orientation.get_heading())
                    delta = ang_diff(current, start)
                    remaining = float(degrees) - delta
                    if abs(remaining) <= float(tolerance_deg):
                        break
                    step_dir = "turn_left" if remaining > 0 else "turn_right"
                    try:
                        self.act(step_dir, step_count=1, speed=int(speed))
                    except Exception:
                        pass
                    time.sleep(0.1)
            except Exception:
                # fall back to step-based if anything goes wrong
                pass
            finally:
                self.wait()
            return
        # Fallback: step-based estimate using degrees-per-step
        # Prefer per-speed mapping if available; fallback to scalar
        dps = 15.0
        cfg = getattr(ctx, "config", None) if ctx is not None else None
        if cfg is not None:
            try:
                mapping = getattr(cfg, "TURN_DPS_BY_SPEED", None)
                if isinstance(mapping, dict) and len(mapping) > 0:
                    # choose nearest key to requested speed
                    keys = sorted(int(k) for k in mapping.keys())
                    pick = min(keys, key=lambda k: abs(k - int(speed)))
                    dps = float(mapping[pick])
                else:
                    dps = float(getattr(cfg, "TURN_DEGREES_PER_STEP", 15.0))
            except Exception:
                try:
                    dps = float(getattr(cfg, "TURN_DEGREES_PER_STEP", 15.0))
                except Exception:
                    dps = 15.0
        steps = max(1, int(round(abs(float(degrees)) / max(1e-6, dps))))
        direction = "turn_left" if float(degrees) > 0 else "turn_right"
        self.act(direction, step_count=steps, speed=int(speed))
        self.wait()
