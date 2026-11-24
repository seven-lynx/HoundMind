"""`tools.validate_config` answers "would the runtime accept this file" without the dog.

The loader refuses a bad config before a single module starts, so the two ways to ask were to boot
the dog or to PATCH a live one. These tests pin the four verdicts the tool gives - clean, schema
problem, cross-field warning, file that will not parse - against the shipped config for the clean
case, so "clean" means the file that actually ships rather than a fixture's idea of a legal one.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.validate_config import check, main

SHIPPED = Path(__file__).resolve().parents[1] / "config" / "settings.jsonc"


def write_config(tmp_path: Path, tree: dict) -> Path:
    """A settings file in the loader's own root shape: `{"settings": ..., "modules": ...}`."""
    path = tmp_path / "settings.jsonc"
    path.write_text(json.dumps(tree), encoding="utf-8")
    return path


def test_the_shipped_config_would_load(capsys) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "0 error(s), 0 warning(s)" in output
    assert "config/settings.jsonc" in output.replace("\\", "/")


def test_a_retired_module_key_is_named(tmp_path: Path, capsys) -> None:
    """#392's retired name: the schema answers with what replaced it, and the key is printed."""
    path = write_config(tmp_path, {"modules": {"telemetry_dashboard": {"enabled": False}}})

    assert main(["--config", str(path)]) == 1
    output = capsys.readouterr().out
    assert "config.modules.telemetry_dashboard" in output
    assert "retired" in output
    assert "1 error(s), 0 warning(s)" in output


def test_a_module_typo_gets_a_suggestion(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path, {"modules": {"watchdg": {"enabled": True}}})

    assert main(["--config", str(path)]) == 1
    assert "did you mean 'watchdog'?" in capsys.readouterr().out


def test_a_cross_field_warning_keeps_exit_zero(tmp_path: Path, capsys) -> None:
    """Each value is legal; together they are wrong, and `validate_config` says so without refusing."""
    path = write_config(
        tmp_path, {"settings": {"sensors": {"distance_min_cm": 40, "distance_max_cm": 20}}}
    )

    assert main(["--config", str(path)]) == 0
    output = capsys.readouterr().out
    assert "sensors.distance_min_cm should be less than distance_max_cm" in output
    assert "0 error(s), 1 warning(s)" in output


def test_the_loader_names_a_profile_the_schema_cannot_see(tmp_path: Path, capsys) -> None:
    """The tree has no opinion on `profile`; `resolve_profile` does (`core/config.py:136`)."""
    path = write_config(tmp_path, {"profile": "pi3"})

    assert main(["--config", str(path)]) == 1
    output = capsys.readouterr().out
    assert "config.profile" in output
    assert "unknown profile 'pi3'" in output


def test_a_file_that_will_not_parse_is_exit_two_not_a_traceback(
    tmp_path: Path, capsys
) -> None:
    """A stray brace is not a finding: there is no key to name, so the question could not be asked."""
    path = tmp_path / "settings.jsonc"
    path.write_text('{ "settings": { "loop": ', encoding="utf-8")

    assert main(["--config", str(path)]) == 2
    output = capsys.readouterr().out
    assert "unparsable" in output
    assert "Unexpected end of input" in output


def test_a_missing_file_is_exit_two_not_a_clean_pass(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(tmp_path / "nope.jsonc")]) == 2
    assert "cannot read" in capsys.readouterr().out


def test_json_lists_every_problem_with_its_key(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path, {"modules": {"watchdg": {"enabled": True}}})

    assert main(["--config", str(path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"] == 1
    assert payload["warnings"] == 0
    finding = payload["findings"][0]
    assert finding["path"] == "config.modules.watchdg"
    assert finding["kind"] == "invalid"
    assert finding["severity"] == "error"
    assert finding["hint"] == "watchdog"


def test_json_counts_warnings_without_calling_them_errors(tmp_path: Path, capsys) -> None:
    path = write_config(
        tmp_path, {"settings": {"sensors": {"distance_min_cm": 40, "distance_max_cm": 20}}}
    )

    assert main(["--config", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    assert payload["warnings"] == 1
    assert payload["findings"][0]["severity"] == "warning"


def test_json_stays_json_when_the_file_will_not_parse(tmp_path: Path, capsys) -> None:
    """A consumer parses this; exit `2` must not arrive as a traceback or as prose."""
    path = tmp_path / "settings.jsonc"
    path.write_text("{", encoding="utf-8")

    assert main(["--config", str(path), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["findings"][0]["kind"] == "unparsable"


def test_check_is_the_schema_tree_and_nothing_else() -> None:
    """`check` takes a parsed tree, so it answers without a file or a profile."""
    assert check({}) == []
    findings = check({"modules": {"watchdg": {"enabled": True}}})
    assert [(finding.kind, finding.path) for finding in findings] == [
        ("invalid", "config.modules.watchdg")
    ]


def test_the_shipped_config_is_not_written(capsys) -> None:
    """Read-only by construction (D1): the verdict costs the file nothing."""
    before = SHIPPED.read_bytes()

    assert main([]) == 0

    assert SHIPPED.read_bytes() == before
