"""A bad config must fail before hardware is touched, and say why.

The old validator only appended warnings, so `tick_hz: "fast"` loaded and a key placed under
`modules.<name>` was silently dropped while still being documented as working.
"""

from __future__ import annotations

import json5
import pytest

from houndmind_ai.core.config import default_config_path, load_config
from houndmind_ai.kernel.config_schema import (
    Bool,
    ConfigError,
    FloatSpec,
    IntSpec,
    ListOf,
    MapOf,
    Problem,
    Section,
    StrSpec,
    validate_config_tree,
)


def paths(problems: list[Problem]) -> list[str]:
    return [p.path for p in problems]


# ------------------------------------------------------------------ primitive specs


def test_bool_accepts_only_real_booleans() -> None:
    assert Bool().validate(True, "x")[1] == []
    assert Bool().validate("true", "x")[1]  # a string is not a bool
    assert Bool().validate(1, "x")[1]


def test_int_rejects_bool() -> None:
    """`tick_hz: true` must not silently become 1 tick per second."""
    _, problems = IntSpec(minimum=1).validate(True, "loop.tick_hz")
    assert problems


def test_int_bounds_are_enforced() -> None:
    assert IntSpec(minimum=1, maximum=100).validate(0, "x")[1]
    assert IntSpec(minimum=1, maximum=100).validate(101, "x")[1]
    assert IntSpec(minimum=1, maximum=100).validate(50, "x")[1] == []


def test_int_allow_none_is_explicit() -> None:
    assert IntSpec(minimum=1, allow_none=True).validate(None, "x")[1] == []
    assert IntSpec(minimum=1).validate(None, "x")[1]


def test_float_rejects_nan_and_strings() -> None:
    assert FloatSpec().validate(float("nan"), "x")[1]
    assert FloatSpec().validate("1.5", "x")[1]


def test_float_exclusive_minimum() -> None:
    spec = FloatSpec(minimum=0.0, exclusive_minimum=True)
    assert spec.validate(0.0, "x")[1]
    assert spec.validate(0.001, "x")[1] == []


def test_string_choices_suggest_a_near_match() -> None:
    _, problems = StrSpec(choices=("picamera2", "opencv")).validate("picamra2", "backend")
    assert problems[0].hint == "picamera2"


def test_list_reports_the_offending_index() -> None:
    _, problems = ListOf(IntSpec(minimum=0)).validate([1, -1], "vals")
    assert paths(problems) == ["vals[1]"]


def test_list_can_require_a_fixed_length() -> None:
    """`mapping.grid_size` is indexed as [0]/[1], so a third entry is a broken map."""
    spec = ListOf(IntSpec(minimum=1), length=2)
    assert spec.validate([100, 100], "g")[1] == []
    assert spec.validate([100], "g")[1][0].path == "g"
    assert spec.validate([100, 100, 100], "g")[1]


def test_map_requires_a_table() -> None:
    assert MapOf().validate([], "m")[1]


# ------------------------------------------------------------------ strict sections


def test_unknown_key_is_an_error_with_a_suggestion() -> None:
    spec = Section(fields={"enabled": Bool(), "required": Bool()})
    _, problems = spec.validate({"enabled": True, "requird": False}, "modules.foo")
    assert len(problems) == 1
    assert "unknown key" in problems[0].message
    assert problems[0].hint == "required"


def test_known_keys_pass() -> None:
    spec = Section(fields={"enabled": Bool()})
    assert spec.validate({"enabled": False}, "m")[1] == []


def test_allow_extra_accepts_anything() -> None:
    spec = Section(fields={}, allow_extra=True)
    assert spec.validate({"anything": 1}, "s")[1] == []


def test_config_error_message_lists_every_problem() -> None:
    error = ConfigError(
        [Problem("config.loop.tick_hz", "expected an integer"), Problem("config.nope", "x")]
    )
    text = error.format()
    assert "2 problem(s)" in text
    assert "config.loop.tick_hz" in text
    assert "config.nope" in text


# ------------------------------------------------------------------ whole tree


def test_minimal_tree_is_accepted() -> None:
    assert validate_config_tree({"loop": {"tick_hz": 10, "max_cycles": None}}) == []


def test_unknown_top_level_key_is_rejected() -> None:
    problems = validate_config_tree({"loops": {}})
    assert paths(problems) == ["config.loops"]
    assert problems[0].hint == "loop"


def test_bad_tick_rate_is_rejected() -> None:
    problems = validate_config_tree({"loop": {"tick_hz": "fast"}})
    assert "config.loop.tick_hz" in paths(problems)


def test_zero_tick_rate_is_rejected() -> None:
    """A 0 Hz loop would divide by zero in the runtime."""
    assert validate_config_tree({"loop": {"tick_hz": 0}})


def test_a_module_key_beyond_enabled_is_rejected() -> None:
    """This is blocker B-07: the old loader accepted it and then threw it away."""
    problems = validate_config_tree(
        {"modules": {"navigation": {"enabled": True, "gentle_recovery_stuck_count": 3}}}
    )
    assert paths(problems) == ["config.modules.navigation.gentle_recovery_stuck_count"]


def test_module_enabled_and_required_are_accepted() -> None:
    tree = {"modules": {"safety": {"enabled": False, "required": False}}}
    assert validate_config_tree(tree) == []


def test_profile_overrides_are_validated() -> None:
    tree = {"profiles": {"pi5": {"loop": {"tick_hz": 999}}}}
    assert "config.profiles.pi5.loop.tick_hz" in paths(validate_config_tree(tree))


def test_settings_must_be_a_table() -> None:
    assert validate_config_tree({"settings": []})


def test_settings_sections_not_yet_audited_stay_permissive() -> None:
    """Sections arrive in groups; an unaudited one keeps loading untouched."""
    tree = {"settings": {"voice_assistant": {"anything_at_all": 1}}}
    assert validate_config_tree(tree) == []


# ----------------------------------------------------- audited settings sections
#
# One row per covered section: a value of the wrong type must be rejected at load. The point
# is coverage breadth — a section that is added to `_SETTINGS_SECTIONS` without a row here is
# a section nobody proved was reachable.

BAD_SETTINGS_VALUES: list[tuple[str, str, object]] = [
    ("sensors", "poll_hz", "often"),
    ("motors", "min_action_interval_s", "soon"),
    ("sensor_health", "enabled", "yes"),
    ("service_watchdog", "max_restarts", "many"),
    ("watchdog", "module_timeout_s", None),
    ("balance", "lpf_alpha", 1.5),
    ("safety", "tilt_threshold_deg", "steep"),
    ("logging", "log_level", "LOUD"),
    ("performance", "runtime_ema_alpha", 0.0),
    ("battery", "low_voltage_v", "empty"),
    ("quiet_mode", "start_hour", 24),
    ("attention", "head_yaw_max_deg", 91.0),
    ("navigation", "scan_mode", "sweepy"),
    ("mapping", "grid_size", [100]),
    ("movement", "speed_turn_normal", 300),
    ("orientation", "turn_timeout_s", 0.0),
    ("calibration", "request", "servo_zer0"),
    ("perception", "fusion", []),
    ("habituation", "threshold", 0),
    ("personality", "curiosity", 1.5),
    ("energy", "initial", "full"),
    ("emotion", "led_colors", ["blue"]),
    ("led", "brightness", 1.4),
    ("behavior", "behavior_selection_mode", "random"),
]


@pytest.mark.parametrize(("section", "key", "bad_value"), BAD_SETTINGS_VALUES)
def test_a_covered_section_rejects_a_bad_value(section, key, bad_value) -> None:
    problems = validate_config_tree({"settings": {section: {key: bad_value}}})
    assert paths(problems) == [f"config.settings.{section}.{key}"], problems


def test_the_schema_and_this_table_agree() -> None:
    """A section added to the schema without a rejection case here is untested."""
    assert set(_settings_section().fields) == {
        section for section, _, _ in BAD_SETTINGS_VALUES
    }


def test_every_covered_section_exists_in_the_shipped_file() -> None:
    covered = {section for section, _, _ in BAD_SETTINGS_VALUES}
    shipped = set(json5.loads(default_config_path().read_text(encoding="utf-8"))["settings"])
    assert covered <= shipped, covered - shipped


def test_an_unknown_key_inside_a_covered_section_is_an_error() -> None:
    problems = validate_config_tree({"settings": {"logging": {"log_levels": "DEBUG"}}})
    assert paths(problems) == ["config.settings.logging.log_levels"]
    assert problems[0].hint == "log_level"


def test_an_unknown_settings_section_is_still_tolerated() -> None:
    """Until a section is audited, a new section name cannot be told from a typo."""
    assert validate_config_tree({"settings": {"voice": {}}}) == []


def test_a_misspelled_enum_value_suggests_the_real_one() -> None:
    problems = validate_config_tree({"settings": {"watchdog": {"recovery_mode": "behaviour"}}})
    assert problems[0].hint == "behavior"


def test_a_nullable_setting_accepts_null_but_not_a_number() -> None:
    tree = {"settings": {"watchdog": {"recovery_action": None}}}
    assert validate_config_tree(tree) == []
    assert validate_config_tree({"settings": {"watchdog": {"recovery_action": 3}}})


def test_profile_settings_overrides_are_validated() -> None:
    tree = {"profiles": {"pi5": {"settings": {"logging": {"log_level": "LOUD"}}}}}
    assert paths(validate_config_tree(tree)) == [
        "config.profiles.pi5.settings.logging.log_level"
    ]


def test_shipped_settings_values_all_validate() -> None:
    """Every value the repo ships must satisfy the section spec that now covers it."""
    raw = json5.loads(default_config_path().read_text(encoding="utf-8"))
    for section in sorted(raw["settings"]):
        _, problems = _settings_section().validate(raw["settings"][section], section)
        assert not problems, problems


def _settings_section():
    from houndmind_ai.kernel import config_schema

    return config_schema._SETTINGS


# ------------------------------------------------------------------ the real file


def test_shipped_config_is_valid() -> None:
    """The config we actually ship must pass the schema we actually enforce."""
    raw = json5.loads(default_config_path().read_text(encoding="utf-8"))
    assert validate_config_tree(raw) == []


def test_shipped_config_loads() -> None:
    config = load_config()
    assert config.loop.tick_hz >= 1
    assert config.modules, "the shipped config should declare modules"


def test_shipped_config_runs_continuously() -> None:
    """B-01: a finite max_cycles made a fresh install quit after two seconds."""
    assert load_config().loop.max_cycles is None


def test_load_config_raises_on_a_bad_file(tmp_path) -> None:
    bad = tmp_path / "settings.jsonc"
    bad.write_text('{ "loop": { "tick_hz": "fast" } }', encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(bad)
    assert "tick_hz" in str(excinfo.value)