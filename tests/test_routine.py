"""The routine model and its validator: a bad routine does not start, it reports.

A routine is JSON a user writes and the device then runs unattended, so every test here pins a rule
that refuses a document *before* the first step reaches a servo. The rules under test are the three
in `kernel/routine.py`: data not code, all-or-nothing (`allow_locomotion`), and no key silently
ignored. The last group covers `parse_routine`, which is tolerant by design because the loud refusal
belongs to the validator.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.actions import Repertoire, build_repertoire, repertoire_from_settings
from houndmind_ai.kernel.routine import (
    MAX_STEPS,
    Routine,
    RoutineStep,
    check_routine,
    parse_routine,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "config" / "settings.jsonc"


def shipped() -> Repertoire:
    """The repertoire a device runs: the built-in floor plus `config/actions.jsonc`."""
    return repertoire_from_settings(load_config(SETTINGS_FILE).settings)


def greeting(**overrides) -> dict:
    """The canon's morning greeting (§8.1), with the parameters today's catalog declares.

    §8.1 writes `stand {wait: true}`, `stretch {wait: true}` and `wag_tail {steps: 6}`. None of the
    three is declared in `config/actions.jsonc`, and `hal/motors.py` hands parameters to the HAL for
    `_PARAM_ACTIONS` only — locomotion since P2 R4, posture nowhere yet — so a `wait` on `stand` is
    dropped in silence. The validator refuses what the gateway would ignore, so the example is
    written here with the parameters that reach the HAL today; the posture half is **#69**.
    """
    document = {
        "id": "morning_greeting",
        "name": "Morning greeting",
        "version": 1,
        "allow_locomotion": False,
        "steps": [
            {"action": "sound", "params": {"name": "woohoo", "volume": 80}},
            {"action": "stand"},
            {"action": "stretch"},
            {"action": "wag_tail"},
            {"action": "rgb", "params": {"style": "breath", "color": "green", "bps": 2.0}},
            {"action": "speak", "params": {"text": "Good morning!", "volume": 70}},
        ],
    }
    document.update(overrides)
    return document


# ------------------------------------------------------------------ the valid routine


def test_the_worked_example_validates_against_the_shipped_repertoire() -> None:
    """The example the docs will print has to pass the check the device applies to it."""
    assert check_routine(greeting(), shipped()) == []


def test_a_parameter_the_catalog_does_not_declare_is_refused() -> None:
    """The catalog is the authority on what an action reads, not the vendor library.

    `hal/vendor.py:385-404` honours `wait` for any servo action, but `hal/motors.py` forwards
    parameters for `_PARAM_ACTIONS` only, and posture is not in that set yet (#69), so this routine
    would wait for nothing. Refused until the gateway carries it.
    """
    problems = check_routine(
        greeting(steps=[{"action": "sit", "params": {"wait": True}}]), shipped()
    )
    assert any("does not read 'wait'" in str(problem) for problem in problems)


def test_parameters_come_from_the_loaded_catalog_not_from_the_builtin_floor() -> None:
    """`Repertoire.builtin()` declares no parameters, so a `sound` step only passes with the file.

    This is the test that keeps the validator's repertoire argument honest: a module that invented
    its own parameter table would pass both halves of this assertion, and disagree with
    `GET /api/v1/repertoire`.
    """
    document = greeting(steps=[{"action": "sound", "params": {"name": "woohoo", "volume": 80}}])
    assert check_routine(document, shipped()) == []
    assert check_routine(document, Repertoire.builtin()) != []


# ------------------------------------------------------------------------- the refusals


def test_a_typoed_action_gets_a_suggestion() -> None:
    problems = check_routine(greeting(steps=[{"action": "stnad"}]), shipped())
    assert problems
    assert problems[0].hint == "stand"


def test_a_typoed_parameter_gets_a_suggestion() -> None:
    problems = check_routine(
        greeting(steps=[{"action": "sound", "params": {"volum": 80}}]), shipped()
    )
    assert any(problem.hint == "volume" for problem in problems)


def test_a_typoed_routine_key_gets_a_suggestion() -> None:
    """`alow_locomotion` is the dangerous typo: ignored, it would leave locomotion off unstated."""
    problems = check_routine(greeting(alow_locomotion=True), shipped())
    assert any(problem.hint == "allow_locomotion" for problem in problems)


def test_a_typoed_step_key_is_reported() -> None:
    problems = check_routine(
        greeting(steps=[{"action": "sound", "parms": {"volume": 80}}]), shipped()
    )
    assert any("unknown key" in str(problem) for problem in problems)
    assert any(problem.hint == "params" for problem in problems)


def test_a_parameter_value_must_be_a_scalar() -> None:
    """A nested table never reaches a servo, so it is refused instead of being stringified."""
    problems = check_routine(
        greeting(steps=[{"action": "head", "params": {"yaw": {"x": 1}}}]), shipped()
    )
    assert any("expected a string, number or true/false" in str(problem) for problem in problems)


def test_locomotion_in_a_no_locomotion_routine_is_refused() -> None:
    """§8.2: a routine that half-runs is worse than one that never starts."""
    steps = [{"action": "forward", "params": {"steps": 2}}]
    refused = check_routine(greeting(steps=steps), shipped())
    assert any("allow_locomotion: false" in str(problem) for problem in refused)

    allowed = check_routine(greeting(steps=steps, allow_locomotion=True), shipped())
    assert allowed == []


def test_the_locomotion_rule_follows_the_class_not_the_name() -> None:
    """A locomotion action a config file declared is a locomotion step, whatever it is called."""
    repertoire = build_repertoire({"creep": {"class": "locomotion"}})
    problems = check_routine(greeting(steps=[{"action": "creep"}]), repertoire)
    assert any("moves the dog" in str(problem) for problem in problems)


def test_an_empty_step_list_is_refused() -> None:
    problems = check_routine(greeting(steps=[]), shipped())
    assert any("at least one step" in str(problem) for problem in problems)


def test_a_missing_steps_key_is_refused() -> None:
    document = greeting()
    del document["steps"]
    problems = check_routine(document, shipped())
    assert any("at least one step" in str(problem) for problem in problems)


def test_steps_must_be_a_list() -> None:
    problems = check_routine(greeting(steps={"1": {"action": "sit"}}), shipped())
    assert any("expected a list of steps" in str(problem) for problem in problems)


def test_a_step_must_be_a_table() -> None:
    problems = check_routine(greeting(steps=["sit"]), shipped())
    assert any("expected a table with an 'action'" in str(problem) for problem in problems)


def test_one_step_too_many_is_refused() -> None:
    """An unattended run has a bound; the cap is `MAX_STEPS`, not the file size."""
    steps = [{"action": "sit"} for _ in range(MAX_STEPS + 1)]
    problems = check_routine(greeting(steps=steps), shipped())
    assert any(f"the limit is {MAX_STEPS}" in str(problem) for problem in problems)


def test_the_step_cap_admits_exactly_max_steps() -> None:
    steps = [{"action": "sit"} for _ in range(MAX_STEPS)]
    assert check_routine(greeting(steps=steps), shipped()) == []


@pytest.mark.parametrize("identifier", ["Morning Greeting", "../escape", "", "a" * 65])
def test_the_id_must_be_a_slug(identifier: str) -> None:
    """The id becomes a filename in R3; a path separator or `..` dies here, not in the store."""
    problems = check_routine(greeting(id=identifier), shipped())
    assert any(problem.path == "routine.id" for problem in problems)


@pytest.mark.parametrize("flag", ["false", "true", 1, 0, None])
def test_the_locomotion_flag_must_be_a_real_bool(flag: object) -> None:
    """A string `"false"` is truthy: coercing it would switch the opt-in on while reading as off."""
    problems = check_routine(greeting(allow_locomotion=flag), shipped())
    assert any(problem.path == "routine.allow_locomotion" for problem in problems)


@pytest.mark.parametrize("version", [0, -1, True, "1", 1.5])
def test_the_version_must_be_a_positive_whole_number(version: object) -> None:
    problems = check_routine(greeting(version=version), shipped())
    assert any(problem.path == "routine.version" for problem in problems)


def test_a_name_must_be_a_non_empty_string() -> None:
    problems = check_routine(greeting(name="   "), shipped())
    assert any(problem.path == "routine.name" for problem in problems)


def test_a_document_that_is_not_a_table_is_refused() -> None:
    problems = check_routine([{"action": "sit"}], shipped())
    assert problems and problems[0].path == "routine"


# ----------------------------------------------------------------------------- the model


def test_an_action_name_is_canonicalised_when_parsed() -> None:
    """Producers may spell motion with spaces; the model speaks the underscored vocabulary only.

    `kernel/commands.py::canonical_action` is the only translation, so the runner never has to know
    that a client wrote `turn left`.
    """
    routine = parse_routine(
        greeting(steps=[{"action": "turn left"}], allow_locomotion=True)
    )
    assert routine is not None
    assert routine.steps[0].action == "turn_left"


def test_a_parsed_routine_round_trips() -> None:
    """The wire shape is what a client writes and what the route returns, so it must be stable."""
    routine = parse_routine(greeting())
    assert routine is not None
    again = parse_routine(routine.to_dict())
    assert again == routine
    assert routine.to_dict()["steps"] == [
        {"action": "sound", "params": {"name": "woohoo", "volume": 80}},
        {"action": "stand", "params": {}},
        {"action": "stretch", "params": {}},
        {"action": "wag_tail", "params": {}},
        {"action": "rgb", "params": {"style": "breath", "color": "green", "bps": 2.0}},
        {"action": "speak", "params": {"text": "Good morning!", "volume": 70}},
    ]


def test_an_absent_name_defaults_to_the_id() -> None:
    """A client that shows a list needs a label even when the author did not write one."""
    document = greeting()
    del document["name"]
    routine = parse_routine(document)
    assert routine is not None and routine.name == "morning_greeting"


def test_parsing_never_invents_a_locomotion_opt_in() -> None:
    """The tolerant builder still fails safe: only a real `true` opts locomotion in."""
    routine = parse_routine(
        {"id": "x", "allow_locomotion": "true", "steps": [{"action": "sit"}]}
    )
    assert routine is not None and routine.allow_locomotion is False


def test_the_step_cursor_stops_at_the_end() -> None:
    routine = parse_routine(greeting())
    assert routine is not None
    assert routine.step(0) == RoutineStep(action="sound", params={"name": "woohoo", "volume": 80})
    assert routine.step(len(routine.steps) - 1) is not None
    assert routine.step(len(routine.steps)) is None
    assert routine.step(-1) is None


@pytest.mark.parametrize(
    "raw",
    [None, [], "morning_greeting", {}, {"id": "x"}, {"id": "x", "steps": []}, {"steps": []}],
)
def test_parse_returns_none_for_a_document_it_cannot_build(raw: object) -> None:
    """No half-built routine: the store reports the file and moves on (`check_routine`)."""
    assert parse_routine(raw) is None


def test_parse_skips_a_step_it_cannot_read() -> None:
    """Tolerant like `build_repertoire`: the unreadable step goes, the readable one stays."""
    routine = parse_routine(
        {"id": "x", "steps": [{"action": "sit"}, "wave", {"params": {"yaw": 10}}]}
    )
    assert routine is not None
    assert [step.action for step in routine.steps] == ["sit"]


def test_a_frozen_step_cannot_be_edited_after_validation() -> None:
    """The runner keeps its own cursor rather than mutating a validated step."""
    step = RoutineStep(action="sit", params={"wait": True})
    with pytest.raises(FrozenInstanceError):
        step.action = "forward"  # type: ignore[misc]


def test_the_model_is_typed_as_the_documented_dataclasses() -> None:
    routine = parse_routine(greeting())
    assert isinstance(routine, Routine)
    assert all(isinstance(step, RoutineStep) for step in routine.steps)
