"""The shipped routine fixtures: twenty files, each one a rule that must not rot.

`tests/fixtures/routines/` is a legal `settings.routines.dir`, so the store test loads it in place —
the quarantine rule gets exercised over real files rather than over strings a test invented. Every
`invalid_` fixture is asserted against the problem it is *named* for, because "it fails" would let a
fixture drift into failing for the wrong reason and quietly stop covering its rule.

The rules themselves live in `kernel/routine.py` and are pinned by `tests/test_routine.py`. What is
pinned here is that the set a user can copy behaves the way `docs/ROUTINES.md` says it does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.actions import Repertoire, repertoire_from_settings
from houndmind_ai.kernel.commands import canonical_action
from houndmind_ai.kernel.routine import check_routine, parse_routine
from houndmind_ai.kernel.routine_store import RoutineStore

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "routines"
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"

# The plan's exit criterion is "20 fixtures" (`.houndmind-local/docs/plans/p2-routines.md` §R8).
EXPECTED_FILES = 20

# stem -> (the path the validator reports, a substring of the message it must carry)
REFUSED = {
    "invalid_unknown_action": ("routine.steps[0].action", "is not in the repertoire"),
    "invalid_undeclared_param": ("routine.steps[0].params.wait", "does not read 'wait'"),
    "invalid_param_not_scalar": ("routine.steps[0].params.yaw", "got list"),
    "invalid_locomotion_without_optin": ("routine.steps[0].action", "allow_locomotion"),
    "invalid_optin_not_bool": ("routine.allow_locomotion", "expected true or false"),
    "invalid_empty_steps": ("routine.steps", "at least one step"),
    "invalid_too_many_steps": ("routine.steps", "the limit is"),
    "invalid_unknown_top_key": ("routine.description", "unknown key"),
    "invalid_unknown_step_key": ("routine.steps[0].wait", "unknown key"),
    "invalid_bad_slug": ("routine.id", "not a slug"),
}

# Both files are valid on their own; together the sorted-first keeps the id.
COLLISION_FIRST, COLLISION_SECOND = "collision_first", "collision_second"

# The ids the seven `valid_` files declare, plus the collision winner: what a store load must return.
ACCEPTED_IDS = {
    "minimal",
    "postures",
    "expressions",
    "head_and_sound",
    "say_hello",
    "patrol_march",
    "version_two",
    "collision",
}

NAMES = re.compile(r"^(valid|invalid|collision|malformed)_[a-z0-9_]+\.json$")


def shipped() -> Repertoire:
    """The repertoire a device runs: the built-in floor plus `config/actions.jsonc`."""
    return repertoire_from_settings(load_config(SETTINGS_FILE).settings)


def fixtures(prefix: str) -> list[Path]:
    return sorted(FIXTURES.glob(f"{prefix}_*.json"))


def document(stem: str) -> dict:
    return json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", fixtures("valid"), ids=lambda path: path.stem)
def test_a_valid_fixture_is_accepted_and_parses_to_its_own_steps(path: Path) -> None:
    """Accepted by the shipped catalog *and* parsed into exactly the steps the file names."""
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert check_routine(raw, shipped()) == []
    routine = parse_routine(raw)
    assert routine.id == raw["id"]
    assert [step.action for step in routine.steps] == [
        canonical_action(step["action"]) for step in raw["steps"]
    ]


@pytest.mark.parametrize("stem", REFUSED, ids=list(REFUSED))
def test_an_invalid_fixture_fails_for_its_stated_reason(stem: str) -> None:
    """The file is named for one rule; it has to be the rule that fires."""
    expected_path, expected_message = REFUSED[stem]

    problems = check_routine(document(stem), shipped())

    assert any(
        problem.path == expected_path and expected_message in problem.message for problem in problems
    ), f"{stem}: expected {expected_path} ~ {expected_message!r}, got {[str(p) for p in problems]}"


def test_the_store_loads_the_valid_files_and_refuses_the_rest() -> None:
    """One directory, twenty files: the good ones load and the bad ones are named, never hidden."""
    report = RoutineStore(FIXTURES).load(shipped())

    assert set(report.routines) == ACCEPTED_IDS
    assert set(report.refusals) == {f"{stem}.json" for stem in REFUSED} | {
        "malformed_not_json.json",
        f"{COLLISION_SECOND}.json",
    }


def test_two_files_with_one_id_keep_the_first_in_sorted_order() -> None:
    """Sorted order is what makes the winner reproducible between boots."""
    report = RoutineStore(FIXTURES).load(shipped())

    winner = report.get("collision")
    assert winner is not None
    assert [step.action for step in winner.steps] == [canonical_action("sit")]
    assert COLLISION_FIRST < COLLISION_SECOND
    assert COLLISION_FIRST in " ".join(problem.message for problem in report.refusals[f"{COLLISION_SECOND}.json"])


def test_every_fixture_is_named_for_what_it_proves() -> None:
    """A fixture whose name does not state its rule is a fixture nobody dares change."""
    for path in sorted(FIXTURES.glob("*.json")):
        assert NAMES.match(path.name), f"{path.name} does not say which rule it proves"


def test_the_fixture_set_is_the_size_the_plan_promised() -> None:
    """The exit criterion is a count, so it is asserted rather than counted by hand."""
    assert len(list(FIXTURES.glob("*.json"))) == EXPECTED_FILES
