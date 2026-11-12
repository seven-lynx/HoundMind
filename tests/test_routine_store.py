"""The routines directory: a bad file is refused by name and never costs the others.

The store is the only place a user's hand-written JSON reaches the runtime, so every test here is
about the quarantine rule: one broken file must not stop a dog from booting, and the file a user has
to edit must be named in the report. The files are written into `tmp_path` and the repertoire is the
shipped one, because the store validates against what the device can actually run.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.actions import Repertoire, repertoire_from_settings
from houndmind_ai.kernel.routine_store import (
    DEFAULT_ROUTINES_DIR,
    MAX_FILE_BYTES,
    RoutineStore,
    StoreReport,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"


def shipped() -> Repertoire:
    """The repertoire a device runs: the built-in floor plus `config/actions.jsonc`."""
    return repertoire_from_settings(load_config(SETTINGS_FILE).settings)


def document(**overrides) -> dict:
    """A small valid routine: an expression and a posture, nothing that walks."""
    doc = {
        "id": "morning_greeting",
        "name": "Morning greeting",
        "steps": [
            {"action": "sound", "params": {"name": "woohoo"}},
            {"action": "sit"},
        ],
    }
    doc.update(overrides)
    return doc


def place(directory: Path, name: str, payload: object) -> Path:
    """Write one routine file, the way a user would."""
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ------------------------------------------------------------- a directory and nothing else


def test_a_missing_directory_is_an_empty_report_and_is_not_created(tmp_path: Path) -> None:
    """A fresh install has no routines and still boots; a read must not create the directory."""
    missing = tmp_path / "routines"
    report = RoutineStore(missing).load(shipped())

    assert report.routines == {}
    assert report.refusals == {}
    assert report.ids() == ()
    assert not missing.exists()


def test_an_empty_directory_loads_nothing(tmp_path: Path) -> None:
    report = RoutineStore(tmp_path).load(shipped())
    assert report.refused == 0
    assert report.ids() == ()


def test_a_path_that_is_a_file_starts_the_runtime_empty(tmp_path: Path) -> None:
    """Pointing `dir` at a file is a user error, not a crash on the boot path."""
    not_a_directory = tmp_path / "routines"
    not_a_directory.write_text("{}", encoding="utf-8")

    report = RoutineStore(not_a_directory).load(shipped())

    assert report.routines == {}
    assert report.refusals == {}


def test_the_default_directory_is_device_state_outside_the_tree() -> None:
    """The G2 ruling: `~/.houndmind/routines`, and the tilde is expanded before it is used.

    A tracked `config/routines.jsonc` would make every edit a user makes show up as a dirty
    worktree, and a fresh clone would silently lose their routines.
    """
    assert DEFAULT_ROUTINES_DIR == "~/.houndmind/routines"
    store = RoutineStore()
    assert store.directory == Path(DEFAULT_ROUTINES_DIR).expanduser()
    assert "~" not in str(store.directory)


# ----------------------------------------------------------------------- the happy path


def test_a_valid_file_is_loaded_with_its_steps_in_order(tmp_path: Path) -> None:
    place(tmp_path, "greeting.json", document())

    report = RoutineStore(tmp_path).load(shipped())

    assert report.ids() == ("morning_greeting",)
    routine = report.get("morning_greeting")
    assert routine is not None
    assert [step.action for step in routine.steps] == ["sound", "sit"]
    assert routine.name == "Morning greeting"
    assert routine.allow_locomotion is False


def test_a_loaded_routine_round_trips_through_its_own_document(tmp_path: Path) -> None:
    """Load, serialise, load again — the model is what a client would write back.

    `to_dict` is normalised (every step carries `params`, the three optional keys are always
    present), so the comparison is against a second load, not the file's exact bytes.
    """
    place(tmp_path, "greeting.json", document())
    first = RoutineStore(tmp_path).load(shipped()).get("morning_greeting")
    assert first is not None

    second_dir = tmp_path / "again"
    second_dir.mkdir()
    place(second_dir, "greeting.json", first.to_dict())
    second = RoutineStore(second_dir).load(shipped()).get("morning_greeting")

    assert second == first
    assert first.to_dict()["steps"] == [
        {"action": "sound", "params": {"name": "woohoo"}},
        {"action": "sit", "params": {}},
    ]


def test_a_file_name_that_differs_from_its_id_is_allowed(tmp_path: Path) -> None:
    """The id is the identity; renaming the file must not break a routine a client stored."""
    place(tmp_path, "whatever.json", document(id="morning_greeting"))

    report = RoutineStore(tmp_path).load(shipped())

    assert report.refusals == {}
    assert report.get("morning_greeting") is not None
    assert report.get("whatever") is None


def test_an_uppercase_suffix_is_still_a_routine(tmp_path: Path) -> None:
    """A file manager is not always careful about case, and the suffix is not data."""
    place(tmp_path, "GREETING.JSON", document())

    report = RoutineStore(tmp_path).load(shipped())

    assert report.refusals == {}
    assert report.get("morning_greeting") is not None


def test_a_bom_from_a_windows_editor_still_loads(tmp_path: Path) -> None:
    """`utf-8-sig`, not `utf-8`: the BOM would otherwise read as a bad first character."""
    path = tmp_path / "greeting.json"
    path.write_text(json.dumps(document()), encoding="utf-8-sig")

    report = RoutineStore(tmp_path).load(shipped())

    assert report.refusals == {}
    assert report.get("morning_greeting") is not None


def test_two_routines_load_together_and_list_in_sorted_order(tmp_path: Path) -> None:
    place(tmp_path, "b.json", document(id="second_one"))
    place(tmp_path, "a.json", document(id="first_one"))

    report = RoutineStore(tmp_path).load(shipped())

    assert report.ids() == ("first_one", "second_one")


# ------------------------------------------------------------------------ the quarantine


def test_a_file_that_is_not_json_is_refused_by_name(tmp_path: Path) -> None:
    """The refusal has to name the file: that is the only thing a user can edit."""
    (tmp_path / "broken.json").write_text("{ this is not json", encoding="utf-8")
    place(tmp_path, "greeting.json", document())

    report = RoutineStore(tmp_path).load(shipped())

    assert list(report.refusals) == ["broken.json"]
    assert "not valid JSON" in report.refusals["broken.json"][0].message
    assert report.get("morning_greeting") is not None, "one bad file must not cost the others"


def test_an_unreadable_file_is_refused_and_the_others_load(tmp_path: Path) -> None:
    """Injected reader: a permission denied is the failure a test cannot provoke portably."""
    place(tmp_path, "locked.json", document(id="locked_one"))
    place(tmp_path, "greeting.json", document())

    def read_text(path: Path) -> str:
        if path.name == "locked.json":
            raise PermissionError(13, "Permission denied")
        return path.read_text(encoding="utf-8-sig")

    report = RoutineStore(tmp_path, read_text=read_text).load(shipped())

    assert list(report.refusals) == ["locked.json"]
    assert "could not be read" in report.refusals["locked.json"][0].message
    assert report.ids() == ("morning_greeting",)


def test_a_routine_the_validator_refuses_is_refused_by_name(tmp_path: Path) -> None:
    """`allow_locomotion: false` plus a gait is an error at load, not a veto at step 1.

    The refusal keeps the validator's own path (`routine.steps[0].action`), so the message points
    inside the file instead of repeating the file name the report already keyed it by.
    """
    place(tmp_path, "walk.json", document(id="walk_about", steps=[{"action": "forward"}]))

    report = RoutineStore(tmp_path).load(shipped())

    problems = report.refusals["walk.json"]
    assert [problem.path for problem in problems] == ["routine.steps[0].action"]
    assert "allow_locomotion" in problems[0].message
    assert report.get("walk_about") is None


def test_parameters_are_checked_against_the_loaded_repertoire(tmp_path: Path) -> None:
    """The store must hand the validator the runtime's repertoire, not the built-in floor.

    `Repertoire.builtin()` declares no parameters, so the same file loads against the shipped
    catalog and is refused against the floor — which is what proves the argument is not ignored.
    """
    place(tmp_path, "greeting.json", document())

    assert RoutineStore(tmp_path).load(shipped()).ids() == ("morning_greeting",)
    assert RoutineStore(tmp_path).load(Repertoire.builtin()).ids() == ()

    problems = RoutineStore(tmp_path).load(Repertoire.builtin()).refusals["greeting.json"]
    assert any("does not read 'name'" in problem.message for problem in problems)


def test_a_second_file_claiming_a_loaded_id_is_refused_and_names_the_first(tmp_path: Path) -> None:
    """Duplicate ids are a report, not a silent last-wins — and sorted order picks the winner."""
    place(tmp_path, "a_first.json", document(id="duplicated", steps=[{"action": "sit"}]))
    place(tmp_path, "b_second.json", document(id="duplicated", steps=[{"action": "stretch"}]))

    report = RoutineStore(tmp_path).load(shipped())

    assert report.ids() == ("duplicated",)
    assert list(report.refusals) == ["b_second.json"]
    assert "already loaded from a_first.json" in report.refusals["b_second.json"][0].message
    routine = report.get("duplicated")
    assert routine is not None
    assert [step.action for step in routine.steps] == ["sit"]


def test_only_json_files_are_candidates(tmp_path: Path) -> None:
    """A notes file, a commented draft and a directory must not read as broken routines."""
    place(tmp_path, "greeting.json", document())
    (tmp_path / "notes.txt").write_text("shopping list", encoding="utf-8")
    (tmp_path / "draft.jsonc").write_text(json.dumps(document(id="draft")), encoding="utf-8")
    (tmp_path / "archive.json").mkdir()

    report = RoutineStore(tmp_path).load(shipped())

    assert report.refusals == {}
    assert report.ids() == ("morning_greeting",)


def test_a_file_over_the_size_limit_is_refused_before_it_is_read(tmp_path: Path) -> None:
    """The cap is checked from `stat`, so a huge or binary file never reaches memory."""
    (tmp_path / "huge.json").write_bytes(b" " * (MAX_FILE_BYTES + 1))

    def read_text(path: Path) -> str:  # pragma: no cover - being called is the failure
        raise AssertionError(f"{path} was read before its size was checked")

    report = RoutineStore(tmp_path, read_text=read_text).load(shipped())

    assert list(report.refusals) == ["huge.json"]
    assert f"limit is {MAX_FILE_BYTES}" in report.refusals["huge.json"][0].message


# --------------------------------------------------------------------------- the report


def test_a_report_is_immutable(tmp_path: Path) -> None:
    """The runner and the control plane share one report; neither may edit what the other sees."""
    place(tmp_path, "greeting.json", document())
    report = RoutineStore(tmp_path).load(shipped())

    with pytest.raises(TypeError):
        report.routines["sneaky"] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        report.refusals["sneaky"] = ()  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        report.directory = tmp_path  # type: ignore[misc]


def test_an_empty_report_answers_every_question() -> None:
    report = StoreReport(directory=Path("/nowhere"))

    assert report.ids() == ()
    assert report.refused == 0
    assert report.get("anything") is None
