#!/usr/bin/env python3
"""
IMU Turn Sanity Test
====================

Quick tool to validate IMU-based closed-loop turning. Rotates the PiDog by
±90° using the CanineCore OrientationService for heading feedback and reports
final error.

Usage (on the PiDog):
    python tools/imu_turn_test.py

Notes:
- Requires PiDog hardware and IMU. Make sure there's free space to rotate.
- Uses CanineCore Hardware/IMU/Orientation services (no PackMind orchestrator needed).
"""
from __future__ import annotations
import time
from typing import Any
import os
import sys

# Ensure repo root in sys.path for direct execution from tools/
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _tools_dir = os.path.abspath(os.path.dirname(__file__))
    _repo_root = os.path.abspath(os.path.join(_tools_dir, os.pardir))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)


def _ang_diff(a: float, b: float) -> float:
    d = (a - b + 180.0) % 360.0 - 180.0
    return d


def _turn_by_angle(dog: Any, orient: Any, degrees: float, speed: int = 200, tolerance_deg: float = 5.0, timeout_s: float = 5.0) -> float:
    """Closed-loop turn using 1-step actions and IMU heading feedback.

    Returns the signed final error (target - actual delta) in degrees.
    """
    start = float(orient.get_heading())
    target_delta = float(degrees)
    end_time = time.time() + float(timeout_s)
    while time.time() < end_time:
        current = float(orient.get_heading())
        delta = _ang_diff(current, start)
        remaining = target_delta - delta
        if abs(remaining) <= float(tolerance_deg):
            break
        step_dir = "turn_left" if remaining > 0 else "turn_right"
        try:
            dog.do_action(step_dir, step_count=1, speed=int(speed))
            dog.wait_all_done()
        except Exception:
            break
        time.sleep(0.05)
    # Compute final error
    current = float(orient.get_heading())
    delta = _ang_diff(current, start)
    return target_delta - delta


def main() -> int:
    # Local imports to avoid errors on dev hosts without hardware
    try:
        from canine_core.core.services.hardware import HardwareService  # type: ignore
        from canine_core.core.services.imu import IMUService  # type: ignore
        from canine_core.core.services.orientation import OrientationService  # type: ignore
    except Exception:
        print("[imu-test] Required services not available. Run on PiDog hardware.")
        return 2

    # Init hardware + services
    hw = HardwareService()
    try:
        hw.init()
    except Exception as e:
        print(f"[imu-test] Hardware init failed: {e}")
        return 2

    imu = IMUService(hw)
    orient = OrientationService(imu)
    try:
        orient.start()
    except Exception as e:
        print(f"[imu-test] Orientation start failed: {e}")
        return 2
    time.sleep(0.8)

    dog = hw.dog
    # Gentle stand
    try:
        dog.do_action("stand", speed=80)
        dog.wait_all_done()
    except Exception:
        pass

    print("[imu-test] Starting ±90° turn validation...")

    # Turn +90
    err1 = _turn_by_angle(dog, orient, +90.0, speed=200, tolerance_deg=5.0, timeout_s=6.0)
    print(f"[imu-test] +90°: final error = {err1:+.1f}°")
    time.sleep(0.5)

    # Turn -90 (back to original)
    err2 = _turn_by_angle(dog, orient, -90.0, speed=200, tolerance_deg=5.0, timeout_s=6.0)
    print(f"[imu-test] -90°: final error = {err2:+.1f}°")

    # Summary
    avg_abs = (abs(err1) + abs(err2)) / 2.0
    print(f"[imu-test] Average abs error: {avg_abs:.1f}°")

    # Return to stand
    try:
        dog.do_action("stand", speed=80)
        dog.wait_all_done()
    except Exception:
        pass

    try:
        orient.stop()
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
