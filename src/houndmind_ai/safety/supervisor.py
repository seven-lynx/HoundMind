from __future__ import annotations

import logging
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class SafetyModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.too_close_cm = 10
        self._context = None
        self._sensor_service = None
        # Cache the last override state to minimize redundant writes.
        self._last_override_active = False
        # Cooldown tracking for emergency stop actions.
        self._last_emergency_ts = 0.0
        self._last_tilt_ts = 0.0

    def start(self, context) -> None:
        self._context = context
        service = context.get("sensor_service")
        if service is not None and hasattr(service, "subscribe"):
            self._sensor_service = service
            service.subscribe(self._on_sensor_reading)

    def tick(self, context) -> None:
        # Load safety settings from the master config each tick.
        settings = (context.get("settings") or {}).get("safety", {})
        self.too_close_cm = settings.get("too_close_cm", self.too_close_cm)

        reading = context.get("sensor_reading")
        if reading is not None:
            self._update_from_reading(context, reading)

    def stop(self, context) -> None:
        if self._sensor_service is not None:
            try:
                self._sensor_service.unsubscribe(self._on_sensor_reading)
            except Exception:  # noqa: BLE001
                pass

    def _on_sensor_reading(self, reading) -> None:
        if self._context is None:
            return
        self._update_from_reading(self._context, reading)

    def _update_from_reading(self, context, reading) -> None:
        distance = getattr(reading, "distance_cm", None)
        settings = (context.get("settings") or {}).get("safety", {})
        emergency_enabled = bool(settings.get("emergency_stop_enabled", True))
        emergency_action = settings.get("emergency_stop_action", "lie")
        emergency_cooldown_s = float(settings.get("emergency_stop_cooldown_s", 2.0))
        emergency_stop_cm = float(settings.get("emergency_stop_cm", self.too_close_cm))
        now = time.time()

        # Tilt/pose safety: compute simple pitch/roll from accelerometer and
        # trigger a safety action if orientation exceeds configured thresholds.
        try:
            acc = getattr(reading, "acc", None)
            if acc is None:
                sensors = context.get("sensors") or {}
                acc = sensors.get("acc")
            if acc is not None and len(acc) >= 3:
                import math

                ax, ay, az = float(acc[0]), float(acc[1]), float(acc[2])
                # Compute small-angle-safe pitch/roll in degrees.
                pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
                roll = math.degrees(math.atan2(ay, az))
                tilt_threshold = float(settings.get("tilt_threshold_deg", 45.0))
                tilt_action = settings.get("tilt_action", emergency_action)
                tilt_cooldown = float(settings.get("tilt_cooldown_s", 1.0))
                if abs(pitch) >= tilt_threshold or abs(roll) >= tilt_threshold:
                    if now - self._last_tilt_ts < tilt_cooldown:
                        return
                    self._last_tilt_ts = now
                    context.set(
                        "tilt_warning", {"timestamp": now, "pitch": pitch, "roll": roll}
                    )
                    context.set("safety_action", tilt_action)
                    context.set("safety_active", True)
                    context.set("emergency_stop_active", False)
                    context.set(
                        "led_request:safety",
                        {
                            "timestamp": now,
                            "mode": "tilt",
                            "priority": int(settings.get("led_priority", 80)),
                        },
                    )
                    self._apply_override_priority(context)
                    logger.warning(
                        "Tilt warning: pitch=%.1f roll=%.1f; action=%s",
                        pitch,
                        roll,
                        tilt_action,
                    )
                    return
        except Exception:  # noqa: BLE001
            logger.debug("Tilt check failed", exc_info=True)

        # Emergency stop takes priority when enabled and within threshold.
        if (
            emergency_enabled
            and isinstance(distance, (int, float))
            and 0 < distance <= emergency_stop_cm
        ):
            if now - self._last_emergency_ts < emergency_cooldown_s:
                return
            self._last_emergency_ts = now
            context.set("safety_action", emergency_action)
            context.set("safety_active", True)
            context.set("emergency_stop_active", True)
            context.set(
                "led_request:safety",
                {
                    "timestamp": now,
                    "mode": "emergency",
                    "priority": int(settings.get("led_priority", 80)),
                },
            )
            self._apply_override_priority(context)
            logger.warning(
                "Emergency stop: distance=%scm action=%s", distance, emergency_action
            )
            return

        # Apply safety overrides when within the critical distance threshold.
        if isinstance(distance, (int, float)) and 0 < distance <= self.too_close_cm:
            context.set("safety_action", "backward")
            context.set("safety_active", True)
            context.set("emergency_stop_active", False)
            self._apply_override_priority(context)
            logger.warning("Safety override: obstacle too close (%scm)", distance)
        else:
            context.set("safety_action", None)
            context.set("safety_active", False)
            context.set("emergency_stop_active", False)
            context.set("led_request:safety", None)
            # Clear the cached state when safety is no longer active.
            self._last_override_active = False

    def _apply_override_priority(self, context) -> None:
        # Pull safety settings for override behavior.
        settings = (context.get("settings") or {}).get("safety", {})
        # Ordered priority list: earlier items are higher priority.
        priority = settings.get(
            "override_priority",
            ["safety", "watchdog", "navigation", "behavior"],
        )
        if not isinstance(priority, list) or not priority:
            priority = ["safety", "watchdog", "navigation", "behavior"]

        # Avoid rewriting context on every tick when already active.
        if self._last_override_active:
            return
        self._last_override_active = True

        # Optionally clear lower-priority actions to avoid conflicting intent.
        clear_lower = bool(settings.get("override_clear_lower", True))
        if not clear_lower:
            return

        # Map logical priorities to context keys for action overrides.
        priority_map = {
            "safety": "safety_action",
            "watchdog": "watchdog_action",
            "navigation": "navigation_action",
            "behavior": "behavior_action",
        }
        if "safety" not in priority:
            return
        safety_index = priority.index("safety")
        for name in priority[safety_index + 1 :]:
            key = priority_map.get(str(name))
            if key:
                context.set(key, None)
