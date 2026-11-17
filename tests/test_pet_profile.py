"""The `pet` profile is a named end-user set, and it must not turn a safety module on."""

from __future__ import annotations

from pathlib import Path

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.config_schema import ConfigError

CONFIG = Path(__file__).resolve().parents[1] / "config" / "settings.jsonc"


def test_the_pet_profile_loads_and_keeps_the_safety_modules_off(monkeypatch) -> None:
    monkeypatch.setenv("HOUNDMIND_PROFILE", "pet")

    config = load_config(CONFIG)

    assert config.profile == "pet"
    assert config.loop.tick_hz == 10
    assert config.modules["health"].enabled is True
    for module in ("safety", "sensor_health", "balance"):
        assert config.modules[module].enabled is False, module


def test_the_pet_profile_leaves_the_watchdog_on(monkeypatch) -> None:
    monkeypatch.setenv("HOUNDMIND_PROFILE", "pet")

    config = load_config(CONFIG)

    assert config.modules["watchdog"].enabled is True


def test_a_stray_profile_name_is_still_refused(monkeypatch) -> None:
    monkeypatch.setenv("HOUNDMIND_PROFILE", "petz")

    with pytest.raises(ConfigError) as excinfo:
        load_config(CONFIG)

    assert "petz" in excinfo.value.format()
