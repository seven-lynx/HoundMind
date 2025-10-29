from __future__ import annotations
import threading
import time
from typing import Optional

from .imu import IMUService


class OrientationService:
    """
    Background yaw integrator using IMUService.gyro Z to maintain heading (degrees).

    - start(): spawns a thread that polls IMU and integrates heading
    - stop(): stops the thread
    - get_heading(): returns latest heading in degrees (0..360)
    Config keys (from CanineConfig):
      ORIENTATION_GYRO_SCALE (units->deg/s), ORIENTATION_BIAS_Z, ORIENTATION_CALIBRATION_S
    """

    def __init__(self, imu: IMUService, config: object | None = None) -> None:
        self._imu = imu
        self._config = config
        self._heading_deg: float = 0.0
        self._bias_z: float = 0.0
        self._scale: float = 1.0
        self._running = False
        self._thread: Optional[threading.Thread] = None

        try:
            if config is not None:
                self._scale = float(getattr(config, "ORIENTATION_GYRO_SCALE", self._scale))
                self._bias_z = float(getattr(config, "ORIENTATION_BIAS_Z", self._bias_z))
        except Exception:
            pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Optional quick calibration
        try:
            calib_s = float(getattr(self._config, "ORIENTATION_CALIBRATION_S", 0.0))
        except Exception:
            calib_s = 0.0
        if calib_s > 0:
            self._calibrate_bias(duration_s=calib_s)
        self._thread = threading.Thread(target=self._loop, name="OrientationService", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._running = False
        t = self._thread
        if t:
            t.join(timeout)

    def reset(self, heading_deg: float = 0.0) -> None:
        self._heading_deg = float(heading_deg) % 360.0

    def get_heading(self) -> float:
        return float(self._heading_deg)

    # --- internals ---
    def _calibrate_bias(self, duration_s: float = 1.0) -> None:
        start = time.time()
        samples = 0
        sum_z = 0.0
        while time.time() - start < duration_s:
            g = self._imu.read_gyro()
            if g is not None:
                sum_z += float(g[2])
                samples += 1
            time.sleep(0.01)
        if samples > 0:
            self._bias_z = sum_z / samples

    def _loop(self) -> None:
        last_t = time.monotonic()
        while self._running:
            now = time.monotonic()
            dt = max(0.0, now - last_t)
            last_t = now
            try:
                g = self._imu.read_gyro()
                if g is not None:
                    gz_units = float(g[2])
                    gz_deg_s = (gz_units - self._bias_z) * self._scale
                    self._heading_deg = (self._heading_deg + gz_deg_s * dt) % 360.0
            except Exception:
                pass
            time.sleep(0.02)  # ~50 Hz
