from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import logging
import os
import re

logger = logging.getLogger(__name__)


@dataclass
class LoopConfig:
    tick_hz: int = 5
    max_cycles: int | None = 10


@dataclass
class ModuleConfig:
    enabled: bool = True
    required: bool = False


@dataclass
class Config:
    loop: LoopConfig
    modules: dict[str, ModuleConfig]
    settings: dict[str, dict] = field(default_factory=dict)

    @staticmethod
    def from_dict(raw: dict) -> "Config":
        loop_raw = raw.get("loop", {})
        loop = LoopConfig(
            tick_hz=int(loop_raw.get("tick_hz", 5)),
            max_cycles=loop_raw.get("max_cycles"),
        )

        modules: dict[str, ModuleConfig] = {}
        for name, mod in raw.get("modules", {}).items():
            modules[name] = ModuleConfig(
                enabled=bool(mod.get("enabled", True)),
                required=bool(mod.get("required", False)),
            )
        settings = raw.get("settings", {})

        return Config(loop=loop, modules=modules, settings=settings)


def default_config_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "config" / "settings.jsonc"


def _load_jsonc(path: Path) -> dict:
    raw_text = path.read_text(encoding="utf-8")

    # Allow JSONC-style comments for user-friendly config files.
    cleaned: list[str] = []
    in_string = False
    escape = False
    i = 0
    length = len(raw_text)
    while i < length:
        ch = raw_text[i]
        nxt = raw_text[i + 1] if i + 1 < length else ""
        if in_string:
            cleaned.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            cleaned.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            # Skip line comment.
            i += 2
            while i < length and raw_text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            # Skip block comment.
            i += 2
            while i + 1 < length and not (
                raw_text[i] == "*" and raw_text[i + 1] == "/"
            ):
                i += 1
            i += 2
            continue

        cleaned.append(ch)
        i += 1

    cleaned_text = "".join(cleaned)
    # Remove trailing commas before closing braces/brackets.
    cleaned_text = re.sub(r",\s*([}\]])", r"\1", cleaned_text)
    return json.loads(cleaned_text)


def load_config(path: Path | None = None) -> Config:
    config_path = path or default_config_path()
    raw = _load_jsonc(config_path)
    raw = _apply_profile_overrides(raw)
    config = Config.from_dict(raw)

    warnings = validate_config(config)
    for warning in warnings:
        logger.warning("Config warning: %s", warning)

    # Optional: load action catalog from a dedicated file.
    behavior_settings = config.settings.get("behavior", {})
    actions_file = behavior_settings.get("actions_file")
    if actions_file:
        actions_path = Path(actions_file)
        if not actions_path.is_absolute():
            actions_path = config_path.parent / actions_file
        if actions_path.exists():
            actions_raw = _load_jsonc(actions_path)
            behavior_settings["catalog"] = actions_raw.get("catalog", {})
            config.settings["behavior"] = behavior_settings
            _ensure_action_sets(behavior_settings)

    return config


def _apply_profile_overrides(raw: dict) -> dict:
    profiles = raw.get("profiles", {})
    if not isinstance(profiles, dict):
        return raw

    profile = os.getenv("HOUNDMIND_PROFILE") or raw.get("profile")
    if not profile:
        return raw
    profile = str(profile)
    overrides = profiles.get(profile)
    if not isinstance(overrides, dict):
        logger.warning("Profile '%s' not found; skipping overrides", profile)
        return raw

    merged = dict(raw)
    _deep_merge(merged, overrides)
    logger.info("Applied profile overrides: %s", profile)
    return merged


def _deep_merge(target: dict, overrides: dict) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _ensure_action_sets(behavior_settings: dict) -> None:
    catalog = behavior_settings.get("catalog", {})
    if not isinstance(catalog, dict):
        return
    action_sets = behavior_settings.get("action_sets", {})
    if not isinstance(action_sets, dict):
        return
    # Define missing sets using base actions as defaults.
    defaults = {
        "idle": [behavior_settings.get("idle_action", "stand")],
        "alert": [
            behavior_settings.get("touch_action", "wag tail"),
            behavior_settings.get("sound_action", "shake head"),
        ],
        "avoid": [behavior_settings.get("avoid_action", "backward")],
        "play": ["stretch"],
        "rest": ["lie"],
        "patrol": [behavior_settings.get("patrol_action", "forward")],
    }
    for role, set_name in action_sets.items():
        if set_name not in catalog:
            catalog[set_name] = defaults.get(str(role), [])
            logger.warning("Action set missing: %s (created default)", set_name)
    behavior_settings["catalog"] = catalog


def _to_float(value: object | None) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_config(config: Config) -> list[str]:
    warnings: list[str] = []
    if config.loop.tick_hz <= 0:
        warnings.append("loop.tick_hz should be > 0")
    if config.loop.max_cycles is not None and config.loop.max_cycles <= 0:
        warnings.append("loop.max_cycles should be > 0 when set")
    settings = config.settings or {}
    sensors = settings.get("sensors", {})
    navigation = settings.get("navigation", {})
    movement = settings.get("movement", {})
    performance = settings.get("performance", {})
    logging_settings = settings.get("logging", {})
    safety = settings.get("safety", {})
    attention = settings.get("attention", {})
    balance = settings.get("balance", {})

    min_cm = _to_float(sensors.get("distance_min_cm"))
    max_cm = _to_float(sensors.get("distance_max_cm"))
    if min_cm is not None and max_cm is not None and min_cm >= max_cm:
        warnings.append("sensors.distance_min_cm should be less than distance_max_cm")

    poll_hz = _to_float(sensors.get("poll_hz"))
    poll_hz_max = _to_float(performance.get("sensor_poll_hz_max"))
    if poll_hz is not None and poll_hz_max is not None and poll_hz > poll_hz_max:
        warnings.append("sensors.poll_hz exceeds performance.sensor_poll_hz_max")

    scan_interval = _to_float(navigation.get("scan_interval_s"))
    scan_min = _to_float(navigation.get("scan_interval_min_s"))
    scan_max = _to_float(navigation.get("scan_interval_max_s"))
    if scan_min is None:
        scan_min = _to_float(performance.get("scan_interval_min_s"))
    if scan_max is None:
        scan_max = _to_float(performance.get("scan_interval_max_s"))
    if scan_interval is not None and scan_min is not None and scan_interval < scan_min:
        warnings.append(
            "navigation.scan_interval_s is below performance.scan_interval_min_s"
        )
    if scan_interval is not None and scan_max is not None and scan_interval > scan_max:
        warnings.append(
            "navigation.scan_interval_s is above performance.scan_interval_max_s"
        )

    emergency_stop = _to_float(navigation.get("emergency_stop_cm"))
    min_distance = _to_float(navigation.get("min_distance_cm"))
    safe_distance = _to_float(navigation.get("safe_distance_cm"))
    if (
        emergency_stop is not None
        and min_distance is not None
        and emergency_stop >= min_distance
    ):
        warnings.append(
            "navigation.emergency_stop_cm should be less than min_distance_cm"
        )
    if (
        min_distance is not None
        and safe_distance is not None
        and min_distance >= safe_distance
    ):
        warnings.append(
            "navigation.min_distance_cm should be less than safe_distance_cm"
        )

    stuck_window = _to_float(navigation.get("stuck_time_window_s"))
    stuck_threshold = _to_float(navigation.get("stuck_movement_threshold"))
    stuck_samples = _to_float(navigation.get("stuck_min_samples"))
    if stuck_window is not None and stuck_window <= 0:
        warnings.append("navigation.stuck_time_window_s should be > 0")
    if stuck_threshold is not None and stuck_threshold <= 0:
        warnings.append("navigation.stuck_movement_threshold should be > 0")
    if stuck_samples is not None and stuck_samples < 3:
        warnings.append("navigation.stuck_min_samples should be >= 3")

    min_valid_points = _to_float(navigation.get("scan_min_valid_points"))
    min_valid_ratio = _to_float(navigation.get("scan_min_valid_ratio"))
    if min_valid_points is not None and min_valid_points < 1:
        warnings.append("navigation.scan_min_valid_points should be >= 1")
    if min_valid_ratio is not None and not (0 < min_valid_ratio <= 1):
        warnings.append("navigation.scan_min_valid_ratio should be in (0, 1]")

    turn_confidence_min = _to_float(navigation.get("turn_confidence_min"))
    if turn_confidence_min is not None and not (0 < turn_confidence_min <= 1):
        warnings.append("navigation.turn_confidence_min should be in (0, 1]")

    low_confidence_cooldown = _to_float(navigation.get("low_confidence_cooldown_s"))
    if low_confidence_cooldown is not None and low_confidence_cooldown < 0:
        warnings.append("navigation.low_confidence_cooldown_s should be >= 0")

    retry_limit = _to_float(navigation.get("scan_retry_limit"))
    if retry_limit is not None and retry_limit < 0:
        warnings.append("navigation.scan_retry_limit should be >= 0")

    speed_normal = _to_float(movement.get("speed_normal"))
    speed_turn_normal = _to_float(movement.get("speed_turn_normal"))
    if speed_normal is not None and speed_normal < 0:
        warnings.append("movement.speed_normal should be >= 0")
    if speed_normal is not None and speed_normal > 255:
        warnings.append("movement.speed_normal exceeds servo limit (255)")
    if speed_turn_normal is not None and speed_turn_normal < 0:
        warnings.append("movement.speed_turn_normal should be >= 0")
    if speed_turn_normal is not None and speed_turn_normal > 255:
        warnings.append("movement.speed_turn_normal exceeds servo limit (255)")
    if (
        speed_normal is not None
        and speed_turn_normal is not None
        and speed_turn_normal <= speed_normal
    ):
        warnings.append("movement.speed_turn_normal should be faster than speed_normal")

    log_max_entries = _to_float(logging_settings.get("log_max_entries"))
    if log_max_entries is not None and log_max_entries > 5000:
        warnings.append(
            "logging.log_max_entries is large and may use significant memory"
        )

    override_priority = safety.get("override_priority")
    if override_priority is not None and not isinstance(override_priority, list):
        warnings.append("safety.override_priority should be a list")
    if isinstance(override_priority, list) and "safety" not in override_priority:
        warnings.append("safety.override_priority should include 'safety'")
    override_clear_lower = safety.get("override_clear_lower")
    if override_clear_lower is not None and not isinstance(override_clear_lower, bool):
        warnings.append("safety.override_clear_lower should be a boolean")
    # Emergency stop validation
    emergency_enabled = safety.get("emergency_stop_enabled")
    if emergency_enabled is not None and not isinstance(emergency_enabled, bool):
        warnings.append("safety.emergency_stop_enabled should be a boolean")
    emergency_cm = _to_float(safety.get("emergency_stop_cm"))
    if emergency_cm is not None and emergency_cm <= 0:
        warnings.append("safety.emergency_stop_cm should be > 0")
    emergency_cool = _to_float(safety.get("emergency_stop_cooldown_s"))
    if emergency_cool is not None and emergency_cool < 0:
        warnings.append("safety.emergency_stop_cooldown_s should be >= 0")
    emergency_action = safety.get("emergency_stop_action")
    if emergency_action is not None and not isinstance(emergency_action, str):
        warnings.append("safety.emergency_stop_action should be a string action name")

    head_yaw_max = _to_float(attention.get("head_yaw_max_deg"))
    if head_yaw_max is not None and not (0 < head_yaw_max <= 90):
        warnings.append("attention.head_yaw_max_deg should be in (0, 90]")
    attention_cooldown = _to_float(attention.get("sound_cooldown_s"))
    if attention_cooldown is not None and attention_cooldown < 0:
        warnings.append("attention.sound_cooldown_s should be >= 0")
    scan_block = _to_float(attention.get("scan_block_s"))
    if scan_block is not None and scan_block < 0:
        warnings.append("attention.scan_block_s should be >= 0")

    balance_update_hz = _to_float(balance.get("update_hz"))
    if balance_update_hz is not None and balance_update_hz < 0:
        warnings.append("balance.update_hz should be >= 0")
    balance_scale = _to_float(balance.get("compensation_scale"))
    if balance_scale is not None and balance_scale < 0:
        warnings.append("balance.compensation_scale should be >= 0")
    balance_max_pitch = _to_float(balance.get("max_pitch_deg"))
    if balance_max_pitch is not None and balance_max_pitch <= 0:
        warnings.append("balance.max_pitch_deg should be > 0")
    balance_max_roll = _to_float(balance.get("max_roll_deg"))
    if balance_max_roll is not None and balance_max_roll <= 0:
        warnings.append("balance.max_roll_deg should be > 0")
    balance_lpf = _to_float(balance.get("lpf_alpha"))
    if balance_lpf is not None and not (0 < balance_lpf <= 1.0):
        warnings.append("balance.lpf_alpha should be in (0, 1]")

    return warnings
