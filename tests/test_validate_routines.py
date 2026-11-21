"""`tools.validate_routines` answers "does this directory load" without the dog (#408).

The runtime quarantines a broken routine file and boots anyway, which is right at boot and useless as
a way to find a typo. The tool runs the same `RoutineStore` over the same directory, so its answer is
the loader's answer rather than a second opinion — and `tests/fixtures/routines/` is the real set,
one file per rule.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tools.validate_routines import main, validate

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "routines"


def copy_valid(tmp_path: Path) -> None:
    for path in sorted(FIXTURES.glob("valid_*.json")):
        shutil.copy(path, tmp_path / path.name)


def test_a_directory_of_legal_routines_exits_zero(tmp_path: Path, capsys) -> None:
    copy_valid(tmp_path)

    code = main(["--dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert code == 0
    assert "ok       minimal" in output
    assert "0 refused" in output


def test_a_broken_file_is_named_with_its_reason(tmp_path: Path, capsys) -> None:
    copy_valid(tmp_path)
    shutil.copy(FIXTURES / "invalid_empty_steps.json", tmp_path / "invalid_empty_steps.json")

    code = main(["--dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert code == 1
    assert "refused  invalid_empty_steps.json: routine.steps: " in output
    assert "at least one step" in output
    assert "1 refused" in output


def test_a_malformed_file_is_refused_before_the_validator_runs(tmp_path: Path, capsys) -> None:
    copy_valid(tmp_path)
    shutil.copy(FIXTURES / "malformed_not_json.json", tmp_path / "malformed_not_json.json")

    assert main(["--dir", str(tmp_path)]) == 1
    assert "refused  malformed_not_json.json" in capsys.readouterr().out


def test_a_missing_directory_is_an_error_not_an_empty_pass(tmp_path: Path, capsys) -> None:
    """A typo in the path must not read as "nothing to fix"."""
    assert main(["--dir", str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().out


def test_an_empty_directory_loads_nothing_and_says_so(tmp_path: Path, capsys) -> None:
    assert validate(tmp_path) == 0
    assert "no routine files" in capsys.readouterr().out
