#!/usr/bin/env python3
"""
PiDog Turn Calibration Tool
===========================

Hands-free utility to measure degrees-per-step at typical turn speeds using
the IMU-based orientation service, then update config files automatically.

- Calibrates using CanineCore Hardware + IMU services (works for both stacks)
- Measures small single-step left turns at configured speeds
- Updates:
  - CanineCore: TURN_DEGREES_PER_STEP (fallback) and TURN_DPS_BY_SPEED mapping
  - PackMind: TURN_DEGREES_PER_STEP and derived step counts (45/90/180)

Usage:
    python tools/turn_calibration.py

Notes:
- Requires PiDog hardware available (pidog library) and IMU functional.
- Ensure the robot has space to turn in place.
"""
from __future__ import annotations
import re
import time
from pathlib import Path
from typing import Dict, Tuple, Optional, Any
import os
import sys

# Ensure repo root in sys.path for direct execution from tools/
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _tools_dir = os.path.abspath(os.path.dirname(__file__))
    _repo_root = os.path.abspath(os.path.join(_tools_dir, os.pardir))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

ROOT = Path(__file__).resolve().parents[1]

CFG_CANINE = ROOT / "canine_core" / "config" / "canine_config.py"
CFG_PACKMIND = ROOT / "packmind" / "packmind_config.py"


def _ang_diff(a: float, b: float) -> float:
    d = (a - b + 180.0) % 360.0 - 180.0
    return d


def _measure_degrees_per_step(dog: Any, orientation: Any, speed: int, samples: int = 4) -> Optional[float]:
    """Issue one-step left turns and measure average degrees per step using IMU heading."""
    try:
        # Prep posture
        try:
            dog.do_action("stand", speed=max(40, int(speed * 0.5)))
            dog.wait_all_done()
        except Exception:
            pass
        time.sleep(0.3)
        vals = []
        for _ in range(max(1, samples)):
            start = float(orientation.get_heading())
            try:
                dog.do_action("turn_left", step_count=1, speed=int(speed))
                dog.wait_all_done()
            except Exception:
                return None
            time.sleep(0.3)
            cur = float(orientation.get_heading())
            delta = _ang_diff(cur, start)
            if delta < 0:
                delta += 360.0
            vals.append(delta)
            time.sleep(0.2)
        if not vals:
            return None
        return sum(vals) / len(vals)
    except Exception:
        return None


def _update_key_value(text: str, key: str, new_value: str) -> Tuple[str, bool]:
    """Replace a top-level assignment line like 'KEY = ...' with new value string.
    Returns (updated_text, changed?)."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*.*$", re.MULTILINE)
    repl = f"{key} = {new_value}"
    if pattern.search(text):
        out = pattern.sub(repl, text)
        return out, True
    return text, False


def _insert_after_key(text: str, after_key: str, insert_block: str) -> Tuple[str, bool]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(after_key)}\s*=\s*.*$", line):
            lines.insert(i + 1, insert_block)
            return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), True
    return text, False


def _format_float(x: float, decimals: int = 2) -> str:
    return (f"{x:.{decimals}f}").rstrip("0").rstrip(".")


def _update_canine_config(dps_by_speed: Dict[int, float], normal_speed: int) -> bool:
    changed = False
    try:
        txt = CFG_CANINE.read_text(encoding="utf-8")
    except Exception:
        return False
    # Update scalar fallback to normal speed value
    dps_normal = dps_by_speed.get(int(normal_speed))
    if dps_normal is not None:
        new_txt, did = _update_key_value(txt, "TURN_DEGREES_PER_STEP", _format_float(dps_normal, 2))
        txt, changed = new_txt, (changed or did)
    # Build mapping block
    mapping = ", ".join(f"{int(k)}: {_format_float(v, 3)}" for k, v in sorted(dps_by_speed.items()))
    block = f"TURN_DPS_BY_SPEED = {{{mapping}}}"
    if "TURN_DPS_BY_SPEED" in txt:
        new_txt, did = _update_key_value(txt, "TURN_DPS_BY_SPEED", f"{{{mapping}}}")
        txt, changed = new_txt, (changed or did)
    else:
        new_txt, did = _insert_after_key(txt, "TURN_DEGREES_PER_STEP", block)
        txt, changed = new_txt, (changed or did)
    if changed:
        CFG_CANINE.write_text(txt, encoding="utf-8")
    return changed


def _update_packmind_config(dps_normal: Optional[float]) -> bool:
    changed = False
    try:
        txt = CFG_PACKMIND.read_text(encoding="utf-8")
    except Exception:
        return False
    if dps_normal is not None:
        # Update scalar
        new_txt, did = _update_key_value(txt, "TURN_DEGREES_PER_STEP", str(int(round(dps_normal))))
        txt, changed = new_txt, (changed or did)
        # Update step counts for 45/90/180 based on new dps
        try:
            s45 = max(1, int(round(45.0 / dps_normal)))
            s90 = max(1, int(round(90.0 / dps_normal)))
            s180 = max(1, int(round(180.0 / dps_normal)))
            for key, val in ("TURN_45_DEGREES", s45), ("TURN_90_DEGREES", s90), ("TURN_180_DEGREES", s180):
                txt, did2 = _update_key_value(txt, key, str(val))
                changed = changed or did2
        except Exception:
            pass
    if changed:
        CFG_PACKMIND.write_text(txt, encoding="utf-8")
    return changed


def main() -> int:
    # Import services and configs locally to avoid static analysis issues when unavailable on host
    try:
        from canine_core.core.services.hardware import HardwareService
        from canine_core.core.services.imu import IMUService
        from canine_core.core.services.orientation import OrientationService
    except Exception:
        print("[calibrate] Required services not available. Run on PiDog hardware.")
        return 2
    try:
        from canine_core.config.canine_config import CanineConfig  # type: ignore
    except Exception:
        CanineConfig = None  # type: ignore
    try:
        from packmind.packmind_config import PiDogConfig  # type: ignore
    except Exception:
        PiDogConfig = None  # type: ignore
    # Gather speeds from configs (if importable)
    canine_speeds = []
    packmind_speeds = []
    normal_speeds = []
    try:
        if CanineConfig is not None:
            cfg = CanineConfig()
            canine_speeds = [int(getattr(cfg, n, 0)) for n in ("SPEED_TURN_SLOW", "SPEED_TURN_NORMAL", "SPEED_TURN_FAST")]
            normal_speeds.append(int(getattr(cfg, "SPEED_TURN_NORMAL", 200)))
    except Exception:
        pass
    try:
        if PiDogConfig is not None:
            pcfg = PiDogConfig()
            packmind_speeds = [int(getattr(pcfg, n, 0)) for n in ("SPEED_TURN_SLOW", "SPEED_TURN_NORMAL", "SPEED_TURN_FAST")]
            normal_speeds.append(int(getattr(pcfg, "SPEED_TURN_NORMAL", 200)))
    except Exception:
        pass
    speeds = sorted({int(s) for s in canine_speeds + packmind_speeds if int(s) > 0}) or [100, 200, 220]
    normal_speed = int(normal_speeds[0]) if normal_speeds else 200

    # Initialize hardware + orientation
    hw = HardwareService()
    try:
        hw.init()
    except Exception as e:
        print(f"[calibrate] Hardware init failed: {e}")
        return 2
    imu = IMUService(hw)
    # Use CanineConfig orientation tuning if available
    cfg = None
    try:
        if CanineConfig is not None:
            cfg = CanineConfig()
    except Exception:
        cfg = None
    # Ensure a brief bias calibration for more stable readings
    if cfg is not None:
        try:
            setattr(cfg, "ORIENTATION_CALIBRATION_S", max(1.0, float(getattr(cfg, "ORIENTATION_CALIBRATION_S", 0.0))))
        except Exception:
            pass
    orient = OrientationService(imu, config=cfg)
    try:
        orient.start()
    except Exception as e:
        print(f"[calibrate] Orientation start failed: {e}")
        return 2
    time.sleep(0.8)

    # Measure dps per speed
    results: Dict[int, float] = {}
    for spd in speeds:
        dps = _measure_degrees_per_step(hw.dog, orient, spd, samples=4)
        if dps is None:
            print(f"[calibrate] Speed {spd}: measurement failed; skipping")
            continue
        results[int(spd)] = float(dps)
        print(f"[calibrate] Speed {spd}: {dps:.2f} deg/step")

    # Stop orientation
    try:
        orient.stop()
    except Exception:
        pass

    if not results:
        print("[calibrate] No measurements produced; aborting without config changes.")
        return 1

    # Update configs
    changed_canine = _update_canine_config(results, normal_speed=normal_speed)
    dps_normal = results.get(int(normal_speed))
    changed_pack = _update_packmind_config(dps_normal)

    print("[calibrate] Updated:", "CanineCore" if changed_canine else "(no CanineCore change)", "/",
          "PackMind" if changed_pack else "(no PackMind change)")

    # Gentle stand still at end
    try:
        hw.dog.do_action("stand", speed=80)
        hw.dog.wait_all_done()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
