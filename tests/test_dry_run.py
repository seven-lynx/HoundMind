"""`--dry-run` proves a start is motionless (#405).

Before this flag there were two states: the dog runs, or the process fails. A start could not be
shown to be still, so "I proved it moves nothing" was a claim rather than evidence. These cases hold
the two halves: the shipped config builds the whole registry and the fake dog records no call, and a
config that fails validation exits 2 naming the key.
"""

from __future__ import annotations

import logging
import sys

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.main import dry_run, main


def test_the_shipped_config_builds_every_module_and_moves_nothing() -> None:
    config = load_config()
    hal = FakeDogHAL()

    rows = dry_run(config, hal=hal)

    names = {row["name"] for row in rows}
    assert {"hal", "motion_gateway", "hal_motors"} <= names
    assert all(set(row) == {"name", "enabled", "required"} for row in rows)
    assert hal.calls == [], "a dry run asks the dog for nothing"


def test_a_module_the_config_turns_off_is_reported_as_such() -> None:
    """The point of the verdict list: what would run, before anything runs."""
    config = load_config()
    rows = {row["name"]: row for row in dry_run(config, hal=FakeDogHAL())}

    # `safety` ships off (README: safety is off by default for bug testing), so it must read so.
    assert rows["safety"]["enabled"] is False
    assert rows["hal"]["enabled"] is True


def test_a_config_that_fails_validation_exits_non_zero_and_names_the_key(
    tmp_path, monkeypatch, caplog
) -> None:
    bad = tmp_path / "settings.jsonc"
    bad.write_text('{"modules": {"not_a_module": {"enabled": true}}}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["houndmind_ai", "--dry-run", "--config", str(bad)])

    with caplog.at_level(logging.ERROR, logger="houndmind_ai.main"):
        with pytest.raises(SystemExit) as exit_info:
            main()

    assert exit_info.value.code == 2
    assert "not_a_module" in caplog.text
