from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default
import importlib

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class _RtabmapAdapter:
    """Minimal defensive adapter for RTAB-Map Python bindings."""

    def __init__(self, cfg: dict | None = None):
        self._rtab: Any | None = None
        self._cfg = cfg or {}

    def available(self) -> bool:
        try:
            importlib.import_module("rtabmap")
            return True
        except Exception:
            return False

    def init(self, db_path: str) -> None:
        import rtabmap  # type: ignore

        self._rtab = getattr(rtabmap, "Rtabmap", None)
        if callable(self._rtab):
            self._rtab = self._rtab()
        # Apply optional parameters from cfg if binding supports it
        params = self._cfg.get("params") if isinstance(self._cfg, dict) else None
        r = self._rtab
        if params and r is not None and hasattr(r, "set_parameters"):
            try:
                r.set_parameters(params)
            except Exception:
                # ignore if API differs
                pass

    def process(self, frame: Any, imu: dict | None = None, timestamp: float | None = None) -> None:
        if self._rtab is None:
            raise RuntimeError("RTAB-Map backend not initialized")
        try:
            if hasattr(self._rtab, "process"):
                self._rtab.process(frame, imu=imu, timestamp=timestamp)
            elif hasattr(self._rtab, "update"):
                self._rtab.update(frame)
            else:
                try:
                    self._rtab(frame)
                except Exception:
                    logger.debug("RTAB-Map: unknown process signature")
        except Exception as exc:
            logger.debug("RTAB-Map process error: %s", exc)

    def get_pose(self):
        if self._rtab is None:
            return None
        try:
            if hasattr(self._rtab, "getPose"):
                return self._rtab.getPose()
            if hasattr(self._rtab, "get_pose"):
                return self._rtab.get_pose()
        except Exception as exc:
            logger.debug("RTAB-Map get_pose failed: %s", exc)
        return None

    def get_map_data(self):
        if self._rtab is None:
            return None
        try:
            if hasattr(self._rtab, "getMapData"):
                return self._rtab.getMapData()
            if hasattr(self._rtab, "get_map_data"):
                return self._rtab.get_map_data()
        except Exception as exc:
            logger.debug("RTAB-Map get_map_data failed: %s", exc)
        return None

    def get_trajectory(self):
        if self._rtab is None:
            return None
        try:
            if hasattr(self._rtab, "getTrajectory"):
                return self._rtab.getTrajectory()
            if hasattr(self._rtab, "get_trajectory"):
                return self._rtab.get_trajectory()
        except Exception as exc:
            logger.debug("RTAB-Map get_trajectory failed: %s", exc)
        return None



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
        self._adapter: _RtabmapAdapter | None = None
        self._rtabmap_cfg: dict = {}
        self._rtabmap_failed = False

        # Buffers for frame+imu pairing: store tuples (timestamp, frame, imu)
        self._buffer: deque = deque()

        # Track last map export time
        self._last_map_export_ts = 0.0

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("slam_pi4", {})
        self.backend = settings.get("backend", "rtabmap")
        self._rtabmap_cfg = settings.get("rtabmap", {}) or {}

        if self.backend == "rtabmap":
            adapter = _RtabmapAdapter(self._rtabmap_cfg)
            if adapter.available():
                try:
                    db_path = self._rtabmap_cfg.get("database_path", "rtabmap.db")
                    adapter.init(db_path)
                    self._adapter = adapter
                    self.available = True
                    context.set("slam_status", {"status": "ready", "backend": "rtabmap"})
                    return
                except Exception as exc:
                    logger.warning("RTAB-Map initialization failed: %s", exc)
                    self._rtabmap_failed = True
                    self._adapter = None
            else:
                logger.info("RTAB-Map bindings not present; falling back to stub")
                self._rtabmap_failed = True

        # Fallback to stub
        self.available = True
        context.set("slam_status", {"status": "ready", "backend": "stub"})


    def tick(self, context) -> None:
        if not self.available or not self.status.enabled:
            return
        settings = (context.get("settings") or {}).get("slam_pi4", {})
        if not settings.get("enabled", True):
            return

        interval = _safe_float(settings.get("interval_s", 0.2), 0.2)
        now = time.time()
        if now - self._last_ts < interval:
            return

        # Read incoming frame and sensor reading and push to buffer
        frame = context.get("vision_frame")
        sensor = context.get("sensor_reading") or {}
        imu = None
        if isinstance(sensor, dict):
            imu = {"acc": sensor.get("acc"), "gyro": sensor.get("gyro"), "timestamp": sensor.get("timestamp")}
        else:
            imu = {"acc": getattr(sensor, "acc", None), "gyro": getattr(sensor, "gyro", None), "timestamp": getattr(sensor, "timestamp", None)}

        ts = None
        if imu and imu.get("timestamp"):
            try:
                ts = _safe_float(imu.get("timestamp"), time.time())
            except Exception:
                ts = time.time()
        else:
            ts = time.time()

        if frame is not None or imu is not None:
            self._buffer.append((ts, frame, imu))

        # Trim buffer to configured max age
        max_buffer_s = _safe_float(settings.get("max_buffer_s", 2.0), 2.0)
        cutoff = now - max_buffer_s
        while self._buffer and (self._buffer[0][0] < cutoff):
            self._buffer.popleft()

        # Process buffer with RTAB-Map adapter if available
        if self._adapter and not self._rtabmap_failed:
            processed = 0
            max_per_tick = int(settings.get("max_process_per_tick", 4))
            while self._buffer and processed < max_per_tick:
                item_ts, item_frame, item_imu = self._buffer.popleft()
                try:
                    self._adapter.process(item_frame, imu=item_imu, timestamp=item_ts)
                except Exception as exc:
                    logger.debug("RTAB-Map adapter process error: %s", exc)
                processed += 1

            # Retrieve pose and map data
            try:
                pose = self._adapter.get_pose() if self._adapter else None
                if pose:
                    try:
                        x = _safe_float(pose[0], 0.0)
                        y = _safe_float(pose[1], 0.0)
                        yaw = _safe_float(pose[5], 0.0) if len(pose) > 5 else 0.0
                        conf = _safe_float(pose[6], 1.0) if len(pose) > 6 else 1.0
                        self._pose = {"x": x, "y": y, "yaw": yaw, "confidence": conf}
                    except Exception:
                        pass
                map_data = self._adapter.get_map_data() if self._adapter else None
                trajectory = self._adapter.get_trajectory() if self._adapter else None
                context.set("slam_map_data", map_data)
                context.set("slam_trajectory", trajectory)
            except Exception as exc:
                logger.warning("RTAB-Map retrieval failed: %s", exc)
                context.set("slam_map_data", None)
                context.set("slam_trajectory", None)

            # Optionally export map to file with selectable format
            map_export_interval = _safe_float(settings.get("map_export_interval_s", 0), 0.0)
            map_export_path = settings.get("map_export_path")
            map_export_format = (settings.get("map_export_format") or "json").lower()
            if map_export_interval > 0 and map_export_path:
                if now - self._last_map_export_ts >= map_export_interval:
                    try:
                        md = self._adapter.get_map_data() if self._adapter else None
                        if md is not None:
                            try:
                                if map_export_format == "json":
                                    import json

                                    with open(map_export_path, "w", encoding="utf-8") as fh:
                                        fh.write(json.dumps({"exported_at": now, "map": md}))
                                elif map_export_format == "ply":
                                    # Expect md to be iterable of [x,y,z] points
                                    try:
                                        with open(map_export_path, "w", encoding="utf-8") as fh:
                                            pts = list(md)
                                            fh.write("ply\nformat ascii 1.0\nelement vertex %d\nproperty float x\nproperty float y\nproperty float z\nend_header\n" % len(pts))
                                            for p in pts:
                                                fh.write(f"{p[0]} {p[1]} {p[2]}\n")
                                    except Exception:
                                        logger.debug("Failed to export PLY; falling back to JSON")
                                        import json

                                        with open(map_export_path, "w", encoding="utf-8") as fh:
                                            fh.write(json.dumps({"exported_at": now, "map": md}))
                                else:
                                    # Unknown format: default to JSON
                                    import json

                                    with open(map_export_path, "w", encoding="utf-8") as fh:
                                        fh.write(json.dumps({"exported_at": now, "map": md}))
                                self._last_map_export_ts = now
                            except Exception as exc:
                                logger.debug("Failed to write map export: %s", exc)
                    except Exception as exc:
                        logger.debug("Map export failed: %s", exc)
        else:
            self._update_stub(context, settings, imu)

        context.set("slam_pose", self._pose)
        context.set("slam_status", {"status": "running", "backend": ("rtabmap" if self._adapter else "stub")})
        self._emit_nav_hint(context, settings)
        self._last_ts = now

    def _update_stub(self, context, settings: dict, imu: dict | None = None) -> None:
        yaw = self._pose.get("yaw", 0.0)
        gyro = None
        if imu:
            gyro = imu.get("gyro")
        if isinstance(gyro, (list, tuple)) and len(gyro) >= 3:
            yaw += _safe_float(gyro[2], 0.0) * _safe_float(settings.get("gyro_scale", 0.0), 0.0)
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
