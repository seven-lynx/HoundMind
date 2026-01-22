from __future__ import annotations

import logging
import time
from collections import Counter, deque

from typing import Any, cast

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


class ObstacleAvoidanceModule(Module):
    """Translate perception into navigation actions.

    This module stays lightweight and relies on PiDog's built-in actions.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._baseline_cm: dict[int, float] = {}
        self._confirm_votes: deque[str] = deque(maxlen=1)
        self._last_scan_ts = 0.0
        self._last_approach_ts = 0.0
        self._approach_votes: deque[bool] = deque(maxlen=1)
        self._movement_history: deque[tuple[float, float]] = deque(maxlen=100)
        self._last_stuck_ts = 0.0
        self._avoid_history: deque[float] = deque(maxlen=20)
        self._strategy_index = 0
        self._last_strategy: str | None = None
        self._stuck_count = 0
        self._last_low_confidence_ts = 0.0
        self._low_confidence_retries = 0
        self._last_mapping_bias_ts = 0.0
        self._decision_last_ts = 0.0
        self._turn_cooldown_ts = 0.0
        self._dead_end_cache: deque[int] = deque(maxlen=5)
        self._clear_path_streak = 0
        self._no_go_history: deque[tuple[float, str]] = deque(maxlen=40)
        # Gentle recovery state
        self._gentle_recovery_active = False
        self._gentle_recovery_until = 0.0

    def tick(self, context) -> None:
        perception = context.get("perception") or {}
        obstacle = perception.get("obstacle", False)
        sensor_reading = context.get("sensor_reading")
        distance = (
            getattr(sensor_reading, "distance_cm", None)
            if sensor_reading
            else perception.get("distance")
        )

        settings = (context.get("settings") or {}).get("navigation", {})
        avoid_action = settings.get("avoid_action", "backward")
        safe_action = settings.get("safe_action", "stand")
        scan_interval_s = _safe_float(settings.get("scan_interval_s", 0.5), 0.5)
        emergency_stop_cm = _safe_float(settings.get("emergency_stop_cm", 12), 12)
        safe_distance_cm = _safe_float(settings.get("safe_distance_cm", 35), 35)
        approach_delta_cm = _safe_float(settings.get("approach_delta_cm", 10), 10)
        approach_delta_pct = _safe_float(settings.get("approach_delta_pct", 0.25), 0.25)
        approach_cooldown_s = _safe_float(settings.get("approach_cooldown_s", 2.0), 2.0)
        backup_steps = _safe_int(settings.get("backup_steps", 2), 2)
        retreat_turn_direction = settings.get("retreat_turn_direction", "auto")

        # Gentle recovery config
        gentle_recovery_threshold = _safe_int(
            settings.get("gentle_recovery_stuck_count", 3), 3
        )
        gentle_recovery_cooldown = _safe_float(
            settings.get("gentle_recovery_cooldown_s", 8.0), 8.0
        )

        now = time.time()
        turn_degrees_on_gap = _safe_int(settings.get("turn_degrees_on_gap", 30), 30)

        # Action/result variables
        nav_action = None
        nav_turn = None
        nav_led = None
        nav_followup = None
        emit_decision = None
        stuck_recovery = None
        # ...existing code...

        # Emergency retreat if obstacle is too close.
        if isinstance(distance, (int, float)) and 0 < distance <= emergency_stop_cm:
            nav_action = avoid_action
            self._record_no_go("forward", now)
            nav_led = "retreat"
        else:
            clear_streak_min = int(settings.get("clear_path_streak_min", 0))
            if (
                not obstacle
                and clear_streak_min > 0
                and self._clear_path_streak >= clear_streak_min
            ):
                if settings.get("clear_path_skip_scans", True):
                    nav_action = "forward"
                    nav_led = "patrol"
                    self._clear_path_streak += 1
                    emit_decision = ("forward", 0.0, True)
            else:
                scan_result = self._scan_open_space(context, settings, now)
                if scan_result is None:
                    if now - self._last_scan_ts < scan_interval_s:
                        if obstacle:
                            nav_action = avoid_action
                        else:
                            nav_action = safe_action
                    else:
                        self._last_scan_ts = now
                        nav_action = safe_action
                else:
                    direction, score, confirmed = scan_result
                    logger.info(
                        "Navigation scan: dir=%s score=%.1f confirmed=%s",
                        direction,
                        score,
                        confirmed,
                    )
                    low_confidence_cooldown = _safe_float(
                        settings.get("low_confidence_cooldown_s", 0.8), 0.8
                    )
                    retry_limit = _safe_int(settings.get("scan_retry_limit", 2), 2)
                    if not confirmed:
                        self._last_low_confidence_ts = now
                        self._low_confidence_retries += 1
                    else:
                        self._low_confidence_retries = 0
                    if now - self._last_low_confidence_ts < low_confidence_cooldown:
                        if self._low_confidence_retries <= retry_limit:
                            pass
                        elif obstacle:
                            nav_action = avoid_action
                            self._record_no_go(direction, now)
                        else:
                            nav_action = safe_action
                    elif not confirmed and obstacle:
                        nav_action = avoid_action
                        self._record_no_go(direction, now)
                    else:
                        # Detect approach events by comparing the forward baseline to current distance.
                        approaching = False
                        base_fwd = self._baseline_cm.get(
                            0, distance if isinstance(distance, (int, float)) else None
                        )
                        if isinstance(base_fwd, (int, float)) and isinstance(distance, (int, float)):
                            delta = max(0.0, base_fwd - distance)
                            pct = (delta / base_fwd) if base_fwd > 1e-6 else 0.0
                            approaching = (delta >= approach_delta_cm) or (pct >= approach_delta_pct)

                        # Confirm approach events via vote window to avoid noise.
                        approach_window = max(
                            1, _safe_int(settings.get("approach_confirm_window", 3), 3)
                        )
                        if self._approach_votes.maxlen != approach_window:
                            self._approach_votes = deque(self._approach_votes, maxlen=approach_window)
                        self._approach_votes.append(bool(approaching))
                        approach_confirmed = (
                            sum(1 for v in self._approach_votes if v)
                            >= _safe_int(settings.get("approach_confirm_threshold", 2), 2)
                        )

                        if approach_confirmed and now - self._last_approach_ts >= approach_cooldown_s:
                            nav_action = avoid_action
                            nav_followup = {
                                "type": "retreat_turn",
                                "backup_steps": backup_steps,
                                "direction": retreat_turn_direction,
                            }
                            nav_led = "retreat"
                            self._record_no_go(direction, now)
                            self._last_approach_ts = now
                            self._record_avoidance(now)
                        elif self._check_stuck(context, settings, now):
                            self._apply_avoidance_strategy(context, settings, avoid_action)
                            self._record_avoidance(now)
                            self._stuck_count += 1
                            stuck_recovery = {
                                "timestamp": now,
                                "count": self._stuck_count,
                                "strategy": self._last_strategy,
                            }
                            # Activate gentle recovery if threshold reached and not already active
                            if (
                                not self._gentle_recovery_active
                                and self._stuck_count >= gentle_recovery_threshold
                            ):
                                self._gentle_recovery_active = True
                                self._gentle_recovery_until = now + gentle_recovery_cooldown
                        else:
                            direction = self._apply_no_go_bias(direction, now, settings)
                            if direction == "left":
                                # First consult the lightweight occupancy grid (if enabled),
                                # then apply the higher-level mapping bias and SLAM hints.
                                direction = self._apply_grid_bias(context, settings, direction)
                                direction = self._apply_mapping_bias(context, settings, direction)
                                direction = self._apply_slam_bias(context, settings, direction)
                                if self._is_dead_end(direction):
                                    direction = "right"
                                if self._turn_cooldown_active(settings):
                                    direction = "forward"
                                nav_turn = {"direction": direction, "degrees": turn_degrees_on_gap}
                                nav_action = "turn left"
                                nav_led = "turn"
                                self._record_turn(direction)
                            elif direction == "right":
                                direction = self._apply_grid_bias(context, settings, direction)
                                direction = self._apply_mapping_bias(context, settings, direction)
                                direction = self._apply_slam_bias(context, settings, direction)
                                if self._is_dead_end(direction):
                                    direction = "left"
                                if self._turn_cooldown_active(settings):
                                    direction = "forward"
                                nav_turn = {"direction": direction, "degrees": turn_degrees_on_gap}
                                nav_action = "turn right"
                                nav_led = "turn"
                                self._record_turn(direction)
                            elif isinstance(distance, (int, float)) and distance < safe_distance_cm:
                                nav_action = avoid_action
                                nav_led = "obstacle"
                                self._record_no_go("forward", now)
                            else:
                                nav_action = "forward"
                                nav_led = "patrol"
                                self._clear_path_streak += 1
                            emit_decision = (direction, score, confirmed)

        # Set all context state at the end
        if nav_action is not None:
            context.set("navigation_action", nav_action)
        if nav_turn is not None:
            context.set("navigation_turn", nav_turn)
        if nav_led is not None:
            self._set_nav_led(context, nav_led)
        if nav_followup is not None:
            context.set("navigation_followup", nav_followup)
        if emit_decision is not None:
            self._emit_navigation_decision(context, settings, *emit_decision)
        if stuck_recovery is not None:
            context.set("stuck_recovery", stuck_recovery)

        # Always set gentle recovery state at the END of tick, using latest time
        now = time.time()
        if self._gentle_recovery_active or now < self._gentle_recovery_until:
            if now >= self._gentle_recovery_until:
                self._gentle_recovery_active = False
                self._stuck_count = 0
                context.set("gentle_recovery_active", False)
                context.set("energy_speed_hint", None)
            else:
                context.set("gentle_recovery_active", True)
                context.set("gentle_recovery_until", self._gentle_recovery_until)
                context.set("energy_speed_hint", "slow")
        else:
            context.set("gentle_recovery_active", False)
            context.set("energy_speed_hint", None)

        # Emergency retreat if obstacle is too close.
        if isinstance(distance, (int, float)) and 0 < distance <= emergency_stop_cm:
            context.set("navigation_action", avoid_action)
            self._record_no_go("forward", now)
            logger.info(
                "Navigation emergency retreat: %s (distance=%s)", avoid_action, distance
            )
            return

        clear_streak_min = _safe_int(settings.get("clear_path_streak_min", 0), 0)
        if (
            not obstacle
            and clear_streak_min > 0
            and self._clear_path_streak >= clear_streak_min
        ):
            if settings.get("clear_path_skip_scans", True):
                context.set("navigation_action", "forward")
                self._set_nav_led(context, "patrol")
                self._clear_path_streak += 1
                self._emit_navigation_decision(context, settings, "forward", 0.0, True)
                return

        scan_result = self._scan_open_space(context, settings, now)
        if scan_result is None:
            if now - self._last_scan_ts < scan_interval_s:
                if obstacle:
                    context.set("navigation_action", avoid_action)
                else:
                    context.set("navigation_action", safe_action)
                return
            self._last_scan_ts = now
            context.set("navigation_action", safe_action)
            return

        direction, score, confirmed = scan_result
        logger.info(
            "Navigation scan: dir=%s score=%.1f confirmed=%s",
            direction,
            score,
            confirmed,
        )

        low_confidence_cooldown = _safe_float(
            settings.get("low_confidence_cooldown_s", 0.8), 0.8
        )
        retry_limit = _safe_int(settings.get("scan_retry_limit", 2), 2)
        if not confirmed:
            self._last_low_confidence_ts = now
            self._low_confidence_retries += 1
        else:
            self._low_confidence_retries = 0
        if now - self._last_low_confidence_ts < low_confidence_cooldown:
            if self._low_confidence_retries <= retry_limit:
                return
            if obstacle:
                context.set("navigation_action", avoid_action)
                self._record_no_go(direction, now)
                return
            context.set("navigation_action", safe_action)
            return

        if not confirmed and obstacle:
            context.set("navigation_action", avoid_action)
            self._record_no_go(direction, now)
            return

        # Detect approach events by comparing the forward baseline to current distance.
        approaching = False
        base_fwd = self._baseline_cm.get(
            0, distance if isinstance(distance, (int, float)) else None
        )
        if isinstance(base_fwd, (int, float)) and isinstance(distance, (int, float)):
            delta = max(0.0, base_fwd - distance)
            pct = (delta / base_fwd) if base_fwd > 1e-6 else 0.0
            approaching = (delta >= approach_delta_cm) or (pct >= approach_delta_pct)

        # Confirm approach events via vote window to avoid noise.
        approach_window = max(1, _safe_int(settings.get("approach_confirm_window", 3), 3))
        if self._approach_votes.maxlen != approach_window:
            self._approach_votes = deque(self._approach_votes, maxlen=approach_window)
        self._approach_votes.append(bool(approaching))
        approach_confirmed = (
            sum(1 for v in self._approach_votes if v)
            >= _safe_int(settings.get("approach_confirm_threshold", 2), 2)
        )

        if approach_confirmed and now - self._last_approach_ts >= approach_cooldown_s:
            context.set("navigation_action", avoid_action)
            context.set(
                "navigation_followup",
                {
                    "type": "retreat_turn",
                    "backup_steps": backup_steps,
                    "direction": retreat_turn_direction,
                },
            )
            self._set_nav_led(context, "retreat")
            self._record_no_go(direction, now)
            self._last_approach_ts = now
            self._record_avoidance(now)
            return

        if self._check_stuck(context, settings, now):
            self._apply_avoidance_strategy(context, settings, avoid_action)
            self._record_avoidance(now)
            self._stuck_count += 1
            context.set(
                "stuck_recovery",
                {
                    "timestamp": now,
                    "count": self._stuck_count,
                    "strategy": self._last_strategy,
                },
            )
            # Activate gentle recovery if threshold reached and not already active
            if (
                not self._gentle_recovery_active
                and self._stuck_count >= gentle_recovery_threshold
            ):
                self._gentle_recovery_active = True
                self._gentle_recovery_until = now + gentle_recovery_cooldown
            return

        direction = self._apply_no_go_bias(direction, now, settings)

        if direction == "left":
            direction = self._apply_mapping_bias(context, settings, direction)
            direction = self._apply_slam_bias(context, settings, direction)
            if self._is_dead_end(direction):
                direction = "right"
            if self._turn_cooldown_active(settings):
                direction = "forward"
            context.set(
                "navigation_turn",
                {"direction": direction, "degrees": turn_degrees_on_gap},
            )
            context.set("navigation_action", "turn left")
            self._set_nav_led(context, "turn")
            self._record_turn(direction)
        elif direction == "right":
            direction = self._apply_mapping_bias(context, settings, direction)
            direction = self._apply_slam_bias(context, settings, direction)
            if self._is_dead_end(direction):
                direction = "left"
            if self._turn_cooldown_active(settings):
                direction = "forward"
            context.set(
                "navigation_turn",
                {"direction": direction, "degrees": turn_degrees_on_gap},
            )
            context.set("navigation_action", "turn right")
            self._set_nav_led(context, "turn")
            self._record_turn(direction)
        elif isinstance(distance, (int, float)) and distance < safe_distance_cm:
            context.set("navigation_action", avoid_action)
            self._set_nav_led(context, "obstacle")
            self._record_no_go("forward", now)
        else:
            context.set("navigation_action", "forward")
            self._set_nav_led(context, "patrol")
            self._clear_path_streak += 1

        self._emit_navigation_decision(context, settings, direction, score, confirmed)

    def _scan_open_space(
        self, context, settings, now: float
    ) -> tuple[str, float, bool] | None:
        """Select a direction using the latest scan data.

        Returns (direction, score, confirmed) where direction is left/right/forward.
        """
        scan_reading = context.get("scan_reading")
        scan_service = context.get("scan_service")
        scan_stale_s = float(
            settings.get("scan_stale_s", settings.get("scan_interval_s", 0.5))
        )

        if scan_reading is not None:
            reading_ts = getattr(scan_reading, "timestamp", 0.0)
            if now - float(reading_ts) <= scan_stale_s:
                return self._process_scan(scan_reading, settings)

        if scan_service is None:
            return None

        try:
            # Avoid performing potentially blocking, on-demand scans from the
            # navigation tick path. Prefer the scanning service's latest
            # background reading (if available) to keep the tick short. If no
            # latest reading is available, return None so navigation falls back
            # to safe_action instead of blocking on head movement and sleeps.
            latest = None
            try:
                latest = scan_service.latest()
            except Exception:
                latest = None
            if latest is None:
                return None
            reading = latest
            context.set("scan_reading", reading)
            context.set("scan_latest", reading.to_dict())
            return self._process_scan(reading, settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("On-demand scan processing failed: %s", exc)
            return None

    def _process_scan(self, reading, settings) -> tuple[str, float, bool] | None:
        yaw_max = _safe_int(settings.get("scan_yaw_max_deg", 60), 60)
        ema_alpha = _safe_float(settings.get("baseline_ema", 0.25), 0.25)
        min_gap_width_deg = _safe_int(settings.get("min_gap_width_deg", 30), 30)
        min_score_cm = _safe_float(settings.get("min_score_cm", 60), 60)
        confirm_window = max(1, _safe_int(settings.get("confirm_window", 2), 2))
        confirm_threshold = max(1, _safe_int(settings.get("confirm_threshold", 2), 2))
        turn_confidence_min = _safe_float(settings.get("turn_confidence_min", 0.6), 0.6)
        min_valid_points = _safe_int(settings.get("scan_min_valid_points", 3), 3)
        min_valid_ratio = _safe_float(settings.get("scan_min_valid_ratio", 0.5), 0.5)

        mode = getattr(reading, "mode", "three_way")
        data = getattr(reading, "data", {})
        distances: dict[int, float] = {}
        if mode == "sweep":
            distances = {int(k): _safe_float(v, 0.0) for k, v in data.items()}
            angles = sorted(distances.keys())
        else:
            left = _safe_float(data.get("left", 0.0), 0.0)
            right = _safe_float(data.get("right", 0.0), 0.0)
            forward = _safe_float(data.get("forward", 0.0), 0.0)
            distances = {-yaw_max: left, 0: forward, yaw_max: right}
            angles = [-yaw_max, 0, yaw_max]

        if not angles:
            return None

        valid_points = sum(1 for _, dist in distances.items() if dist > 0)
        if valid_points < min_valid_points:
            return None
        if valid_points / max(1, len(distances)) < min_valid_ratio:
            return None

        for yaw, dist in distances.items():
            base = self._baseline_cm.get(yaw)
            self._baseline_cm[yaw] = (
                dist if base is None else (1 - ema_alpha) * base + ema_alpha * dist
            )

        best_angle, score = self._find_best_cluster(
            angles, distances, min_gap_width_deg, min_score_cm
        )
        direction = "forward"
        if best_angle < 0:
            direction = "left"
        elif best_angle > 0:
            direction = "right"

        if self._confirm_votes.maxlen != confirm_window:
            self._confirm_votes = deque(self._confirm_votes, maxlen=confirm_window)
        self._confirm_votes.append(direction)
        counts = Counter(self._confirm_votes)
        confirm_count = counts.get(direction, 0)
        confirmed = confirm_count >= confirm_threshold
        if confirm_window > 0:
            confidence = confirm_count / confirm_window
            if confidence < turn_confidence_min:
                confirmed = False

        return direction, score, confirmed

    def _emit_navigation_decision(
        self, context, settings, direction: str, score: float, confirmed: bool
    ) -> None:
        if not settings.get("log_decision_enabled", True):
            return
        now = time.time()
        decision = {
            "timestamp": now,
            "direction": direction,
            "score": score,
            "confirmed": confirmed,
            "clear_path_streak": self._clear_path_streak,
            "low_confidence_retries": self._low_confidence_retries,
        }
        if settings.get("log_decision_raw_angles", False):
            scan_latest = context.get("scan_latest") or {}
            if isinstance(scan_latest, dict):
                decision["scan_angles"] = scan_latest.get("angles")
        context.set("navigation_decision", decision)

    def _record_turn(self, direction: str) -> None:
        self._clear_path_streak = 0
        if direction == "left":
            self._dead_end_cache.append(-1)
        elif direction == "right":
            self._dead_end_cache.append(1)
        self._turn_cooldown_ts = time.time()

    def _is_dead_end(self, direction: str) -> bool:
        maxlen = self._dead_end_cache.maxlen
        if maxlen is None or len(self._dead_end_cache) < maxlen:
            return False
        neg = sum(1 for v in self._dead_end_cache if v < 0)
        pos = sum(1 for v in self._dead_end_cache if v > 0)
        if direction == "left" and neg > pos:
            return True
        if direction == "right" and pos > neg:
            return True
        return False

    def _turn_cooldown_active(self, settings) -> bool:
        cooldown = _safe_float(settings.get("turn_cooldown_s", 0.0), 0.0)
        if cooldown <= 0:
            return False
        return (time.time() - self._turn_cooldown_ts) < cooldown

    def _apply_mapping_bias(self, context, settings, fallback: str) -> str:
        if not settings.get("use_mapping_bias", True):
            return fallback
        weight = _safe_float(settings.get("mapping_bias_weight", 0.5), 0.5)
        min_conf = _safe_float(
            settings.get("mapping_bias_min_confidence", 0.6), 0.6
        )
        cooldown = _safe_float(settings.get("mapping_bias_cooldown_s", 1.0), 1.0)
        if weight <= 0:
            return fallback
        now = time.time()
        if now - self._last_mapping_bias_ts < cooldown:
            return fallback
        mapping = context.get("mapping_openings") or {}
        best_path = mapping.get("best_path") if isinstance(mapping, dict) else None
        if not isinstance(best_path, dict):
            return fallback
        try:
            conf = _safe_float(best_path.get("confidence", 0.0), 0.0)
        except Exception:
            conf = 0.0
        if conf < min_conf:
            return fallback
        yaw = _safe_float(best_path.get("yaw", 0.0), 0.0)
        if yaw < 0:
            self._last_mapping_bias_ts = now
            choice = "left" if weight >= 0.5 else fallback
            self._emit_mapping_hint(context, fallback, choice, best_path)
            return choice
        if yaw > 0:
            self._last_mapping_bias_ts = now
            choice = "right" if weight >= 0.5 else fallback
            self._emit_mapping_hint(context, fallback, choice, best_path)
            return choice
        return fallback

    def _apply_grid_bias(self, context, settings, fallback: str) -> str:
        """Use the lightweight occupancy grid to bias turns away from denser sides.

        Returns a direction string (left/right/forward).
        """
        if not settings.get("use_grid_map", True):
            return fallback
        mapping_state = context.get("mapping_state") or {}
        grid = mapping_state.get("grid") or {}
        cells = grid.get("cells") if isinstance(grid, dict) else None
        if not isinstance(cells, dict) or not cells:
            return fallback

        # Depth to consider ahead of robot (cm) and cell size
        cell_size = float(settings.get("grid_cell_size_cm", settings.get("cell_size_cm", 10)))
        depth_cm = float(settings.get("grid_influence_depth_cm", 100))
        depth_cells = max(1, int(depth_cm / max(1.0, cell_size)))

        left_count = 0
        right_count = 0
        # cells keys are "ix,iy" where ix = lateral (left + / right -), iy = forward cells
        for k, v in cells.items():
            try:
                ix_s, iy_s = k.split(",")
                ix = int(ix_s)
                iy = int(iy_s)
            except Exception:
                continue
            if iy < 0 or iy > depth_cells:
                continue
            if ix < 0:
                left_count += int(v or 0)
            elif ix > 0:
                right_count += int(v or 0)

        total = left_count + right_count
        if total <= 0:
            return fallback

        # Choose the side with fewer hits. Apply weight threshold to avoid flip-flopping.
        ratio = (left_count + 1) / (right_count + 1)
        weight = float(settings.get("grid_bias_weight", 0.7))
        # If left is denser, prefer right; if right denser, prefer left.
        if ratio > (1.0 / weight):
            return "right"
        if ratio < weight:
            return "left"
        return fallback

    def _apply_slam_bias(self, context, settings, fallback: str) -> str:
        if not settings.get("slam_nav_enabled", False):
            return fallback
        hint = context.get("slam_nav_hint")
        if not isinstance(hint, dict):
            return fallback
        try:
            confidence = float(hint.get("confidence", 0.0))
        except Exception:
            confidence = 0.0
        min_conf = float(settings.get("slam_nav_min_confidence", 0.3))
        if confidence < min_conf:
            return fallback
        direction = hint.get("direction")
        if direction not in ("left", "right", "forward"):
            return fallback
        if not settings.get("slam_nav_override", True):
            return fallback
        return direction

    @staticmethod
    def _emit_mapping_hint(
        context, fallback: str, chosen: str, best_path: dict
    ) -> None:
        if fallback == chosen:
            return
        context.set(
            "mapping_hint",
            {
                "timestamp": time.time(),
                "fallback": fallback,
                "chosen": chosen,
                "best_path": best_path,
            },
        )
        logger.info("Mapping hint influenced turn: %s -> %s", fallback, chosen)

    def _record_avoidance(self, now: float) -> None:
        self._avoid_history.append(now)

    def _record_no_go(self, direction: str, now: float) -> None:
        if direction not in ("left", "right", "forward"):
            return
        self._no_go_history.append((now, direction))

    def _apply_no_go_bias(self, direction: str, now: float, settings) -> str:
        if direction not in ("left", "right", "forward"):
            return direction
        if not settings.get("no_go_enabled", False):
            return direction
        window_s = float(settings.get("no_go_window_s", 8.0))
        repeat = int(settings.get("no_go_repeat_threshold", 3))
        if repeat <= 0:
            return direction
        recent = [d for ts, d in self._no_go_history if now - ts <= window_s]
        count = sum(1 for d in recent if d == direction)
        if count >= repeat:
            if direction == "left":
                return "right"
            if direction == "right":
                return "left"
        return direction

    def _check_stuck(self, context, settings, now: float) -> bool:
        reading = context.get("sensor_reading")
        acc = getattr(reading, "acc", None) if reading else None
        if acc is None:
            return False
        magnitude = (
            abs(_safe_float(acc[0], 0.0))
            + abs(_safe_float(acc[1], 0.0))
            + abs(_safe_float(acc[2], 0.0))
        )
        self._movement_history.append((now, magnitude))

        window_s = float(settings.get("stuck_time_window_s", 5.0))
        threshold = float(settings.get("stuck_movement_threshold", 1500.0))
        min_samples = int(settings.get("stuck_min_samples", 10))
        cooldown = float(settings.get("stuck_cooldown_s", 6.0))

        while self._movement_history and now - self._movement_history[0][0] > window_s:
            self._movement_history.popleft()
        if len(self._movement_history) < min_samples:
            return False
        avg = sum(val for _, val in self._movement_history) / len(
            self._movement_history
        )
        if avg >= threshold:
            return False
        if now - self._last_stuck_ts < cooldown:
            return False
        self._last_stuck_ts = now
        return True

    def _apply_avoidance_strategy(self, context, settings, avoid_action: str) -> None:
        strategies = settings.get("avoidance_strategies", ["smart_turn"])
        if not isinstance(strategies, list) or not strategies:
            strategies = ["smart_turn"]

        repeat_window = float(settings.get("stuck_strategy_repeat_window_s", 10.0))
        repeat_threshold = int(settings.get("stuck_strategy_repeat_threshold", 3))
        now = time.time()
        recent = [t for t in self._avoid_history if now - t <= repeat_window]
        if len(recent) >= repeat_threshold:
            self._strategy_index = (self._strategy_index + 1) % len(strategies)

        strategy = str(strategies[self._strategy_index])
        self._last_strategy = strategy
        if strategy == "backup_turn":
            context.set("navigation_action", avoid_action)
            context.set(
                "navigation_followup",
                {
                    "type": "retreat_turn",
                    "backup_steps": int(settings.get("backup_steps", 2)),
                    "direction": "auto",
                },
            )
        elif strategy == "zigzag":
            context.set("navigation_action", "turn left")
            context.set(
                "navigation_followup",
                {
                    "type": "sequence",
                    "actions": ["turn right", "turn left", "forward"],
                },
            )
        elif strategy == "reverse_escape":
            context.set("navigation_action", "backward")
            context.set(
                "navigation_followup",
                {
                    "type": "sequence",
                    "actions": ["backward", "turn left", "turn right"],
                },
            )
        else:
            context.set("navigation_action", "turn left")

    @staticmethod
    def _set_nav_led(context, mode: str) -> None:
        """Emit navigation LED request for the LED manager."""
        settings = (context.get("settings") or {}).get("navigation", {})
        if not settings.get("led_enabled", True):
            return
        context.set(
            "led_request:navigation",
            {
                "timestamp": time.time(),
                "mode": mode,
                "priority": int(settings.get("led_priority", 50)),
            },
        )

    @staticmethod
    def _find_best_cluster(
        angles: list[int],
        distances: dict[int, float],
        min_gap_deg: int,
        min_score_cm: float,
    ) -> tuple[int, float]:
        """Return the center angle for the most open cluster.

        Score = gap width (deg) * average distance (cm).
        """
        best_angle = 0
        best_score = -1.0
        i = 0
        n = len(angles)
        step_deg = abs(angles[1] - angles[0]) if len(angles) > 1 else min_gap_deg

        while i < n:
            if distances.get(angles[i], 0.0) >= min_score_cm:
                j = i
                total = 0.0
                count = 0
                while j < n and distances.get(angles[j], 0.0) >= min_score_cm:
                    total += distances.get(angles[j], 0.0)
                    count += 1
                    j += 1
                width_deg = count * step_deg
                if width_deg >= min_gap_deg and count > 0:
                    avg = total / count
                    center_idx = i + (count // 2)
                    center_angle = angles[center_idx]
                    score = width_deg * avg
                    if score > best_score:
                        best_score = score
                        best_angle = center_angle
                i = j
            else:
                i += 1

        if best_score < 0:
            # Fallback to the maximum distance angle.
            best_angle = max(angles, key=lambda a: distances.get(a, -1.0))
            best_score = distances.get(best_angle, 0.0)
        return best_angle, best_score
