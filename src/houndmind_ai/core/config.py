from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import json5

from houndmind_ai.board.detect import SUPPORTED_KINDS, BoardInfo, detect
from houndmind_ai.kernel.config_schema import (
    ConfigError,
    Problem,
    validate_config_tree,
)

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
    # The profile that was actually applied, after board detection. Empty for a `Config` built
    # by hand, so a caller that never went through `load_config` cannot claim one.
    profile: str = ""

    @staticmethod
    def from_dict(raw: dict, profile: str = "") -> Config:
        loop_raw = raw.get("loop", {})
        # Coerce loop numeric settings to the expected types. Ensure max_cycles
        # is either an int or None to avoid runtime type errors when compared
        # against counters in the runtime loop.
        tick_hz_raw = loop_raw.get("tick_hz", 5)
        try:
            tick_hz = int(tick_hz_raw)
        except (TypeError, ValueError):
            tick_hz = 5
        max_cycles_raw = loop_raw.get("max_cycles")
        if max_cycles_raw is None:
            max_cycles = None
        else:
            try:
                max_cycles = int(max_cycles_raw)
            except (TypeError, ValueError):
                max_cycles = None

        loop = LoopConfig(tick_hz=tick_hz, max_cycles=max_cycles)

        modules: dict[str, ModuleConfig] = {}
        for name, mod in raw.get("modules", {}).items():
            modules[name] = ModuleConfig(
                enabled=bool(mod.get("enabled", True)),
                required=bool(mod.get("required", False)),
            )
        settings = raw.get("settings", {})

        return Config(loop=loop, modules=modules, settings=settings, profile=profile)


def default_config_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "config" / "settings.jsonc"


# `auto` means "ask the board", and it is what the file ships: a config does not know which Pi
# it was copied onto, so a hard-coded default can only be right on one of them.
AUTO_PROFILE = "auto"

# What a host with no device tree resolves to. CI, a workstation and a container are all
# `unknown`, and the runtime has to start on every one of them; the slower of the two shipped
# editions is the honest guess.
FALLBACK_PROFILE = "pi4"

# Named in the refusal a Pi 3 gets, so its owner has somewhere to go. Kept in step with the
# last tag that shipped Pi 3 support.
LAST_PI3_RELEASE = "v2026.01.18"


def _load_jsonc(path: Path) -> dict:
    """Parse a JSONC file. `json5` is a hard dependency, so there is no fallback parser.

    The hand-rolled comment stripper that used to live here existed only because `json5` was
    optional and the installer ran a bare `pip install`. It was 60 lines of string/escape/
    comment state machine whose failures were indistinguishable from a typo in the config, so
    it is gone; a syntax error now names the file it came from (B-02).
    """
    raw_text = path.read_text(encoding="utf-8")
    try:
        return json5.loads(raw_text)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def resolve_profile(raw: dict, board: BoardInfo | None = None) -> str:
    """Decide which profile applies, or refuse loudly.

    Precedence: ``HOUNDMIND_PROFILE`` (an operator override at launch), then ``profile`` in the
    file, then ``auto``.

    An explicitly requested profile must exist. It used to be a warning, so a typo ran the
    shipped cadence and looked exactly like success. A name resolved from the board may be
    absent from the file: a config with no ``profiles`` table is legal and simply has nothing
    to override.

    ``board`` exists for tests; production passes nothing and the device tree answers.
    """
    requested = os.getenv("HOUNDMIND_PROFILE") or raw.get("profile") or AUTO_PROFILE
    requested = str(requested)

    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}

    if requested != AUTO_PROFILE:
        if requested not in profiles:
            raise ConfigError([_unknown_profile(requested, profiles)])
        return requested

    info = board if board is not None else detect()

    if info.kind not in SUPPORTED_KINDS:
        if info.kind == "unsupported":
            raise ConfigError(
                [
                    Problem(
                        "config.profile",
                        f"board not supported: {info.model or 'an unnamed model'} is a board "
                        f"this release does not run on; Pi 3 and older were dropped, and "
                        f"{LAST_PI3_RELEASE} is the last release that supported them",
                    )
                ]
            )
        logger.warning(
            "No Raspberry Pi board detected; using the '%s' profile. Set HOUNDMIND_PROFILE "
            "to choose one explicitly.",
            FALLBACK_PROFILE,
        )
        return FALLBACK_PROFILE

    return info.kind


def _unknown_profile(name: str, profiles: dict) -> Problem:
    available = sorted(profiles)
    # A suggestion has to be a near-miss, not merely a shared prefix. At the default cutoff
    # `pi3` earns "did you mean pi5?", which is advice a Pi 3 owner should not be given: they
    # need the dropped-board message, not a different edition's name.
    suggestion = get_close_matches(name, available, n=1, cutoff=0.8)
    listed = ", ".join(available) if available else "none"
    return Problem(
        "config.profile",
        f"unknown profile {name!r}; this file defines: {listed}",
        suggestion[0] if suggestion else None,
    )


def load_config(path: Path | None = None) -> Config:
    config_path = path or default_config_path()
    raw = _load_jsonc(config_path)

    # Validate before applying profile overrides, so a problem is reported against the file
    # the operator actually edited rather than against the merged result.
    problems = validate_config_tree(raw)
    if problems:
        raise ConfigError(problems)

    profile = resolve_profile(raw)
    raw = _apply_profile_overrides(raw, profile)
    config = Config.from_dict(raw, profile=profile)

    for warning in validate_config(config):
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


def _apply_profile_overrides(raw: dict, profile: str) -> dict:
    profiles = raw.get("profiles", {})
    if not isinstance(profiles, dict):
        return raw

    overrides = profiles.get(profile)
    if not isinstance(overrides, dict):
        # A profile with no overrides is a legal config, not a failure: `resolve_profile` has
        # already refused the names that cannot be honoured.
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


def _to_float(value: Any | None) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_config(config: Config) -> list[str]:
    """Cross-field checks that a per-value schema cannot express.

    Everything else lives in `kernel/config_schema.py` and is enforced before this runs: a
    wrong type or an unknown key is a load-time error, not a warning. What is left here is the
    handful of rules that only make sense when two values are compared — the ordering of the
    safety distances, an interval that must sit inside its own bounds — plus two advisory
    notes about values that are legal but a bad idea on a Pi.
    """
    warnings: list[str] = []
    settings = config.settings or {}
    sensors = settings.get("sensors", {})
    navigation = settings.get("navigation", {})
    movement = settings.get("movement", {})
    performance = settings.get("performance", {})
    logging_settings = settings.get("logging", {})
    safety = settings.get("safety", {})

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

    # A stuck detector that fires on one or two samples is a stuck detector that fires on
    # sensor noise, which is how the dog talks itself into a recovery spiral.
    stuck_samples = _to_float(navigation.get("stuck_min_samples"))
    if stuck_samples is not None and stuck_samples < 3:
        warnings.append("navigation.stuck_min_samples should be >= 3")

    speed_normal = _to_float(movement.get("speed_normal"))
    speed_turn_normal = _to_float(movement.get("speed_turn_normal"))
    if (
        speed_normal is not None
        and speed_turn_normal is not None
        and speed_turn_normal <= speed_normal
    ):
        warnings.append("movement.speed_turn_normal should be faster than speed_normal")

    log_max_entries = _to_float(logging_settings.get("log_max_entries"))
    if log_max_entries is not None and log_max_entries > 5000:
        warnings.append("logging.log_max_entries is large and may use significant memory")

    # The supervisor clears producers below `safety`; without it in the list, an emergency
    # stop could be talked over by a module that never heard about it.
    override_priority = safety.get("override_priority")
    if isinstance(override_priority, list) and "safety" not in override_priority:
        warnings.append("safety.override_priority should include 'safety'")

    return warnings
