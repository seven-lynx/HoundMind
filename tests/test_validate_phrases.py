"""`tools.validate_phrases` answers "can this phrase reach an action" without the dog (#258, #321).

A phrase whose target nothing can execute is silent by construction, so the only way it used to be
found was by saying it and watching nothing happen. These tests pin the four verdicts the tool
gives — dead target, dead alias, cycle, shadowed key — against a settings file that is otherwise the
shipped one, so the answer comes from the real repertoire rather than a fixture's idea of it.
"""

from __future__ import annotations

import json
from pathlib import Path

from houndmind_ai.core.config import load_config
from tools.validate_phrases import check, main, validate


def broken_config(tmp_path: Path, command_map: dict, aliases: dict) -> Path:
    """The shipped settings with only the two phrase tables replaced.

    Written as `{"settings": ...}` because that is the root the loader reads (`core/config.py:75`),
    and `load_config` still installs the catalog's classes on the way back through, so a catalog
    action name like `doze_off` resolves here exactly as it does on the dog.
    """
    settings = load_config().settings
    voice = dict(settings["voice_assistant"])
    voice["command_map"] = command_map
    voice["aliases"] = aliases
    settings["voice_assistant"] = voice
    path = tmp_path / "settings.jsonc"
    path.write_text(json.dumps({"settings": settings}), encoding="utf-8")
    return path


def test_the_shipped_config_resolves_every_phrase(capsys) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "0 error(s), 0 warning(s)" in output


def test_a_dead_target_is_named(tmp_path: Path, capsys) -> None:
    path = broken_config(tmp_path, {"sit": "sit", "moon": "moonwalk"}, {})

    assert main(["--config", str(path)]) == 1
    output = capsys.readouterr().out
    assert "dead_target" in output
    assert "'moonwalk' has no class" in output


def test_a_target_that_is_a_near_miss_gets_a_suggestion(tmp_path: Path, capsys) -> None:
    path = broken_config(tmp_path, {"sit": "sit", "wag": "wag tails"}, {})

    assert main(["--config", str(path)]) == 1
    assert "did you mean 'wag_tail'?" in capsys.readouterr().out


def test_an_alias_whose_value_is_no_key_and_no_action_is_dead(tmp_path: Path, capsys) -> None:
    """The runtime resolves one hop, then uses the value raw — a typo is a dead action name."""
    path = broken_config(tmp_path, {"sit": "sit"}, {"go": "forwrd"})

    assert main(["--config", str(path)]) == 1
    output = capsys.readouterr().out
    assert "'forwrd' is not a command_map key" in output
    assert "passes it through as an action name" in output


def test_an_alias_cycle_is_reported_as_a_cycle_and_not_a_hang(tmp_path: Path, capsys) -> None:
    path = broken_config(tmp_path, {"sit": "sit"}, {"go": "shuffle", "shuffle": "go"})

    assert main(["--config", str(path)]) == 1
    output = capsys.readouterr().out
    assert "alias_cycle" in output
    assert "go -> shuffle -> go" in output


def test_an_alias_pointing_straight_at_a_real_action_is_fine(tmp_path: Path) -> None:
    """`sleep -> doze_off` works because the runtime uses the raw value and it is an action."""
    path = broken_config(tmp_path, {"sit": "sit"}, {"sleep": "doze_off"})

    settings = load_config(path).settings
    assert [finding.kind for finding in check(settings)] == []


def test_a_spaced_target_is_not_dead(tmp_path: Path) -> None:
    """`turn left` and `turn_left` are one action (`kernel/commands.py:169`), so neither is a typo."""
    path = broken_config(tmp_path, {"turn": "turn left", "wag": "wag tail"}, {})

    settings = load_config(path).settings
    assert check(settings) == []
    assert validate(settings) == 0


def test_a_shadowed_key_is_a_warning_and_keeps_the_exit_code(tmp_path: Path, capsys) -> None:
    """`stop` sits inside `stop now` and maps elsewhere, so the substring fallback can misaward it."""
    path = broken_config(tmp_path, {"stop": "stop", "stop now": "stand"}, {})

    assert main(["--config", str(path)]) == 0
    output = capsys.readouterr().out
    assert "shadowed_key" in output
    assert "0 error(s), 1 warning(s)" in output


def test_the_shipped_nested_pairs_are_not_warnings(capsys) -> None:
    """`wag` / `wag tail` nest on purpose and spell the same action; crying about them would be noise."""
    assert main([]) == 0
    assert "shadowed_key" not in capsys.readouterr().out


def test_json_lists_every_finding(tmp_path: Path, capsys) -> None:
    path = broken_config(tmp_path, {"moon": "moonwalk"}, {"go": "shuffle", "shuffle": "go"})

    assert main(["--config", str(path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"] == 3
    assert payload["warnings"] == 0
    assert {finding["kind"] for finding in payload["findings"]} == {"dead_target", "alias_cycle"}
    assert all(finding["severity"] == "error" for finding in payload["findings"])


def test_a_missing_config_is_an_error_not_a_clean_pass(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(tmp_path / "nope.jsonc")]) == 2
    assert "cannot read" in capsys.readouterr().out


def test_a_config_with_no_phrase_map_says_so_and_passes(capsys) -> None:
    assert validate({"voice_assistant": {}}) == 0
    assert "nothing to check" in capsys.readouterr().out


def test_json_stays_json_even_when_there_is_nothing_to_check(capsys) -> None:
    """A consumer parses this; the empty answer must not arrive as prose."""
    assert validate({"voice_assistant": {}}, as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "errors": 0, "warnings": 0, "findings": []}


def test_a_top_level_command_map_is_not_what_the_runtime_reads() -> None:
    """`optional/voice.py:80` reads `settings.voice_assistant`, so a stray top-level map is invisible."""
    assert check({"voice_assistant": {}, "command_map": {"moon": "moonwalk"}}) == []
