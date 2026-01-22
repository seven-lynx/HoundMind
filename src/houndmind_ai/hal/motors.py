from __future__ import annotations

import logging
import time
from typing import Any

from houndmind_ai.calibration.servo_calibration import apply_servo_offsets
from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


class MotorModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.dog = None
        self.last_action: str | None = None
        self.action_flow = None
        self.last_action_ts = 0.0

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        try:
            from pidog import Pidog  # type: ignore
            from pidog.action_flow import ActionFlow  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Pidog library required on hardware: {exc}") from exc

        dog = context.get("pidog")
        if dog is None:
            dog = Pidog()
            context.set("pidog", dog)
        # Motors should own the hardware lifecycle for clean shutdown.
        context.set("pidog_owner", self.name)
        self.dog = dog
        self.action_flow = ActionFlow(dog)
        self.action_flow.start()

        # Apply calibration offsets if configured.
        calibration = (context.get("settings") or {}).get("calibration", {})
        if calibration.get("auto_apply_servo_offsets", False):
            offsets = calibration.get("servo_zero_offsets", {})
            if isinstance(offsets, dict) and offsets:
                apply_servo_offsets(self.dog, offsets)
            else:
                self._apply_persisted_offsets(calibration)

    def tick(self, context) -> None:
        self._release_head_follow_if_due(context)
        # Safety always overrides navigation/behavior.
        action = (
            context.get("safety_action")
            or context.get("watchdog_action")
            or context.get("navigation_action")
            or context.get("behavior_action")
        )
        if action is None:
            return
        action = str(action)
        if action == self.last_action:
            return

        if self.dog is None or self.action_flow is None:
            return

        # Configurable cooldown keeps actions from spamming the action queue.
        settings = (context.get("settings") or {}).get("motors", {})
        min_interval = _safe_float(settings.get("min_action_interval_s", 0.2), 0.2)
        quiet = (context.get("settings") or {}).get("quiet_mode", {})
        if context.get("quiet_mode_active"):
            quiet_interval = _safe_float(
                quiet.get("motor_min_action_interval_s", min_interval), min_interval
            )
            min_interval = max(min_interval, quiet_interval)
        safety_settings = (context.get("settings") or {}).get("safety", {})
        if context.get("emergency_stop_active") and safety_settings.get(
            "emergency_stop_use_hardware_stop", False
        ):
            self._hardware_stop()

        try:
            now = time.time()
            if now - self.last_action_ts < min_interval:
                return
            navigation_turn = context.get("navigation_turn")
            if isinstance(navigation_turn, dict):
                if self._turn_by_angle(context, navigation_turn):
                    context.set("navigation_turn", None)
                    self.last_action = "turn"
                    self.last_action_ts = now
                    return

            if action in ("turn left", "turn right"):
                direction = "left" if action == "turn left" else "right"
                self._schedule_head_follow(context, direction)

            # Execute action; optionally follow with a retreat/turn sequence.
            self.action_flow.add_action(action)
            followup = context.get("navigation_followup")
            if isinstance(followup, dict):
                if followup.get("type") == "retreat_turn":
                    backup_steps = _safe_int(followup.get("backup_steps", 2), 2)
                    direction = str(followup.get("direction", "auto"))
                    if direction == "auto":
                        direction = "left"
                    self.action_flow.add_action("backward")
                    if backup_steps > 1:
                        # Re-queue backward steps for stronger retreat.
                        for _ in range(backup_steps - 1):
                            self.action_flow.add_action("backward")
                    self._enqueue_turn(context, direction, steps=backup_steps)
                elif followup.get("type") == "sequence":
                    actions = followup.get("actions", [])
                    for entry in actions:
                        if isinstance(entry, str):
                            self.action_flow.add_action(entry)
            self.last_action = action
            self.last_action_ts = now
        except Exception as exc:  # noqa: BLE001
            logger.warning("Motor action failed: %s", exc)
            self.disable(str(exc))

    def _enqueue_turn(self, context, direction: str, steps: int = 1) -> None:
        if self.action_flow is None:
            return
        if self._turn_by_angle(context, {"direction": direction, "steps": steps}):
            return
        for _ in range(max(1, _safe_int(steps, 1))):
            self.action_flow.add_action(f"turn {direction}")

    def _turn_by_angle(self, context, payload: dict) -> bool:
        heading = context.get("current_heading")
        if heading is None:
            return False
        direction = str(payload.get("direction", "left"))
        degrees = payload.get("degrees")
        steps = _safe_int(payload.get("steps", 1), 1)

        settings = context.get("settings") or {}
        movement = settings.get("movement", {})
        orientation = settings.get("orientation", {})
        perf = settings.get("performance", {})
        safe_mode = bool(perf.get("safe_mode_enabled", False))
        degrees_per_step = _safe_float(movement.get("turn_degrees_per_step", 15.0), 15.0)
        if degrees is None:
            degrees = degrees_per_step * steps
        degrees = _safe_float(degrees, degrees_per_step * steps)
        if direction == "right":
            degrees = -degrees

        tolerance = _safe_float(orientation.get("turn_tolerance_deg", 5.0), 5.0)
        timeout_s = _safe_float(orientation.get("turn_timeout_s", 3.0), 3.0)
        speed = _safe_int(movement.get("speed_turn_normal", 200), 200)
        if safe_mode:
            speed = _safe_int(perf.get("safe_mode_turn_speed", speed), speed)
        hint = context.get("energy_speed_hint")
        if hint == "fast":
            speed = _safe_int(movement.get("speed_turn_fast", speed), speed)
        elif hint == "slow":
            speed = _safe_int(movement.get("speed_turn_slow", speed), speed)

        def ang_diff(a: float, b: float) -> float:
            d = (a - b + 180.0) % 360.0 - 180.0
            return d

        start = _safe_float(heading, 0.0)
        target = (start + degrees) % 360.0
        end_time = time.time() + timeout_s

        self._apply_head_follow(direction, context)

        while time.time() < end_time:
            current = _safe_float(context.get("current_heading"), start)
            remaining = ang_diff(target, current)
            if abs(remaining) <= tolerance:
                self._apply_head_center(context)
                return True
            step_dir = "turn left" if remaining > 0 else "turn right"
            try:
                self.dog.do_action(
                    step_dir.replace("turn ", "turn_"), step_count=1, speed=speed
                )
                if hasattr(self.dog, "wait_all_done"):
                    self.dog.wait_all_done()
            except Exception:  # noqa: BLE001
                self._apply_head_center(context)
                return False
            time.sleep(0.05)
        self._apply_head_center(context)
        return False

    def stop(self, context) -> None:
        dog_owner = context.get("pidog_owner")
        if dog_owner == self.name and self.dog is not None:
            try:
                if self.action_flow is not None:
                    self.action_flow.stop()
                self.dog.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to close Pidog: %s", exc)

    def _hardware_stop(self) -> None:
        if self.dog is None:
            return
        for method in ("emergency_stop", "stop", "stop_all", "halt", "standby"):
            if hasattr(self.dog, method):
                try:
                    getattr(self.dog, method)()
                    logger.warning("Motor hardware stop via %s", method)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if self.action_flow is not None and hasattr(self.action_flow, "clear_actions"):
            try:
                self.action_flow.clear_actions()
            except Exception:  # noqa: BLE001
                pass

    def _head_follow_config(
        self, context
    ) -> tuple[bool, float, int, float, bool, float, bool, float]:
        settings = (context.get("settings") or {}).get("motors", {})
        enabled = bool(settings.get("head_turn_follow_enabled", True))
        degrees = _safe_float(settings.get("head_turn_follow_deg", 0.0), 0.0)
        speed = _safe_int(settings.get("head_turn_follow_speed", 70), 70)
        hold_s = _safe_float(settings.get("head_turn_follow_hold_s", 0.4), 0.4)
        respect_scanning = bool(settings.get("head_turn_follow_respect_scanning", True))
        scan_block_s = _safe_float(settings.get("head_turn_follow_scan_block_s", 0.4), 0.4)
        respect_attention = bool(
            settings.get("head_turn_follow_respect_attention", True)
        )
        attention_block_s = _safe_float(
            settings.get("head_turn_follow_attention_block_s", 0.6), 0.6
        )
        return (
            enabled,
            degrees,
            speed,
            hold_s,
            respect_scanning,
            scan_block_s,
            respect_attention,
            attention_block_s,
        )

    def _head_follow_blocked(self, context) -> bool:
        (
            _,
            _,
            _,
            _,
            respect_scanning,
            scan_block_s,
            respect_attention,
            attention_block_s,
        ) = self._head_follow_config(context)
        if not respect_scanning:
            scan_block_s = 0.0
        if not respect_attention:
            attention_block_s = 0.0
        blocked = False
        if scan_block_s > 0:
            scan_reading = context.get("scan_reading")
            scan_ts = _safe_float(getattr(scan_reading, "timestamp", 0.0) if scan_reading else 0.0, 0.0)
            blocked = blocked or (time.time() - scan_ts) < max(0.0, scan_block_s)
        if attention_block_s > 0:
            attention_ts = context.get("attention_active_ts")
            try:
                attention_ts = _safe_float(attention_ts, 0.0) if attention_ts is not None else 0.0
            except Exception:
                attention_ts = 0.0
            blocked = blocked or (time.time() - attention_ts) < max(
                0.0, attention_block_s
            )
        return blocked

    def _apply_head_follow(self, direction: str, context) -> None:
        if self.dog is None or not hasattr(self.dog, "head_move"):
            return
        enabled, degrees, speed, _, _, _, _, _ = self._head_follow_config(context)
        if not enabled or degrees <= 0:
            return
        if self._head_follow_blocked(context):
            return
        yaw = degrees if direction == "left" else -degrees
        try:
            self.dog.head_move([[yaw, 0, 0]], speed=speed)
            if hasattr(self.dog, "wait_head_done"):
                self.dog.wait_head_done()
        except Exception:  # noqa: BLE001
            return

    def _apply_head_center(self, context) -> None:
        if self.dog is None or not hasattr(self.dog, "head_move"):
            return
        enabled, _, speed, _, _, _, _, _ = self._head_follow_config(context)
        if not enabled:
            return
        if self._head_follow_blocked(context):
            return
        try:
            self.dog.head_move([[0, 0, 0]], speed=speed)
            if hasattr(self.dog, "wait_head_done"):
                self.dog.wait_head_done()
        except Exception:  # noqa: BLE001
            return

    def _schedule_head_follow(self, context, direction: str) -> None:
        enabled, degrees, _, hold_s, _, _, _, _ = self._head_follow_config(context)
        if not enabled or degrees <= 0:
            return
        self._apply_head_follow(direction, context)
        context.set("head_turn_follow_release_ts", time.time() + max(0.0, hold_s))

    def _release_head_follow_if_due(self, context) -> None:
        release_ts = context.get("head_turn_follow_release_ts")
        try:
            release_ts = float(release_ts) if release_ts is not None else None
        except Exception:
            release_ts = None
        if release_ts is None:
            return
        if time.time() >= release_ts:
            context.set("head_turn_follow_release_ts", None)
            self._apply_head_center(context)

    def _apply_persisted_offsets(self, calibration: dict) -> None:
        from pathlib import Path
        import json

        path = Path(str(calibration.get("persist_path", "data/calibration.json")))
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            offsets = payload.get("last_result", {}).get("servo_zero_offsets", {})
            if isinstance(offsets, dict) and offsets:
                apply_servo_offsets(self.dog, offsets)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to read persisted calibration", exc_info=True)
