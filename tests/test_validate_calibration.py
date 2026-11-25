"""`tools.validate_calibration` answers "can this saved trim be applied" without the dog (#258, #259).

The file it reads is written by `calibration/workflow.py:170-183` and applied at boot by
`hal/motors.py:606-622`, and that reader swallows every defect as a debug line — so a payload of the
wrong shape is indistinguishable from an uncalibrated dog until someone watches the dog walk. These
tests pin the verdicts: a consistent trim passes, a partial one is a note, and a channel that is
unknown, not a number or outside the vendor's clamp is a finding that names it.
"""

from __future__ import annotations

import json
from pathlib import Path

from houndmind_ai.hal.iface import SERVO_NAMES, SERVO_OFFSET_LIMIT_DEG
from tools.validate_calibration import calibration_path, check, main, validate


def write_trim(tmp_path: Path, offsets: dict, **result: object) -> Path:
    """A calibration file in the shape `calibration/workflow.py:176` writes it.

    `{"last_result": {...}, "updated_at": ...}`, because the offsets are nested one level down: a
    top-level map is the case a validator reading the wrong key passes on.
    """
    payload = {
        "last_result": {
            "timestamp": 1.0,
            "request": "servo_zero",
            "status": "ok",
            "servo_zero_offsets": offsets,
            **result,
        },
        "updated_at": 1.0,
    }
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def full_trim() -> dict[str, float]:
    """All twelve HAL channels, every value inside the clamp."""
    return {name: float(index) for index, name in enumerate(SERVO_NAMES)}


def test_every_channel_inside_the_clamp_passes(tmp_path: Path, capsys) -> None:
    path = write_trim(tmp_path, full_trim())
    before = path.read_text(encoding="utf-8")

    assert main(["--file", str(path)]) == 0
    output = capsys.readouterr().out
    assert "12 of 12 channel(s) present" in output
    assert "0 error(s), 0 note(s)" in output
    assert path.read_text(encoding="utf-8") == before, "checking the trim must not write it"


def test_an_offset_beyond_the_vendor_clamp_is_refused_with_the_channel_named(
    tmp_path: Path, capsys
) -> None:
    offsets = full_trim()
    offsets["lf_leg"] = SERVO_OFFSET_LIMIT_DEG + 5.0
    path = write_trim(tmp_path, offsets)

    assert main(["--file", str(path)]) == 1
    output = capsys.readouterr().out
    assert "out_of_range" in output
    assert "'lf_leg'" in output
    assert "beyond the vendor clamp of +/-20.0" in output


def test_a_signed_value_inside_the_clamp_is_accepted(tmp_path: Path) -> None:
    """The clamp is symmetric, so -20.0 is as legal as +20.0 and neither is a finding."""
    offsets = full_trim()
    offsets["tail"] = -SERVO_OFFSET_LIMIT_DEG
    offsets["head_pitch"] = SERVO_OFFSET_LIMIT_DEG

    assert check({"last_result": {"servo_zero_offsets": offsets}}) == []
    assert validate(write_trim(tmp_path, offsets)) == 0


def test_a_partial_trim_is_a_note_and_keeps_the_exit_code(tmp_path: Path, capsys) -> None:
    """`iface.py:238-245` makes an unreadable joint absent, so eight of twelve is a legal file."""
    path = write_trim(tmp_path, {name: 1.0 for name in SERVO_NAMES[:8]})

    assert main(["--file", str(path)]) == 0
    output = capsys.readouterr().out
    assert "partial_trim" in output
    assert "absent: head_yaw, head_roll, head_pitch, tail" in output
    assert "0 error(s), 1 note(s)" in output


def test_an_unknown_channel_is_named_with_a_suggestion(tmp_path: Path, capsys) -> None:
    offsets = full_trim()
    offsets["lf_sholder"] = 2.0
    path = write_trim(tmp_path, offsets)

    assert main(["--file", str(path)]) == 1
    output = capsys.readouterr().out
    assert "unknown_channel" in output
    assert "'lf_sholder' is not a HAL servo channel" in output
    assert "did you mean 'lf_shoulder'?" in output


def test_a_value_that_is_not_a_number_is_a_finding(tmp_path: Path, capsys) -> None:
    path = write_trim(tmp_path, {"tail": "crooked"})

    assert main(["--file", str(path)]) == 1
    output = capsys.readouterr().out
    assert "not_numeric" in output
    assert "'crooked', which is not a number of degrees" in output


def test_json_true_is_not_a_measured_degree() -> None:
    """`True` coerces to `1.0` in Python, so a boolean has to be refused before the coercion."""
    findings = check({"last_result": {"servo_zero_offsets": {"tail": True}}})

    assert [finding.kind for finding in findings] == ["not_numeric", "partial_trim"]


def test_a_payload_without_last_result_is_not_a_clean_pass(tmp_path: Path, capsys) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"updated_at": 1.0}), encoding="utf-8")

    assert main(["--file", str(path)]) == 1
    assert "missing_section" in capsys.readouterr().out


def test_a_top_level_offset_map_is_not_what_the_reader_reads() -> None:
    """`motors.py:618` reads `last_result.servo_zero_offsets`; a stray top-level map reaches nothing."""
    assert [finding.kind for finding in check({"servo_zero_offsets": full_trim()})] == [
        "missing_section"
    ]


def test_a_run_that_carries_no_trim_is_a_note_that_names_it(tmp_path: Path, capsys) -> None:
    """Every request persists to the same file, so a `wall_follow` result is legal and has no trim."""
    payload = {"last_result": {"request": "wall_follow", "status": "ok"}, "updated_at": 1.0}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["--file", str(path)]) == 0
    output = capsys.readouterr().out
    assert "no_servo_trim" in output
    assert "'wall_follow'" in output


def test_a_file_that_is_not_json_is_a_finding(tmp_path: Path, capsys) -> None:
    """The boot-time reader logs this at debug and applies nothing; here it is the answer."""
    path = tmp_path / "calibration.json"
    path.write_text("not json", encoding="utf-8")

    assert main(["--file", str(path)]) == 1
    assert "malformed_json" in capsys.readouterr().out


def test_an_absent_file_is_a_note_and_exits_zero(tmp_path: Path, capsys) -> None:
    assert main(["--file", str(tmp_path / "nope.json")]) == 0
    output = capsys.readouterr().out
    assert "not_calibrated" in output
    assert "0 error(s), 1 note(s)" in output


def test_json_lists_every_finding(tmp_path: Path, capsys) -> None:
    offsets = full_trim()
    offsets["lf_leg"] = 30.0
    offsets["moon"] = 1.0
    del offsets["tail"]
    path = write_trim(tmp_path, offsets)

    assert main(["--file", str(path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"] == 2
    assert payload["notes"] == 1
    assert payload["channels"] == 11
    assert {finding["kind"] for finding in payload["findings"]} == {
        "out_of_range",
        "unknown_channel",
        "partial_trim",
    }


def test_json_stays_json_when_the_file_is_missing(tmp_path: Path, capsys) -> None:
    """A consumer parses this; the absent-file answer must not arrive as prose."""
    assert main(["--file", str(tmp_path / "nope.json"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    assert payload["notes"] == 1
    assert payload["findings"][0]["kind"] == "not_calibrated"


def test_a_missing_config_is_an_error_not_a_clean_pass(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(tmp_path / "nope.jsonc")]) == 2
    assert "cannot read" in capsys.readouterr().out


def test_the_default_path_is_the_persist_path_under_the_repo_root() -> None:
    """Both readers resolve a relative `persist_path` against the repo root, not the CWD."""
    path = calibration_path({})

    assert path.is_absolute()
    assert (path.parent.name, path.name) == ("data", "calibration.json")


def test_a_relative_persist_path_resolves_like_the_readers() -> None:
    default = calibration_path({})
    custom = calibration_path({"calibration": {"persist_path": "data/trim.json"}})

    assert custom == default.parent / "trim.json"


def test_an_absolute_persist_path_is_taken_as_it_is(tmp_path: Path) -> None:
    explicit = tmp_path / "trim.json"

    assert calibration_path({"calibration": {"persist_path": str(explicit)}}) == explicit
