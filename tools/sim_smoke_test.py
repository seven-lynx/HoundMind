#!/usr/bin/env python3
"""
Simple desktop smoke test for the pidog simulation shim.

Usage (PowerShell):
  $env:HOUNDMIND_SIM = "1"; python tools/sim_smoke_test.py

This will:
- instantiate Pidog (sim)
- perform a couple of head moves
- take a few ultrasonic readings
- optionally run a 3-way scan via ScanningService
"""
import os
import sys

# Force simulation mode by default
os.environ.setdefault("HOUNDMIND_SIM", "1")

# Ensure repo root in sys.path for direct execution from tools/
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _tools_dir = os.path.abspath(os.path.dirname(__file__))
    _repo_root = os.path.abspath(os.path.join(_tools_dir, os.pardir))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sim_smoke_test")

try:
    from pidog import Pidog  # should resolve to simulator on desktop
except Exception as e:
    print(f"Failed to import pidog shim: {e}")
    raise

# Optional: basic scanning using PackMind's service
try:
    from packmind.core.context import AIContext
    from packmind.services.scanning_service import ScanningService
except Exception:
    AIContext = None
    ScanningService = None


def main():
    dog = Pidog()
    logger.info("Created Pidog instance (simulated)")

    # Head moves
    dog.head_move([[0, 0, 0]], speed=60)
    time.sleep(0.1)
    dog.head_move([[30, 0, 0]], speed=60)
    time.sleep(0.1)
    dog.head_move([[-30, 0, 0]], speed=60)
    time.sleep(0.1)
    dog.head_move([[0, 0, 0]], speed=60)

    # Sensor reads
    d = dog.ultrasonic.read_distance()
    touch = dog.dual_touch.read()
    ears = (dog.ears.isdetected(), dog.ears.read())
    imu = (dog.accData, dog.gyroData)

    logger.info(f"Ultrasonic distance: {d} cm")
    logger.info(f"Touch: {touch}")
    logger.info(f"Ears: detected={ears[0]} dir={ears[1]}")
    logger.info(f"IMU: acc={imu[0]} gyro={imu[1]}")

    # Three-way scan if PackMind modules import
    if AIContext and ScanningService:
        ctx = AIContext()
        ctx.dog = dog
        scanner = ScanningService(ctx)
        res = scanner.scan_three_way(left_deg=20, right_deg=20, settle_s=0.1, samples=2)
        logger.info(f"3-way scan: {res}")
    else:
        logger.info("PackMind scanning not available; skipping 3-way scan")

    logger.info("Simulation smoke test completed")


if __name__ == "__main__":
    main()
