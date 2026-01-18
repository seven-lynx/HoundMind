from __future__ import annotations

import logging
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)



class SlamPi4Module(Module):
    """Pi4 SLAM module (RTAB-Map or stub backend).

    Publishes:
    - `slam_pose`: {"x": float, "y": float, "yaw": float, "confidence": float}
    - `slam_status`: {"status": "ready", "backend": str}
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.backend = "stub"
        self.available = False
        self._last_ts = 0.0
        self._pose = {"x": 0.0, "y": 0.0, "yaw": 0.0, "confidence": 0.0}
        self._rtabmap = None
        self._rtabmap_cfg = None
        self._rtabmap_failed = False

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("slam_pi4", {})
        self.backend = settings.get("backend", "stub")

        if self.backend == "rtabmap":
            try:
                import rtabmap as rtabmap_py
                self._rtabmap_cfg = settings.get("rtabmap", {})
                # Initialize RTAB-Map (minimal, real pipeline needs camera/IMU)
                self._rtabmap = rtabmap_py.Rtabmap()
                db_path = self._rtabmap_cfg.get("database_path", "rtabmap.db")
                self._rtabmap.init(db_path)
                self.available = True
                context.set("slam_status", {"status": "ready", "backend": self.backend})
                return
            except Exception as exc:
                logger.warning(f"RTAB-Map backend unavailable: {exc}")
                self._rtabmap_failed = True
                self._rtabmap = None
                self.available = False
                # Fallback to stub
        if self.backend == "stub" or self._rtabmap_failed:
            self.available = True
            context.set("slam_status", {"status": "ready", "backend": "stub"})
            return
        self.disable(f"Unknown SLAM backend: {self.backend}")


    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("slam_pi4", {})
        if not settings.get("enabled", True):
            return

        interval = float(settings.get("interval_s", 0.2))
        now = time.time()
        if now - self._last_ts < interval:
            return



        if self.backend == "rtabmap" and self._rtabmap:
            # --- Camera/IMU data pipeline ---
            frame = context.get("vision_frame")
            sensor = context.get("sensor_reading")
            imu = None
            if sensor:
                acc = getattr(sensor, "acc", None)
                gyro = getattr(sensor, "gyro", None)
                imu = {"acc": acc, "gyro": gyro}
            try:
                # Feed frame and IMU to RTAB-Map (API may differ; adjust as needed)
                if frame is not None:
                    ts = getattr(sensor, "timestamp", time.time()) if sensor else time.time()
                    self._rtabmap.process(frame, imu=imu, timestamp=ts)
                pose = self._rtabmap.getPose() if hasattr(self._rtabmap, "getPose") else None
                if pose:
                    self._pose = {
                        "x": float(pose[0]),
                        "y": float(pose[1]),
                        "yaw": float(pose[5]),
                        "confidence": float(pose[6]) if len(pose) > 6 else 1.0,
                    }
                else:
                    self._pose = {"x": 0.0, "y": 0.0, "yaw": 0.0, "confidence": 0.0}

                # Expose map and trajectory for visualization/debugging
                map_data = None
                trajectory = None
                if hasattr(self._rtabmap, "getMapData"):
                    try:
                        map_data = self._rtabmap.getMapData()
                    except Exception as exc:
                        logger.debug(f"RTAB-Map getMapData failed: {exc}")
                if hasattr(self._rtabmap, "getTrajectory"):
                    try:
                        trajectory = self._rtabmap.getTrajectory()
                    except Exception as exc:
                        logger.debug(f"RTAB-Map getTrajectory failed: {exc}")
                context.set("slam_map_data", map_data)
                context.set("slam_trajectory", trajectory)
            except Exception as exc:
                logger.warning(f"RTAB-Map tick failed: {exc}")
                self._pose = {"x": 0.0, "y": 0.0, "yaw": 0.0, "confidence": 0.0}
                context.set("slam_map_data", None)
                context.set("slam_trajectory", None)
        else:
            self._update_stub(context, settings)

        context.set("slam_pose", self._pose)
        context.set("slam_status", {"status": "running", "backend": self.backend})
        self._emit_nav_hint(context, settings)
        self._last_ts = now

    def _update_stub(self, context, settings: dict) -> None:
        imu = (context.get("sensor_reading") or {}).get("gyro")
        yaw = self._pose.get("yaw", 0.0)
        if isinstance(imu, (list, tuple)) and len(imu) >= 3:
            yaw += float(imu[2]) * float(settings.get("gyro_scale", 0.0))
        self._pose = {
            "x": float(self._pose.get("x", 0.0)),
            "y": float(self._pose.get("y", 0.0)),
            "yaw": float(yaw),
            "confidence": float(settings.get("stub_confidence", 0.1)),
        }

    def _emit_nav_hint(self, context, settings: dict) -> None:
        if not settings.get("nav_hint_enabled", False):
            return
        target_heading = settings.get("nav_target_heading_deg")
        if target_heading is None:
            return
        try:
            target_heading = float(target_heading)
        except Exception:
            return

        yaw = float(self._pose.get("yaw", 0.0))
        error = self._normalize_angle(target_heading - yaw)
        deadband = float(settings.get("nav_deadband_deg", 10.0))
        direction = "forward"
        if abs(error) > deadband:
            direction = "right" if error > 0 else "left"
        context.set(
            "slam_nav_hint",
            {
                "direction": direction,
                "confidence": float(self._pose.get("confidence", 0.0)),
                "error_deg": error,
            },
        )

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        while angle <= -180.0:
            angle += 360.0
        while angle > 180.0:
            angle -= 360.0
        return angle
