"""A real schema for `config/settings.jsonc`.

The previous validator was ~170 lines of ``warnings.append(...)`` that only logged. Nothing
was rejected, so ``tick_hz: "fast"`` loaded, a misspelled key vanished without a word, and —
worst of all — any key placed under ``modules.<name>`` beyond ``enabled``/``required`` was
silently discarded by the config model while still being documented as if it worked.

This module makes a bad config a load-time error with a path and a suggestion, before any
hardware is touched. It is deliberately dependency-free: specs are plain dataclasses, so
validation costs nothing on a Pi and adds nothing to the install.

Scope: `loop`, `modules` and `profiles` are strict today. `settings` is validated
structurally only (it must be a table) and grows section by section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

# The action classes are the command vocabulary's own enum, so the schema and the interlock cannot
# disagree about the four strings. `kernel/commands.py` imports nothing but the stdlib, which is
# what keeps this module's "dependency-free" promise intact.
from houndmind_ai.kernel.commands import ActionClass

__all__ = [
    "AnyValue",
    "Bool",
    "ConfigError",
    "FloatSpec",
    "IntSpec",
    "ListOf",
    "MapOf",
    "Problem",
    "Section",
    "StrSpec",
    "validate_config_tree",
]


@dataclass(frozen=True)
class Problem:
    """One reason a config file was rejected."""

    path: str
    message: str
    hint: str | None = None

    def __str__(self) -> str:
        suffix = f" (did you mean '{self.hint}'?)" if self.hint else ""
        return f"{self.path}: {self.message}{suffix}"


class ConfigError(ValueError):
    """Raised when a config file cannot be accepted."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = list(problems)
        super().__init__(self.format())

    def format(self) -> str:
        if not self.problems:
            return "configuration is invalid"
        lines = [f"configuration has {len(self.problems)} problem(s):"]
        lines.extend(f"  - {problem}" for problem in self.problems)
        return "\n".join(lines)


# --------------------------------------------------------------------------- specs


class Spec:
    """Base spec. Subclasses return (normalised_value, problems)."""

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        raise NotImplementedError


@dataclass(frozen=True)
class AnyValue(Spec):
    """Pass-through, for sections that are only checked for being the right shape."""

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        return value, []


@dataclass(frozen=True)
class Bool(Spec):
    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if isinstance(value, bool):
            return value, []
        return value, [Problem(path, f"expected true or false, got {value!r}")]


@dataclass(frozen=True)
class IntSpec(Spec):
    minimum: int | None = None
    maximum: int | None = None
    allow_none: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if value is None and self.allow_none:
            return None, []
        # bool is an int subclass; `"enabled": true` is not a tick rate.
        if isinstance(value, bool) or not isinstance(value, int):
            return value, [Problem(path, f"expected an integer, got {value!r}")]
        if self.minimum is not None and value < self.minimum:
            return value, [Problem(path, f"must be >= {self.minimum}, got {value}")]
        if self.maximum is not None and value > self.maximum:
            return value, [Problem(path, f"must be <= {self.maximum}, got {value}")]
        return value, []


@dataclass(frozen=True)
class FloatSpec(Spec):
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    allow_none: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if value is None and self.allow_none:
            return None, []
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value, [Problem(path, f"expected a number, got {value!r}")]
        number = float(value)
        if number != number:  # NaN
            return value, [Problem(path, "must be a real number, got NaN")]
        if self.minimum is not None:
            if self.exclusive_minimum and number <= self.minimum:
                return value, [Problem(path, f"must be > {self.minimum}, got {number}")]
            if not self.exclusive_minimum and number < self.minimum:
                return value, [Problem(path, f"must be >= {self.minimum}, got {number}")]
        if self.maximum is not None and number > self.maximum:
            return value, [Problem(path, f"must be <= {self.maximum}, got {number}")]
        return number, []


@dataclass(frozen=True)
class StrSpec(Spec):
    choices: tuple[str, ...] = ()
    allow_none: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if value is None and self.allow_none:
            return None, []
        if not isinstance(value, str):
            return value, [Problem(path, f"expected a string, got {value!r}")]
        if self.choices and value not in self.choices:
            suggestion = get_close_matches(value, self.choices, n=1)
            return value, [
                Problem(
                    path,
                    f"must be one of {', '.join(self.choices)}, got {value!r}",
                    suggestion[0] if suggestion else None,
                )
            ]
        return value, []


@dataclass(frozen=True)
class ListOf(Spec):
    item: Spec = field(default_factory=AnyValue)
    # Fixed-length lists exist: `mapping.grid_size` is indexed as `[0]` and `[1]`.
    length: int | None = None
    allow_none: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if value is None and self.allow_none:
            return None, []
        if not isinstance(value, list):
            return value, [Problem(path, f"expected a list, got {value!r}")]
        problems: list[Problem] = []
        if self.length is not None and len(value) != self.length:
            return value, [
                Problem(path, f"expected {self.length} entries, got {len(value)}")
            ]
        out: list[Any] = []
        for index, entry in enumerate(value):
            normalised, found = self.item.validate(entry, f"{path}[{index}]")
            out.append(normalised)
            problems.extend(found)
        return out, problems


@dataclass(frozen=True)
class MapOf(Spec):
    """A table whose keys are user-chosen: module names, profile names, section names."""

    value: Spec = field(default_factory=AnyValue)

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if not isinstance(value, dict):
            return value, [Problem(path, f"expected a table, got {value!r}")]
        problems: list[Problem] = []
        out: dict[str, Any] = {}
        for key, entry in value.items():
            if not isinstance(key, str):
                problems.append(Problem(path, f"keys must be strings, got {key!r}"))
                continue
            normalised, found = self.value.validate(entry, f"{path}.{key}")
            out[key] = normalised
            problems.extend(found)
        return out, problems


@dataclass(frozen=True)
class Section(Spec):
    """A fixed-shape table. Unknown keys are an error, with a suggestion."""

    fields: dict[str, Spec] = field(default_factory=dict)
    allow_extra: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if not isinstance(value, dict):
            return value, [Problem(path, f"expected a table, got {value!r}")]
        problems: list[Problem] = []
        out: dict[str, Any] = {}
        known = list(self.fields)
        for key, entry in value.items():
            if key not in self.fields:
                if self.allow_extra:
                    out[key] = entry
                    continue
                suggestion = get_close_matches(str(key), known, n=1)
                problems.append(
                    Problem(
                        f"{path}.{key}",
                        "unknown key; it would be ignored",
                        suggestion[0] if suggestion else None,
                    )
                )
                continue
            normalised, found = self.fields[key].validate(entry, f"{path}.{key}")
            out[key] = normalised
            problems.extend(found)
        return out, problems


# ------------------------------------------------------------------ tree schema

_LOOP = Section(
    fields={
        "tick_hz": IntSpec(minimum=1, maximum=100),
        # None means "run until stopped", which is the only sane default for a service.
        "max_cycles": IntSpec(minimum=1, allow_none=True),
    }
)

_MODULE_ENTRY = Section(fields={"enabled": Bool(), "required": Bool()})

# ------------------------------------------------------------- settings sections
#
# `settings` used to be checked only for being a table, so a typo in a section name read as
# `{}` at every consumer and the value was re-coerced ad hoc where it was finally used (H-08).
# Each section below is a transcription of what its consumers actually read — the key set is
# the union of the shipped file and the code — so a key nothing reads, or a value of the wrong
# type, is rejected at load instead of at 3 a.m. on the dog.

# Reusable bounds. A servo speed is a PWM duty in percent, a yaw limit is a head angle, a
# filter coefficient is a fraction. Naming them once keeps the sections readable.
_FRACTION = FloatSpec(minimum=0.0, maximum=1.0)
_ALPHA = FloatSpec(minimum=0.0, maximum=1.0, exclusive_minimum=True)
_NON_NEGATIVE = FloatSpec(minimum=0.0)
_POSITIVE = FloatSpec(minimum=0.0, exclusive_minimum=True)
_SERVO_SPEED = IntSpec(minimum=0, maximum=255)
_PRIORITY = IntSpec(minimum=0, maximum=100)
_NAMES = ListOf(StrSpec())
_NULLABLE_STR = StrSpec(allow_none=True)

# `hal/sensors.py` — SensorService reads one key per knob, each through `_safe_float`/
# `_safe_int`, so ints are accepted where a float is wanted and normalised here.
_SENSORS = Section(
    fields={
        "poll_hz": _POSITIVE,
        "history_size": IntSpec(minimum=1),
        "enable_ultrasonic": Bool(),
        "enable_touch": Bool(),
        "enable_sound": Bool(),
        "enable_imu": Bool(),
        "distance_samples": IntSpec(minimum=1),
        "distance_sample_delay_s": _NON_NEGATIVE,
        "distance_use_median": Bool(),
        "distance_debounce_s": _NON_NEGATIVE,
        "distance_min_cm": _NON_NEGATIVE,
        "distance_max_cm": _NON_NEGATIVE,
        "distance_outlier_reject_z": _NON_NEGATIVE,
        "distance_ema_alpha": _FRACTION,
        "touch_debounce_s": _NON_NEGATIVE,
        "sound_direction_on_detect": Bool(),
        "imu_lpf_alpha": _FRACTION,
    }
)

# `hal/motors.py` — the action cooldown and the head-follow behaviour.
_MOTORS = Section(
    fields={
        "min_action_interval_s": _NON_NEGATIVE,
        "head_turn_follow_enabled": Bool(),
        "head_turn_follow_deg": FloatSpec(minimum=0.0, maximum=180.0),
        "head_turn_follow_speed": _SERVO_SPEED,
        "head_turn_follow_hold_s": _NON_NEGATIVE,
        "head_turn_follow_respect_scanning": Bool(),
        "head_turn_follow_scan_block_s": _NON_NEGATIVE,
        "head_turn_follow_respect_attention": Bool(),
        "head_turn_follow_attention_block_s": _NON_NEGATIVE,
    }
)

# `safety/sensor_health.py` — stale thresholds and the LED colours it asks for.
_SENSOR_HEALTH = Section(
    fields={
        "enabled": Bool(),
        "led_ok_color": StrSpec(),
        "led_warning_color": StrSpec(),
        "led_error_color": StrSpec(),
        "log_enabled": Bool(),
        "ultrasonic_stale_s": _NON_NEGATIVE,
        "imu_stale_s": _NON_NEGATIVE,
        "touch_stale_s": _NON_NEGATIVE,
        "sound_stale_s": _NON_NEGATIVE,
        "error_is_critical": Bool(),
    }
)

# `safety/watchdog.py` + `kernel/supervisor.py`. One policy for "the machine is not well": hold
# motion when the data is stale, restart modules that stopped ticking with exponential backoff.
# `restart_cooldown_s` is the *base* delay of that backoff, not a flat one.
_WATCHDOG = Section(
    fields={
        "enabled": Bool(),
        "sensor_timeout_s": _POSITIVE,
        "scan_timeout_s": _POSITIVE,
        "module_timeout_s": _POSITIVE,
        "monitor_modules": _NAMES,
        "ignore_modules": _NAMES,
        "restart_cooldown_s": _NON_NEGATIVE,
        "restart_backoff_factor": FloatSpec(minimum=1.0),
        "restart_max_delay_s": _NON_NEGATIVE,
        "max_restarts": IntSpec(minimum=0),
        "healthy_after_s": _NON_NEGATIVE,
    }
)

# `safety/balance.py` — posture compensation while walking.
_BALANCE = Section(
    fields={
        "enabled": Bool(),
        "update_hz": _NON_NEGATIVE,
        "compensation_scale": _NON_NEGATIVE,
        "max_pitch_deg": _POSITIVE,
        "max_roll_deg": _POSITIVE,
        "lpf_alpha": _ALPHA,
        "active_when_moving": Bool(),
        "active_actions": _NAMES,
    }
)

# `safety/supervisor.py` — the veto thresholds, plus the override precedence list whose
# entries are the producers the supervisor clears, so an unknown name there is dead text.
_SAFETY = Section(
    fields={
        "too_close_cm": _NON_NEGATIVE,
        "emergency_stop_enabled": Bool(),
        "emergency_stop_cm": _NON_NEGATIVE,
        "emergency_stop_action": StrSpec(),
        "emergency_stop_cooldown_s": _NON_NEGATIVE,
        "emergency_stop_use_hardware_stop": Bool(),
        "tilt_threshold_deg": _POSITIVE,
        "tilt_action": StrSpec(),
        "tilt_cooldown_s": _NON_NEGATIVE,
        "led_priority": _PRIORITY,
        "override_priority": ListOf(
            StrSpec(choices=("safety", "watchdog", "navigation", "behavior"))
        ),
        "override_clear_lower": Bool(),
    }
)

# `core/logging_setup.py` + `logging/event_logger.py` + `safety/health_monitor.py`. The
# legacy aliases (`log_file`, `level`, `backup_count`, `context`) are still accepted by
# `setup_logging` for direct callers, but they are not config keys any more: the shipped
# names are the documented ones, and a file using an old spelling gets a did-you-mean.
_LOGGING = Section(
    fields={
        "enable_console": Bool(),
        "enable_file": Bool(),
        "log_dir": StrSpec(),
        "log_file_name": StrSpec(),
        "console_level": StrSpec(choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
        "log_level": StrSpec(choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
        "log_file_max_mb": IntSpec(minimum=1),
        "log_file_backups": IntSpec(minimum=0),
        "log_max_entries": IntSpec(minimum=1),
        "status_log_enabled": Bool(),
        "status_log_interval_s": _NON_NEGATIVE,
        "event_log_enabled": Bool(),
        "event_log_interval_s": _NON_NEGATIVE,
        "event_log_max_entries": IntSpec(minimum=1),
        "event_log_file_enabled": Bool(),
        "event_log_path": StrSpec(),
        "event_log_max_mb": IntSpec(minimum=1),
        # The decision feed: its own flag and file, because `/decisions` must keep working on a
        # device that turned the event log off. The file defaults to off there (9 MB/hour at
        # 10 Hz); the ring in memory does not.
        "decision_log_enabled": Bool(),
        "decision_log_file_enabled": Bool(),
        "decision_log_max_entries": IntSpec(minimum=1),
        "decision_log_path": StrSpec(),
        "decision_log_max_mb": IntSpec(minimum=1),
    }
)

# `core/runtime.py`, `navigation/scanning.py`, `safety/health_monitor.py`. `runtime_ema_alpha`
# was read by the runtime but shipped nowhere, which is how a knob becomes folklore; it is a
# real key now, spelled out in the shipped file. `health_actions` names the levers
# `health_monitor` knows how to pull, so the choices mirror that branch.
_PERFORMANCE = Section(
    fields={
        "scan_interval_min_s": _NON_NEGATIVE,
        "scan_interval_max_s": _NON_NEGATIVE,
        "sensor_poll_hz_max": _POSITIVE,
        "health_load_per_core_warn_multiplier": _POSITIVE,
        "health_temp_warn_c": _POSITIVE,
        "health_gpu_temp_warn_c": _POSITIVE,
        "health_mem_used_warn_pct": FloatSpec(minimum=0.0, maximum=100.0),
        "health_monitor_interval_s": _POSITIVE,
        "health_scan_interval_multiplier": _POSITIVE,
        "health_scan_interval_abs_delta": _NON_NEGATIVE,
        "health_vision_frame_interval_multiplier": _POSITIVE,
        "health_vision_frame_interval_abs_delta": _NON_NEGATIVE,
        "health_actions": ListOf(StrSpec(choices=("throttle_scans", "throttle_vision"))),
        "safe_mode_enabled": Bool(),
        "safe_mode_scan_interval_s": _POSITIVE,
        "safe_mode_turn_speed": _SERVO_SPEED,
        "runtime_tick_warn_s": _POSITIVE,
        "runtime_ema_alpha": _ALPHA,
    }
)

# `behavior/fsm.py` — the low-battery override. Both thresholds may be null, which means
# "do not threshold on this signal".
_BATTERY = Section(
    fields={
        "enabled": Bool(),
        "low_voltage_v": FloatSpec(minimum=0.0, allow_none=True),
        "low_percent": FloatSpec(minimum=0.0, maximum=100.0, allow_none=True),
        "behavior_override": StrSpec(),
    }
)

# `core/runtime.py` + `navigation/scanning.py` + `hal/motors.py` — the night window and the
# slower intervals that apply inside it.
# Routine files are user data outside the tracked tree (`kernel/routine_store.py` owns the reader).
# The key exists so a device can point the runner at a different directory without editing code.
_ROUTINES = Section(fields={"dir": StrSpec()})


_QUIET_MODE = Section(
    fields={
        "enabled": Bool(),
        "start_hour": IntSpec(minimum=0, maximum=23),
        "end_hour": IntSpec(minimum=0, maximum=23),
        "scan_interval_s": _POSITIVE,
        "behavior_action_cooldown_s": _NON_NEGATIVE,
        "motor_min_action_interval_s": _NON_NEGATIVE,
    }
)

# `behavior/attention.py` — how far the head may turn towards a sound.
_ATTENTION = Section(
    fields={
        "enabled": Bool(),
        "sound_cooldown_s": _NON_NEGATIVE,
        "head_yaw_max_deg": FloatSpec(minimum=0.0, maximum=90.0, exclusive_minimum=True),
        "head_turn_speed": _SERVO_SPEED,
        "respect_scanning": Bool(),
        "scan_block_s": _NON_NEGATIVE,
        "led_priority": _PRIORITY,
    }
)

# `navigation/scanning.py`, `navigation/obstacle_avoidance.py`, `navigation/local_planner.py`.
# The largest section, and the one where a typo costs the most: the scan and avoidance knobs
# are the difference between "walks past the sofa" and "walks into it". Choices are the names
# `obstacle_avoidance.py` branches on (`scan_mode`, `avoidance_strategies`,
# `retreat_turn_direction`); the rest are numbers whose consumer clamps or coerces them.
_NAVIGATION = Section(
    fields={
        "min_distance_cm": _NON_NEGATIVE,
        "emergency_stop_cm": _NON_NEGATIVE,
        "safe_distance_cm": _NON_NEGATIVE,
        "avoid_action": StrSpec(),
        "safe_action": StrSpec(),
        "scan_interval_s": _POSITIVE,
        "scan_interval_min_s": _NON_NEGATIVE,
        "scan_interval_max_s": _POSITIVE,
        "scan_mode": StrSpec(choices=("sweep", "three_way")),
        "scan_continuous": Bool(),
        "scan_history_size": IntSpec(minimum=1),
        "scan_samples": IntSpec(minimum=1),
        "scan_stale_s": _POSITIVE,
        "scan_yaw_max_deg": FloatSpec(minimum=0.0, maximum=180.0),
        "scan_step_deg": FloatSpec(minimum=1.0, maximum=180.0),
        "scan_settle_s": _NON_NEGATIVE,
        "scan_between_reads_s": _NON_NEGATIVE,
        "scan_min_valid_points": IntSpec(minimum=1),
        "scan_min_valid_ratio": _ALPHA,
        "baseline_ema": _FRACTION,
        "min_gap_width_deg": FloatSpec(minimum=0.0, maximum=360.0),
        "min_score_cm": _NON_NEGATIVE,
        "confirm_window": IntSpec(minimum=1),
        "confirm_threshold": IntSpec(minimum=1),
        "turn_confidence_min": _ALPHA,
        "low_confidence_cooldown_s": _NON_NEGATIVE,
        "scan_retry_limit": IntSpec(minimum=0),
        "no_go_enabled": Bool(),
        "no_go_window_s": _POSITIVE,
        "no_go_repeat_threshold": IntSpec(minimum=1),
        "head_scan_speed": _SERVO_SPEED,
        "approach_delta_cm": _NON_NEGATIVE,
        "approach_delta_pct": _FRACTION,
        "approach_confirm_window": IntSpec(minimum=1),
        "approach_confirm_threshold": IntSpec(minimum=1),
        "approach_cooldown_s": _NON_NEGATIVE,
        "backup_steps": IntSpec(minimum=0, maximum=20),
        "turn_degrees_on_gap": FloatSpec(minimum=0.0, maximum=180.0),
        "retreat_turn_direction": StrSpec(choices=("auto", "left", "right")),
        "turn_cooldown_s": _NON_NEGATIVE,
        "clear_path_streak_min": IntSpec(minimum=0),
        "clear_path_skip_scans": Bool(),
        "use_mapping_bias": Bool(),
        "mapping_bias_weight": _FRACTION,
        "mapping_bias_min_confidence": _ALPHA,
        "mapping_bias_cooldown_s": _NON_NEGATIVE,
        "use_grid_map": Bool(),
        "grid_cell_size_cm": _POSITIVE,
        "grid_influence_depth_cm": _POSITIVE,
        "grid_bias_weight": _FRACTION,
        "slam_nav_enabled": Bool(),
        "slam_nav_override": Bool(),
        "slam_nav_min_confidence": _ALPHA,
        "log_decision_enabled": Bool(),
        "log_decision_raw_angles": Bool(),
        "planner_enabled": Bool(),
        "planner_min_confidence": _ALPHA,
        "planner_max_age_s": _POSITIVE,
        "stuck_time_window_s": _POSITIVE,
        "stuck_movement_threshold": _POSITIVE,
        "stuck_min_samples": IntSpec(minimum=1),
        "stuck_cooldown_s": _NON_NEGATIVE,
        "stuck_strategy_repeat_window_s": _NON_NEGATIVE,
        "stuck_strategy_repeat_threshold": IntSpec(minimum=1),
        "avoidance_strategies": ListOf(
            StrSpec(choices=("smart_turn", "backup_turn", "zigzag", "reverse_escape"))
        ),
        # Read by the module but shipped nowhere until now: the gentle-recovery counters were
        # the example in B-07 of documentation describing a knob nothing loaded.
        "gentle_recovery_stuck_count": IntSpec(minimum=1),
        "gentle_recovery_cooldown_s": _NON_NEGATIVE,
        "led_enabled": Bool(),
        "led_priority": _PRIORITY,
        "led_patrol_color": StrSpec(),
        "led_turn_color": StrSpec(),
        "led_obstacle_color": StrSpec(),
        "led_retreat_color": StrSpec(),
    }
)

# `mapping/mapper.py` — openings, the occupancy grid and safe-path scoring.
_MAPPING = Section(
    fields={
        "enabled": Bool(),
        "path_planning_enabled": Bool(),
        "sample_history_max": IntSpec(minimum=1),
        "sample_max_age_s": _NON_NEGATIVE,
        "home_map_enabled": Bool(),
        "home_map_max_samples": IntSpec(minimum=0),
        "home_map_max_age_s": _NON_NEGATIVE,
        "home_map_save_interval_s": _NON_NEGATIVE,
        "home_map_path": StrSpec(),
        "cell_size_cm": _POSITIVE,
        "grid_enabled": Bool(),
        # Indexed as [0] and [1]; a third entry or a scalar is a broken map, not a big one.
        "grid_size": ListOf(IntSpec(minimum=1), length=2),
        "opening_min_width_cm": _NON_NEGATIVE,
        "opening_max_width_cm": _NON_NEGATIVE,
        "opening_cell_conf_min": _FRACTION,
        "safe_path_min_width_cm": _NON_NEGATIVE,
        "safe_path_max_width_cm": _NON_NEGATIVE,
        "safe_path_cell_conf_min": _FRACTION,
        "safe_path_score_weight_width": _FRACTION,
        "safe_path_score_weight_distance": _FRACTION,
    }
)

# `hal/motors.py` + `core/config.py`. `speed_normal` never reaches a servo: it is the walking
# reference the turn speeds are compared against, which is why it stays a plain number.
_MOVEMENT = Section(
    fields={
        "turn_degrees_per_step": FloatSpec(minimum=0.0, maximum=180.0),
        "speed_normal": _SERVO_SPEED,
        "speed_turn_slow": _SERVO_SPEED,
        "speed_turn_normal": _SERVO_SPEED,
        "speed_turn_fast": _SERVO_SPEED,
    }
)

# `navigation/orientation.py` + `hal/motors.py`. `gyro_scale` and `bias_z` are signed on
# purpose: a negative scale is how an inverted IMU mount gets corrected.
_ORIENTATION = Section(
    fields={
        "gyro_scale": FloatSpec(),
        "bias_z": FloatSpec(),
        "calibration_enabled": Bool(),
        "calibration_settle_s": _NON_NEGATIVE,
        "calibration_duration_s": _POSITIVE,
        "calibration_samples": IntSpec(minimum=1),
        "calibration_max_bias_abs": _NON_NEGATIVE,
        "initial_heading_deg": FloatSpec(minimum=0.0, maximum=360.0),
        "turn_tolerance_deg": FloatSpec(minimum=0.0, maximum=180.0),
        "turn_timeout_s": _POSITIVE,
    }
)

# `calibration/workflow.py` + `hal/motors.py`. `servo_zero_offsets` is user data written by
# the calibration workflow: signed degrees, never defaulted here. `request` is compared against
# the four workflow names, so a typo used to produce a silent "unknown" status.
_CALIBRATION = Section(
    fields={
        "servo_zero_offsets": MapOf(FloatSpec()),
        "auto_apply_servo_offsets": Bool(),
        "persist_enabled": Bool(),
        "persist_path": StrSpec(),
        "request": StrSpec(
            choices=("servo_zero", "wall_follow", "corner_seek", "landmark_align"),
            allow_none=True,
        ),
        "wall_follow_target_distance_cm": _POSITIVE,
        "corner_seek_turn_deg": FloatSpec(minimum=0.0, maximum=180.0),
        "landmark_alignment_confidence_min": _ALPHA,
        "localization_confidence_bump": _FRACTION,
    }
)

# `main.py` — the identity stamped on every log record and reported by `GET /api/v1/meta`.
# The runtime read this key and the file shipped nothing, so an operator had no way to set it
# and the schema would have rejected it the moment the file did ship one.
_DEVICE = Section(
    fields={
        # Empty means "use the hostname", which is the fallback the runtime already applied.
        "device_id": StrSpec(),
    }
)

# `perception/fusion.py`.
_PERCEPTION = Section(
    fields={
        "obstacle_cm": _NON_NEGATIVE,
        "fusion": Section(
            fields={
                "fusion_anchor_distance_cm": _POSITIVE,
                "fusion_min_confidence": _ALPHA,
            }
        ),
    }
)

# `behavior/habituation.py` — the stimulus names index the `perception` dict, so they are
# free-form by design rather than an enum.
_HABITUATION = Section(
    fields={
        "enabled": Bool(),
        "stimuli": _NAMES,
        "window_s": _POSITIVE,
        "threshold": IntSpec(minimum=1),
        "recovery_s": _NON_NEGATIVE,
    }
)

# `behavior/fsm.py` — the autonomy bias multipliers, each a 0-1 trait.
_PERSONALITY = Section(
    fields={
        "curiosity": _FRACTION,
        "sociability": _FRACTION,
        "activity": _FRACTION,
        "apply_to_autonomy": Bool(),
    }
)

# `behavior/fsm.py` + `optional/energy_emotion.py`.
_ENERGY = Section(
    fields={
        "enabled": Bool(),
        "initial": _FRACTION,
        "min": _FRACTION,
        "max": _FRACTION,
        "decay_per_tick": _NON_NEGATIVE,
        "boost_touch": _NON_NEGATIVE,
        "boost_sound": _NON_NEGATIVE,
        "boost_obstacle": _NON_NEGATIVE,
        "speed_slow_threshold": _FRACTION,
        "speed_fast_threshold": _FRACTION,
    }
)

# `optional/energy_emotion.py` + `logging/led_manager.py`.
_EMOTION = Section(
    fields={
        "led_enabled": Bool(),
        "led_priority": _PRIORITY,
        "led_cooldown_s": _NON_NEGATIVE,
        "led_colors": MapOf(StrSpec()),
    }
)

# `logging/led_manager.py`. Colours and effect names are the vendor's vocabulary, which lives
# behind the HAL, so they stay free-form strings here; only the priority order is ours.
_LED = Section(
    fields={
        "enabled": Bool(),
        "priority": ListOf(
            StrSpec(choices=("safety", "navigation", "attention", "emotion"))
        ),
        "cooldown_s": _NON_NEGATIVE,
        "brightness": _FRACTION,
        "default_color": StrSpec(),
        "safety_color": StrSpec(),
        "safety_mode": StrSpec(),
        "attention_color": StrSpec(),
        "attention_mode": StrSpec(),
        "nav_mode": StrSpec(),
        "nav_turn_mode": StrSpec(),
        "nav_obstacle_mode": StrSpec(),
        "nav_retreat_mode": StrSpec(),
        "emotion_mode": StrSpec(),
        "emotion_color": StrSpec(),
        # The rate an effect runs at, per source (`{"safety": 4}`). Absent means "use the HAL's
        # default", which is what every effect did before P3 L1; a request may carry its own `bps`.
        "bps": MapOf(_NON_NEGATIVE),
        # What the strip falls back to when the request that owned it expires and nothing else is
        # live — §5.2's "then back to idle" — paired with `default_color`.
        "idle_mode": StrSpec(),
    }
)

# `behavior/fsm.py::BehaviorState`, fixed here rather than imported: the schema is the layer that has
# to load even when the behaviour package cannot, and a state name is the schema's business anyway.
_BEHAVIOR_STATES = (
    "idle",
    "alert",
    "avoiding",
    "patrol",
    "explore",
    "interact",
    "play",
    "rest",
)

# One expression per state, fired once when the FSM enters it (`behavior/fsm.py::_entry_beat`), with
# an optional `sound` cue played alongside it (`_entry_cue`). A fixed-shape table rather than a free
# map, so a typo in a state name is a suggestion at load instead of a beat that never fires; a state
# left out simply has no beat. Nested so a cue can ride the entry without a format change.
_STATE_EXPRESSIONS = Section(
    fields={
        state: Section(fields={"action": StrSpec(), "sound": StrSpec()})
        for state in _BEHAVIOR_STATES
    }
)

# `behavior/fsm.py` — the state machine's whole repertoire. `catalog` and `action_classes` are
# replaced at load from `config/actions.jsonc` (see `core/config.py`), so they validate as a map of
# action lists and a map of classifications respectively.
_BEHAVIOR = Section(
    fields={
        "idle_action": StrSpec(),
        "touch_action": StrSpec(),
        "sound_action": StrSpec(),
        "avoid_action": StrSpec(),
        "explore_action": StrSpec(),
        "interact_action": StrSpec(),
        "patrol_action": StrSpec(),
        "actions_file": StrSpec(),
        "action_sets": MapOf(StrSpec()),
        "random_idle_chance": _FRACTION,
        "action_cooldown_s": _NON_NEGATIVE,
        "micro_idle_enabled": Bool(),
        "micro_idle_actions": _NAMES,
        "micro_idle_interval_s": _POSITIVE,
        "micro_idle_chance": _FRACTION,
        # Idle variety (L4). `idle_variety_interval_s` paces how often the idle action may change;
        # `action_reuse_cooldown_s` is how long an action is excluded after it was used, which is the
        # one that keeps a 14-entry bucket from cycling through two of them. 0 disables either.
        "idle_variety_interval_s": _NON_NEGATIVE,
        "action_reuse_cooldown_s": _NON_NEGATIVE,
        "habituation_enabled": Bool(),
        "habituation_threshold": IntSpec(minimum=1),
        "habituation_recovery_s": _NON_NEGATIVE,
        "transition_guard_enabled": Bool(),
        "transition_min_dwell_s": _NON_NEGATIVE,
        "transition_confirm_ticks": IntSpec(minimum=1),
        "transition_immediate_states": _NAMES,
        "state_expressions": _STATE_EXPRESSIONS,
        # The cue a state entry plays (`behavior/fsm.py::_entry_cue`). `cue_sounds` is advisory: the
        # vendor's twelve effects are the ones a stock build has, and a name outside the list is
        # warned once rather than refused, because a build may ship its own (#81).
        "cue_volume": IntSpec(minimum=0, maximum=100),
        "cue_sounds": _NAMES,
        "autonomy_enabled": Bool(),
        "autonomy_interval_s": _POSITIVE,
        "autonomy_modes": _NAMES,
        "autonomy_weights": MapOf(_FRACTION),
        "autonomy_rest_energy_max": _FRACTION,
        "autonomy_play_energy_min": _FRACTION,
        "idle_choices": _NAMES,
        "behavior_selection_mode": StrSpec(choices=("weighted", "sequential")),
        "behavior_weights": MapOf(_FRACTION),
        "catalog": MapOf(ListOf(StrSpec())),
        # One class per action, `{"class": "expression", "params": ["volume"]}`. The shape is
        # checked here; membership is cross-checked against the catalog by `kernel/actions.py`,
        # which is where a bucket name with no class becomes a load-time error with a did-you-mean.
        "action_classes": MapOf(
            Section(
                fields={
                    "class": StrSpec(choices=tuple(action_class.value for action_class in ActionClass)),
                    "params": _NAMES,
                }
            )
        ),
    }
)

# ===================================================================== optional modules
#
# These sections belong to modules that ship disabled (`optional/`). They are validated for
# the same reason as the rest: the moment a user flips one on, the config is the only thing
# standing between them and a module that starts with a half-understood settings table.

# The optional modules have no HTTP surfaces of their own any more. Each one used to carry an
# `http` block with its own bind address, port and (for telemetry) a token; all four servers are
# gone and the control plane in `services/api.py` is the only listener. The key is deliberately
# *not* accepted here, so an existing config fails at load with a did-you-mean instead of
# starting a module that ignores it.

# `optional/vision_pi4.py` + `optional/vision_preprocessing.py`. `backend` is compared against
# "picamera2" and everything else opens `cv2.VideoCapture`, so those are the two spellings.
# `preprocessing` and `inference_scheduler_enabled` are shipped now: they used to be read by the
# module and absent from the file. The scheduler starts nothing unless a model is wired, because
# the placeholder thread it used to start was a sleep loop returning `{"result": "ok"}` (M-03).
_VISION_PI4 = Section(
    fields={
        "enabled": Bool(),
        "backend": StrSpec(choices=("picamera2", "opencv")),
        "device_index": IntSpec(minimum=0),
        "frame_interval_s": _POSITIVE,
        "inference_scheduler_enabled": Bool(),
        "preprocessing": Section(
            fields={
                "resize": ListOf(IntSpec(minimum=1), length=2),
                "normalize": Bool(),
                "roi": ListOf(IntSpec(minimum=0), length=4, allow_none=True),
                "mean": ListOf(FloatSpec(), length=3),
                "std": ListOf(FloatSpec(), length=3),
            }
        ),
    }
)

# `optional/voice.py`. The backend names are the ones its docstring documents and the ones the
# recogniser selection branches on. `tts` is part of that documented contract but the module
# picks a TTS engine at runtime instead of reading it: the key is accepted so an existing file
# keeps loading, and wiring it is tracked with the voice work, not here.
_VOICE = Section(
    fields={
        "enabled": Bool(),
        "cooldown_s": _NON_NEGATIVE,
        "stt": Section(
            fields={
                "enabled": Bool(),
                "backend": StrSpec(choices=("auto", "vosk", "speech_recognition")),
                "vosk_model_path": StrSpec(),
            }
        ),
        "tts": Section(
            fields={
                "enabled": Bool(),
                "backend": StrSpec(choices=("auto", "pyttsx3", "pidog")),
            }
        ),
        "command_map": MapOf(StrSpec()),
        "aliases": MapOf(StrSpec()),
    }
)

# `optional/face_recognition.py` — three backends, each of which fails differently when a
# dependency is missing, which is why the choice is explicit rather than guessed.
_FACE_RECOGNITION = Section(
    fields={
        "enabled": Bool(),
        "backend": StrSpec(choices=("stub", "opencv", "face_recognition")),
        "scale_factor": _POSITIVE,
        "min_neighbors": IntSpec(minimum=1),
        "min_face_px": IntSpec(minimum=1),
        "opencv_haar_path": StrSpec(),
        "lbph": Section(
            fields={
                "enabled": Bool(),
                "model_path": StrSpec(),
                "dataset_dir": StrSpec(),
                "label_map_path": StrSpec(),
                "confidence_threshold": _NON_NEGATIVE,
            }
        ),
        "embeddings_path": StrSpec(),
        "match_threshold": _FRACTION,
    }
)

# `optional/semantic_labeler.py` — a stub and one real backend.
_SEMANTIC_LABELER = Section(
    fields={
        "enabled": Bool(),
        "backend": StrSpec(choices=("stub", "opencv_dnn")),
        "interval_s": _POSITIVE,
        "model_path": StrSpec(),
        "config_path": StrSpec(),
        "labels_path": StrSpec(),
        "input_width": IntSpec(minimum=1),
        "input_height": IntSpec(minimum=1),
        "confidence_threshold": _FRACTION,
    }
)

# `optional/slam_pi4.py`. `rtabmap` itself is a vendor tuning surface (it takes hundreds of
# keys), so that one sub-table allows extra keys; everything this repo reads is named.
_SLAM_PI4 = Section(
    fields={
        "enabled": Bool(),
        "backend": StrSpec(choices=("rtabmap", "stub")),
        "interval_s": _POSITIVE,
        "gyro_scale": FloatSpec(),
        "stub_confidence": _FRACTION,
        "nav_hint_enabled": Bool(),
        "nav_target_heading_deg": FloatSpec(allow_none=True),
        "nav_deadband_deg": FloatSpec(minimum=0.0, maximum=180.0),
        "max_buffer_s": _NON_NEGATIVE,
        "max_process_per_tick": IntSpec(minimum=1),
        "map_export_interval_s": _NON_NEGATIVE,
        "map_export_path": _NULLABLE_STR,
        "map_export_format": StrSpec(choices=("json", "ply")),
        "rtabmap": Section(
            fields={
                "database_path": StrSpec(),
                "frame_width": IntSpec(minimum=1, allow_none=True),
                "frame_height": IntSpec(minimum=1, allow_none=True),
                "rgbd_enabled": Bool(),
                "parameters": MapOf(),
            },
            allow_extra=True,
        ),
    }
)

# `services/api.py` — the control plane (D7). Every key here is read by
# `services/settings.py::ApiSettings.from_settings`; a key that is not read is not listed, which
# is the whole point of the strict schema.
_API = Section(
    fields={
        # Reachable on the LAN by design: the token is the security boundary, not the bind
        # address. `127.0.0.1` is a legitimate choice, and disabling `modules.api` removes the
        # surface entirely.
        "host": StrSpec(),
        "port": IntSpec(minimum=1, maximum=65535),
        # The install-issued token. Referenced by path, never pasted (D8).
        "token_path": StrSpec(),
        "static_root": _NULLABLE_STR,
        "state_hz": FloatSpec(minimum=1.0, maximum=50.0),
        "pairing_enabled": Bool(),
        "pairing_attempts_per_minute": IntSpec(minimum=1, maximum=60),
        "command_queue": IntSpec(minimum=1, maximum=1024),
        "command_ack_timeout_s": FloatSpec(minimum=0.05, maximum=5.0),
        "link_loss_s": FloatSpec(minimum=1.0, maximum=60.0),
        "max_clients": IntSpec(minimum=1, maximum=64),
        "log_tail": IntSpec(minimum=1, maximum=5000),
    }
)

# Sections audited against their consumers so far. A section absent from this table is
# accepted unvalidated, so the migration stays reviewable one group at a time.
_SETTINGS_SECTIONS: dict[str, Spec] = {
    "api": _API,
    "attention": _ATTENTION,
    "balance": _BALANCE,
    "battery": _BATTERY,
    "behavior": _BEHAVIOR,
    "calibration": _CALIBRATION,
    "device": _DEVICE,
    "emotion": _EMOTION,
    "energy": _ENERGY,
    "face_recognition": _FACE_RECOGNITION,
    "habituation": _HABITUATION,
    "led": _LED,
    "logging": _LOGGING,
    "mapping": _MAPPING,
    "motors": _MOTORS,
    "movement": _MOVEMENT,
    "navigation": _NAVIGATION,
    "orientation": _ORIENTATION,
    "perception": _PERCEPTION,
    "performance": _PERFORMANCE,
    "personality": _PERSONALITY,
    "quiet_mode": _QUIET_MODE,
    "routines": _ROUTINES,
    "safety": _SAFETY,
    "semantic_labeler": _SEMANTIC_LABELER,
    "sensor_health": _SENSOR_HEALTH,
    "sensors": _SENSORS,
    "slam_pi4": _SLAM_PI4,
    "vision_pi4": _VISION_PI4,
    "voice_assistant": _VOICE,
    "watchdog": _WATCHDOG,
}

# Every section the repo ships is in the table above, so `settings` no longer tolerates an
# unknown section: a typo such as `settings.voice` instead of `settings.voice_assistant` is
# now an error with a suggestion instead of a table nothing reads.
_SETTINGS = Section(fields=_SETTINGS_SECTIONS)

_PROFILES = MapOf(
    Section(
        fields={
            "loop": _LOOP,
            "modules": MapOf(_MODULE_ENTRY),
            "settings": _SETTINGS,
        }
    )
)

_TOP = Section(
    fields={
        "profile": StrSpec(),
        "profiles": _PROFILES,
        "loop": _LOOP,
        "modules": MapOf(_MODULE_ENTRY),
        "settings": _SETTINGS,
    }
)


def validate_config_tree(raw: Any) -> list[Problem]:
    """Validate and normalise a parsed settings tree.

    Returns the list of problems found. Non-empty means the config must not be used: callers
    raise :class:`ConfigError` so the process stops before it can move a servo.
    """
    _, problems = _TOP.validate(raw, "config")
    return problems