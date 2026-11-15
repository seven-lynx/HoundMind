"""The surgical writer behind `PATCH /config` (#174).

The file is JSONC and every comment in it is documentation, so the write has to be a replacement of
one value's bytes rather than a re-emit. These cases pin the three things that can go wrong in that:
a lookalike key inside a string or a comment, a value inside an array, and a file that changed under
the writer. The last test runs the writer over the **real** `config/settings.jsonc`, because a
scanner that only works on a fixture is the one that fails on the shipped file.
"""

from __future__ import annotations

import json
from pathlib import Path

import json5
import pytest

from houndmind_ai.services.config_writer import (
    ConfigWriteError,
    find_value_span,
    stamp_of,
    write_settings_values,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED = REPO_ROOT / "config" / "settings.jsonc"

DOC = """\
{
  // The settings block, with a comment that mentions brightness on purpose.
  "settings": {
    "led": {
      "brightness": 0.7, // the value under test
      "note": "not the key: \\"brightness\\": 9.9"
    },
    "motors": {
      // min_action_interval_s is mentioned here too, and must not match.
      "min_action_interval_s": 0.2
    }
  }
}
"""


def write(tmp_path: Path, text: str = DOC) -> Path:
    path = tmp_path / "settings.jsonc"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_value_is_replaced_and_every_comment_survives(tmp_path: Path) -> None:
    path = write(tmp_path)
    before = path.read_text(encoding="utf-8")

    write_settings_values(path, {"led.brightness": 0.4})

    after = path.read_text(encoding="utf-8")
    parsed = json5.loads(after)
    assert parsed["settings"]["led"]["brightness"] == 0.4
    # Only the value's bytes differ: the rest of the file, comments included, is byte-identical.
    assert after.replace("0.4", "0.7") == before
    assert after.count("//") == before.count("//")


def test_a_lookalike_inside_a_string_is_not_the_key(tmp_path: Path) -> None:
    path = write(tmp_path)

    write_settings_values(path, {"led.brightness": 0.4})

    parsed = json5.loads(path.read_text(encoding="utf-8"))
    assert parsed["settings"]["led"]["note"] == 'not the key: "brightness": 9.9'


def test_a_key_whose_value_is_not_a_scalar_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '{"settings": {"led": {"brightness": {"nested": 1}}}}',
    )

    with pytest.raises(ConfigWriteError) as caught:
        write_settings_values(path, {"led.brightness": 0.4})

    assert caught.value.status == 409
    assert "not written" in caught.value.detail


def test_a_key_that_is_not_written_in_the_file_is_refused(tmp_path: Path) -> None:
    """The writer will not invent a line and guess its indentation."""
    path = write(tmp_path, '{"settings": {"led": {}}}')

    with pytest.raises(ConfigWriteError) as caught:
        write_settings_values(path, {"led.brightness": 0.4})

    assert caught.value.status == 409
    assert "add it there once" in caught.value.detail


def test_a_file_changed_since_the_stamp_is_refused_and_left_alone(tmp_path: Path) -> None:
    """G1: the edit made on the device wins, and the runtime says so instead of clobbering it."""
    path = write(tmp_path)
    stale = stamp_of(path)
    path.write_text(DOC.replace("0.7", "0.6"), encoding="utf-8")

    with pytest.raises(ConfigWriteError) as caught:
        write_settings_values(path, {"led.brightness": 0.4}, expected_stamp=stale)

    assert caught.value.status == 409
    assert "changed on disk" in caught.value.detail
    assert "0.6" in path.read_text(encoding="utf-8")


def test_a_duplicated_key_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '{"settings": {"led": {"brightness": 0.7, "brightness": 0.8}}}',
    )

    with pytest.raises(ConfigWriteError) as caught:
        write_settings_values(path, {"led.brightness": 0.4})

    assert caught.value.status == 409
    assert "remove the duplicate" in caught.value.detail


def test_several_keys_are_written_in_one_pass(tmp_path: Path) -> None:
    path = write(tmp_path)

    write_settings_values(path, {"led.brightness": 0.4, "motors.min_action_interval_s": 0.5})

    parsed = json5.loads(path.read_text(encoding="utf-8"))
    assert parsed["settings"]["led"]["brightness"] == 0.4
    assert parsed["settings"]["motors"]["min_action_interval_s"] == 0.5
    assert not (tmp_path / "settings.jsonc.tmp").exists(), "the temp file must not survive"


def test_the_span_of_a_missing_key_is_none(tmp_path: Path) -> None:
    assert find_value_span(DOC, "led.nothing") is None


def test_the_shipped_settings_file_round_trips(tmp_path: Path) -> None:
    """The scanner has to work on the real file, not just on the fixture above."""
    path = tmp_path / "settings.jsonc"
    original = SHIPPED.read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    before = json5.loads(original)
    comments_before = original.count("//")

    write_settings_values(
        path, {"behavior.action_cooldown_s": 1.25, "led.brightness": 0.33}
    )

    rewritten = path.read_text(encoding="utf-8")
    after = json5.loads(rewritten)
    assert after["settings"]["behavior"]["action_cooldown_s"] == 1.25
    assert after["settings"]["led"]["brightness"] == 0.33
    assert rewritten.count("//") == comments_before, "every comment line is still there"
    # Nothing else moved: put the two values back in the parsed copy and the documents match.
    after["settings"]["behavior"]["action_cooldown_s"] = before["settings"]["behavior"][
        "action_cooldown_s"
    ]
    after["settings"]["led"]["brightness"] = before["settings"]["led"]["brightness"]
    assert after == before
    # And it is still a JSONC file, not a JSON dump: no key moved onto one line.
    assert rewritten.count("\n") == original.count("\n")
