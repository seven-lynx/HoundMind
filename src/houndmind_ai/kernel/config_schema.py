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

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if not isinstance(value, list):
            return value, [Problem(path, f"expected a list, got {value!r}")]
        problems: list[Problem] = []
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

# `safety/service_watchdog.py` — restart policy for modules that stop ticking.
_SERVICE_WATCHDOG = Section(
    fields={
        "enabled": Bool(),
        "module_timeout_s": _POSITIVE,
        "restart_cooldown_s": _NON_NEGATIVE,
        "max_restarts": IntSpec(minimum=0),
        "monitor_modules": _NAMES,
        "ignore_modules": _NAMES,
        "restart_on_error": Bool(),
        "restart_on_stale": Bool(),
        "status_interval_s": _POSITIVE,
    }
)

# `safety/watchdog.py` — `recovery_mode` is compared against "behavior" and everything else
# is treated as "action", so only those two spellings mean anything. `recovery_behavior` and
# `recovery_action` ship as `null` to mean "use the built-in default", hence the None.
_WATCHDOG = Section(
    fields={
        "enabled": Bool(),
        "sensor_timeout_s": _POSITIVE,
        "scan_timeout_s": _POSITIVE,
        "module_timeout_s": _POSITIVE,
        "monitor_modules": _NAMES,
        "restart_cooldown_s": _NON_NEGATIVE,
        "restart_module_cooldown_s": _NON_NEGATIVE,
        "recovery_mode": StrSpec(choices=("behavior", "action")),
        "recovery_behavior": _NULLABLE_STR,
        "recovery_action": _NULLABLE_STR,
        "restart_modules": _NAMES,
        "max_restarts": IntSpec(minimum=0),
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

# Sections audited against their consumers so far. A section absent from this table is
# accepted unvalidated, so the migration stays reviewable one group at a time.
_SETTINGS_SECTIONS: dict[str, Spec] = {
    "attention": _ATTENTION,
    "balance": _BALANCE,
    "battery": _BATTERY,
    "logging": _LOGGING,
    "motors": _MOTORS,
    "performance": _PERFORMANCE,
    "quiet_mode": _QUIET_MODE,
    "safety": _SAFETY,
    "sensor_health": _SENSOR_HEALTH,
    "sensors": _SENSORS,
    "service_watchdog": _SERVICE_WATCHDOG,
    "watchdog": _WATCHDOG,
}

# `allow_extra` stays true until every shipped section is in the table above: an unaudited
# section keeps loading untouched, while a section that *is* covered rejects strangers now.
_SETTINGS = Section(fields=_SETTINGS_SECTIONS, allow_extra=True)

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