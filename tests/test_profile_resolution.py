"""Profile resolution: one profile, chosen from the board, refused when it cannot be honoured.

The shipped file asks the board (`"profile": "auto"`) instead of naming one, because a default
that names a board can only be right on that board. These tests drive every branch with a
`BoardInfo` and never look at `/proc`.
"""

from __future__ import annotations

import json5
import pytest

from houndmind_ai.board.detect import BoardInfo
from houndmind_ai.core.config import (
    AUTO_PROFILE,
    FALLBACK_PROFILE,
    LAST_PI3_RELEASE,
    Config,
    load_config,
    resolve_profile,
)
from houndmind_ai.kernel.config_schema import ConfigError

PROFILES = {"pi4": {"loop": {"tick_hz": 10}}, "pi5": {"loop": {"tick_hz": 10}}}


@pytest.fixture(autouse=True)
def _no_ambient_profile(monkeypatch):
    """The environment wins over the file, so a stray variable would silently move every test."""
    monkeypatch.delenv("HOUNDMIND_PROFILE", raising=False)


def test_auto_resolves_to_the_detected_board() -> None:
    board = {"profile": AUTO_PROFILE, "profiles": PROFILES}

    assert resolve_profile(board, BoardInfo("pi5")) == "pi5"
    assert resolve_profile(board, BoardInfo("pi4")) == "pi4"


def test_auto_without_a_device_tree_falls_back_to_the_slower_edition() -> None:
    """CI, a workstation and a container have no board; all three still have to start."""
    assert resolve_profile({"profile": AUTO_PROFILE}, BoardInfo("unknown")) == FALLBACK_PROFILE


def test_a_dropped_board_is_refused_with_somewhere_to_go() -> None:
    """A Pi 3 must not get a half-working install that looks like a configuration choice."""
    board = BoardInfo(kind="unsupported", model="Raspberry Pi 3 Model B Rev 1.2")

    with pytest.raises(ConfigError) as excinfo:
        resolve_profile({"profile": AUTO_PROFILE}, board)

    message = excinfo.value.format()
    assert "Raspberry Pi 3 Model B Rev 1.2" in message
    assert LAST_PI3_RELEASE in message
    assert excinfo.value.problems[0].path == "config.profile"


def test_an_explicit_profile_beats_detection() -> None:
    """The escape hatch for a board we classify wrongly: say which profile you want."""
    board = BoardInfo(kind="unsupported", model="Raspberry Pi 3 Model B Rev 1.2")
    assert resolve_profile({"profile": "pi4", "profiles": PROFILES}, board) == "pi4"


def test_the_environment_beats_the_file(monkeypatch) -> None:
    monkeypatch.setenv("HOUNDMIND_PROFILE", "pi5")
    assert resolve_profile({"profile": "pi4", "profiles": PROFILES}) == "pi5"


def test_a_misspelled_profile_is_an_error_with_a_suggestion() -> None:
    """It used to be a warning, so a typo ran the shipped cadence and looked like success."""
    with pytest.raises(ConfigError) as excinfo:
        resolve_profile({"profile": "pi45", "profiles": PROFILES})

    problem = excinfo.value.problems[0]
    assert problem.path == "config.profile"
    # The message has to name the alternatives: the operator cannot guess them.
    assert "pi4, pi5" in problem.message
    assert problem.hint in PROFILES


def test_a_resolved_profile_may_have_no_overrides_but_a_named_one_may_not() -> None:
    """`profiles` is optional; naming a profile that the file does not define is not."""
    assert resolve_profile({"profile": AUTO_PROFILE}, BoardInfo("pi5")) == "pi5"

    with pytest.raises(ConfigError):
        resolve_profile({"profile": "pi5"}, BoardInfo("pi5"))


# --------------------------------------------------------------- the shipped file


def _shipped() -> dict:
    from houndmind_ai.core.config import default_config_path

    return json5.loads(default_config_path().read_text(encoding="utf-8"))


def test_the_shipped_file_asks_the_board() -> None:
    assert _shipped()["profile"] == AUTO_PROFILE


def test_the_shipped_profiles_are_the_two_editions() -> None:
    """Pi 3 was dropped; a `pi3` profile would be a promise the installer no longer keeps."""
    assert set(_shipped()["profiles"]) == set(PROFILES)


def test_the_pi5_thermal_warning_sits_above_the_pi5_idle_temperature() -> None:
    """A Pi 5 idles near 65 C, so the generic 70 C warning would degrade a healthy board and
    pull the `throttle_scans` lever. The override exists for that reason and must stay above
    the idle floor."""
    shipped = _shipped()
    generic = shipped["settings"]["performance"]["health_temp_warn_c"]
    pi5 = shipped["profiles"]["pi5"]["settings"]["performance"]["health_temp_warn_c"]

    assert pi5 > generic
    assert pi5 > 70.0


def test_the_shipped_config_records_the_profile_it_applied() -> None:
    config = load_config()

    assert isinstance(config, Config)
    assert config.profile in {"pi4", "pi5"}