"""The action classification: data in `config/actions.jsonc`, checked before the runtime starts.

Two rules carry the whole design. A name a catalog bucket can offer must have a class, or the
behavior module can publish an intent the interlock then has to refuse. And the four gaits that
move the dog cannot be reclassified, or a class map would be a way to switch the obstacle stop off.
Both are enforced at load *and* at lookup, so this file tests both.
"""

from __future__ import annotations

import json
from pathlib import Path

import json5
import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.hal.iface import DOG_ACTIONS
from houndmind_ai.kernel.actions import (
    LOCOMOTION_FLOOR,
    ActionClass,
    Repertoire,
    action_classes_payload,
    build_repertoire,
    check_repertoire,
    repertoire_from_settings,
)
from houndmind_ai.kernel.commands import KNOWN_ACTIONS
from houndmind_ai.kernel.config_schema import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"
ACTIONS_FILE = REPO_ROOT / "config" / "actions.jsonc"


def shipped() -> dict:
    return json5.loads(ACTIONS_FILE.read_text(encoding="utf-8"))


def copy_config_into(directory: Path) -> Path:
    """A workspace-shaped config directory, so `load_config` runs the real path."""
    (directory / "settings.jsonc").write_text(
        SETTINGS_FILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (directory / "actions.jsonc").write_text(
        ACTIONS_FILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory / "settings.jsonc"


# --------------------------------------------------------------- the shipped file


def test_the_shipped_catalog_is_fully_classified() -> None:
    """The file that ships has to pass the exact check the loader applies to it."""
    raw = shipped()
    assert check_repertoire(raw.get("actions"), raw.get("catalog")) == []


def test_every_hal_action_is_classified() -> None:
    """A gateway with no config still has an envelope, so the built-ins cannot have holes."""
    repertoire = repertoire_from_settings(load_config(SETTINGS_FILE).settings)
    missing = sorted(name for name in DOG_ACTIONS if repertoire.classify(name) is None)
    assert missing == []
    assert set(KNOWN_ACTIONS) <= Repertoire.builtin().known()


def test_the_shipped_file_classifies_one_spelling_of_each_action() -> None:
    """`nod lethargy` and `nod_lethargy` are one action; naming both was the bug."""
    classes = action_classes_payload(shipped()["actions"])
    assert "nod lethargy" not in classes
    assert classes["nod_lethargy"]["class"] == "expression"


# ------------------------------------------------------------------- the refusals


def test_a_bucket_name_with_no_class_is_refused_with_a_suggestion() -> None:
    problems = check_repertoire(
        {"sit": {"class": "posture"}, "stretch": {"class": "posture"}},
        {"idle": ["sit", "strech"]},
    )
    assert problems
    assert any("strech" in str(problem) for problem in problems)
    assert any(problem.hint == "stretch" for problem in problems)


def test_a_gait_cannot_be_reclassified_as_something_harmless() -> None:
    """The floor, at both layers: loud at load, unbypassable at lookup."""
    problems = check_repertoire({"forward": {"class": "non_motion"}}, {})
    assert any("moves the dog" in str(problem) for problem in problems)

    assert LOCOMOTION_FLOOR == {"forward", "backward", "turn_left", "turn_right"}
    unvalidated = build_repertoire({"forward": {"class": "non_motion"}})
    assert unvalidated.classify("forward") is ActionClass.LOCOMOTION


def test_two_spellings_of_one_action_are_refused() -> None:
    problems = check_repertoire(
        {"nod lethargy": {"class": "expression"}, "nod_lethargy": {"class": "expression"}}, {}
    )
    assert any("appear twice" in str(problem) for problem in problems)


def test_an_unknown_class_gets_a_suggestion() -> None:
    problems = check_repertoire({"sit": {"class": "postur"}}, {})
    assert problems
    assert problems[0].hint == "posture"


def test_a_typo_inside_a_class_entry_is_reported() -> None:
    problems = check_repertoire({"sit": {"class": "posture", "parms": []}}, {})
    assert any("unknown key" in str(problem) for problem in problems)


def test_params_must_be_a_list_of_names() -> None:
    problems = check_repertoire({"sit": {"class": "posture", "params": "volume"}}, {})
    assert any("list of parameter names" in str(problem) for problem in problems)


def test_a_table_that_is_not_a_table_is_refused() -> None:
    problems = check_repertoire(["sit"], {})
    assert problems
    assert "expected a table" in str(problems[0])


# ------------------------------------------------------------------ the repertoire


def test_the_payload_is_canonical_and_json_shaped() -> None:
    payload = action_classes_payload({"turn left": {"class": "locomotion", "params": ["speed"]}})
    assert payload == {"turn_left": {"class": "locomotion", "params": ["speed"]}}


@pytest.mark.parametrize("action", ["sound", "speak", "rgb", "head", "rpy", "stop"])
def test_the_hal_actions_are_non_motion(action: str) -> None:
    """An LED, a sound or a head angle must not be gated on a battery or a wall."""
    assert Repertoire.builtin().classify(action) is ActionClass.NON_MOTION


def test_a_runtime_with_no_classification_gets_the_builtin_one() -> None:
    """A missing settings table, junk and a half-built context all have to answer coherently."""
    assert repertoire_from_settings(None).classify("forward") is ActionClass.LOCOMOTION
    assert repertoire_from_settings({"behavior": {"action_classes": "junk"}}).classify(
        "sit"
    ) is ActionClass.POSTURE
    assert repertoire_from_settings({"behavior": None}).classify("moonwalk") is None


def test_a_catalog_action_is_known_once_it_is_classified() -> None:
    """`high five` is data: whether the runtime can run it is a config decision, not a constant."""
    assert Repertoire.builtin().classify("high five") is None
    assert build_repertoire({"high five": {"class": "posture"}}).classify(
        "high five"
    ) is ActionClass.POSTURE


# --------------------------------------------------------------- through the loader


def test_config_load_installs_a_canonical_classification(tmp_path) -> None:
    config = load_config(copy_config_into(tmp_path))
    classes = config.settings["behavior"]["action_classes"]
    assert classes["forward"] == {
        "class": "locomotion",
        "params": ["speed", "steps", "wait"],
    }
    assert classes["nod_lethargy"]["class"] == "expression"
    # Canonical keys, so the interlock's lookup cannot miss a spaced spelling.
    assert "turn left" not in classes
    assert "turn_left" in classes


def test_config_load_refuses_a_catalog_name_with_no_class(tmp_path) -> None:
    """The cross-check names the file the operator edited, before any hardware is touched."""
    (tmp_path / "settings.jsonc").write_text(
        SETTINGS_FILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    raw = shipped()
    raw["catalog"]["custom"] = ["moonwalk"]
    (tmp_path / "actions.jsonc").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ConfigError) as raised:
        load_config(tmp_path / "settings.jsonc")
    assert "moonwalk" in str(raised.value)


def test_config_load_refuses_a_weakened_gait(tmp_path) -> None:
    copy_config_into(tmp_path)
    raw = shipped()
    raw["actions"]["forward"] = {"class": "non_motion"}
    (tmp_path / "actions.jsonc").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ConfigError) as raised:
        load_config(tmp_path / "settings.jsonc")
    assert "moves the dog" in str(raised.value)
