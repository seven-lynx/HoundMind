"""Routines: a user-authored sequence of actions, checked before it is allowed to run.

A routine is the most-requested screen and the most dangerous thing in the design: a list of servo
commands written by a user and executed unattended. The format is therefore built so that a bad
routine is impossible to *start*, rather than merely discouraged.

Three rules carry the design.

1. **A routine is data, never code.** JSON with a flat step list: no expressions, no loops, nothing
   that can fail to terminate. Every step names an action the repertoire reports
   (`kernel/actions.py`), so this validator and `GET /api/v1/repertoire` cannot disagree about what
   the dog can do — the menu a client builds a routine from is the menu that accepts it.
2. **A routine that cannot run in full is refused.** An `allow_locomotion: false` routine holding a
   locomotion step is a validation error, not a runtime veto: a routine that half-runs is worse
   than one that never starts (`robot-pet-design.md` §8.2).
3. **Every present key is checked for being known.** A typo'd `allow_locomotion` must not be
   silently ignored, because ignoring it means a routine the user marked harmless walks the dog.
   `kernel/actions.py` makes the same choice for the classification table, so this module copies
   its hand-rolled shape — `Problem` plus `difflib` — instead of taking a `jsonschema` dependency.

The repertoire arrives as an argument, never from a module global: `Repertoire.builtin()` declares
no parameters for any action, so only a repertoire loaded from `config/actions.jsonc` can say that
`sound` reads `name` and `volume`. A table invented here would drift from the one the route serves.

What "declared" means is worth stating, because it is where this module refuses something the HAL
could technically accept: a parameter key is legal only if the action's catalog entry lists it. The
vendor honours `wait` for any servo action (`hal/vendor.py:385-404`), but `hal/motors.py` hands
parameters to the HAL for `_PARAM_ACTIONS` only, so a `wait` on `sit` would be dropped without a
word today (#69). Advertising it before that path exists would be the same silent half-run rule 2
forbids.

No I/O, no clock, no config at import time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from difflib import get_close_matches
from types import MappingProxyType
from typing import Any

from houndmind_ai.kernel.actions import Repertoire
from houndmind_ai.kernel.commands import ActionClass, canonical_action
from houndmind_ai.kernel.config_schema import Problem

__all__ = [
    "MAX_STEPS",
    "ROUTINE_KEYS",
    "STEP_KEYS",
    "Routine",
    "RoutineStep",
    "check_routine",
    "parse_routine",
]

# A routine runs unattended, one step per tick, and every step can move a servo. The cap is a
# bound on a single unattended run, not a judgement about ambitious choreography: 64 steps is
# around thirteen seconds at the 200 ms tick even if every step waited for the motion to finish.
MAX_STEPS = 64

# The keys a document may carry, in the order `robot-pet-design.md` §8.1 writes them. Unknown keys
# are reported rather than ignored — see rule 3 in the module docstring.
ROUTINE_KEYS: tuple[str, ...] = ("id", "name", "version", "allow_locomotion", "steps")
STEP_KEYS: tuple[str, ...] = ("action", "params")

# An id names the routine *and* the file it lives in (`settings.routines.dir/<id>.json`), so it is
# a slug: a path separator or a `..` here would be resolved by the store, not by this module.
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _is_scalar(value: Any) -> bool:
    """True for the JSON scalars a HAL call can actually carry.

    A nested table or list never reaches a servo, so it is reported here instead of being
    stringified somewhere downstream and quietly becoming `"{'yaw': 1}"`.
    """
    return isinstance(value, (str, bool, int, float))


@dataclass(frozen=True)
class RoutineStep:
    """One step: an action, and the parameters it reads."""

    action: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"action": self.action, "params": dict(self.params)}


@dataclass(frozen=True)
class Routine:
    """A validated routine. Immutable: the runner keeps its own cursor, not a mutated copy."""

    id: str
    steps: tuple[RoutineStep, ...]
    name: str = ""
    version: int = 1
    allow_locomotion: bool = False

    def step(self, index: int) -> RoutineStep | None:
        """The step at `index`, or None past the end. The runner advances one per tick."""
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "allow_locomotion": self.allow_locomotion,
            "steps": [step.to_dict() for step in self.steps],
        }


def check_routine(raw: Any, repertoire: Repertoire) -> list[Problem]:
    """Every problem with a routine document, for a refusal that names what to fix.

    Empty list means the routine may run. `repertoire` is the one the runtime is actually using
    (`kernel/actions.py::repertoire_from_settings`), so a name the interlock cannot classify is
    refused here rather than at the first step that reaches the gateway.
    """
    problems: list[Problem] = []
    if not isinstance(raw, Mapping):
        return [Problem("routine", f"expected a table with a 'steps' list, got {raw!r}")]

    _check_known_keys(raw, ROUTINE_KEYS, "routine", problems)

    identifier = raw.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        problems.append(
            Problem("routine.id", "expected a non-empty string; it names the routine and its file")
        )
    elif not _ID_PATTERN.match(identifier):
        problems.append(
            Problem(
                "routine.id",
                f"{identifier!r} is not a slug: lowercase letters, digits, '_' or '-', "
                "at most 64 characters",
            )
        )

    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        problems.append(Problem("routine.name", f"expected a non-empty string, got {name!r}"))

    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        problems.append(
            Problem("routine.version", f"expected a whole number >= 1, got {version!r}")
        )

    # Anything other than a real `true` leaves locomotion off. A string "false" is the trap this
    # closes: it is truthy, so a coercion would switch the opt-in *on* while reading as off.
    allow_locomotion = raw.get("allow_locomotion", False)
    if not isinstance(allow_locomotion, bool):
        problems.append(
            Problem(
                "routine.allow_locomotion",
                f"expected true or false, got {allow_locomotion!r}; "
                "a string would turn the locomotion opt-in on while reading as off",
            )
        )

    steps = raw.get("steps")
    if steps is None:
        problems.append(Problem("routine.steps", "missing; a routine needs at least one step"))
        return problems
    if not isinstance(steps, list):
        problems.append(Problem("routine.steps", f"expected a list of steps, got {steps!r}"))
        return problems
    if not steps:
        problems.append(Problem("routine.steps", "a routine needs at least one step"))
        return problems
    if len(steps) > MAX_STEPS:
        problems.append(Problem("routine.steps", f"{len(steps)} steps; the limit is {MAX_STEPS}"))

    for index, step in enumerate(steps):
        _check_step(index, step, repertoire, allow_locomotion is True, problems)
    return problems


def parse_routine(raw: Any) -> Routine | None:
    """Build the model from a document, or return None when it cannot be built.

    Tolerant by design, like `kernel/actions.py::build_repertoire`: an unreadable step is skipped
    rather than raised on, because a routine reaches here from a file a user edited. The refusal
    belongs at the load path that can report it (`check_routine`), and a store calls both — check
    first, then parse — so nothing half-understood is ever executed.

    Call it only after `check_routine` is clean; what this function cannot see (an action the
    repertoire does not classify, a parameter the action does not read) it will happily copy.
    """
    if not isinstance(raw, Mapping):
        return None
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list):
        return None

    steps = tuple(
        step for step in (_coerce_step(entry) for entry in raw_steps) if step is not None
    )
    if not steps:
        return None

    name = raw.get("name")
    version = raw.get("version", 1)
    return Routine(
        id=identifier.strip(),
        steps=steps,
        name=name.strip() if isinstance(name, str) and name.strip() else identifier.strip(),
        version=version if isinstance(version, int) and not isinstance(version, bool) else 1,
        allow_locomotion=raw.get("allow_locomotion") is True,
    )


# --------------------------------------------------------------------------- internals


def _check_known_keys(
    entry: Mapping[Any, Any], allowed: tuple[str, ...], path: str, problems: list[Problem]
) -> None:
    """Report every key the format does not define, with a suggestion when one is close."""
    for key in entry:
        if not isinstance(key, str):
            problems.append(Problem(path, f"keys must be strings, got {key!r}"))
            continue
        if key in allowed:
            continue
        matches = get_close_matches(key, list(allowed), n=1)
        problems.append(
            Problem(
                f"{path}.{key}",
                "unknown key; it would be ignored",
                matches[0] if matches else None,
            )
        )


def _check_step(
    index: int,
    step: Any,
    repertoire: Repertoire,
    locomotion_allowed: bool,
    problems: list[Problem],
) -> None:
    """One step: a known action, a class the locomotion flag admits, and readable parameters."""
    path = f"routine.steps[{index}]"
    if not isinstance(step, Mapping):
        problems.append(Problem(path, f"expected a table with an 'action', got {step!r}"))
        return
    _check_known_keys(step, STEP_KEYS, path, problems)

    raw_action = step.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        problems.append(Problem(f"{path}.action", f"expected an action name, got {raw_action!r}"))
        return
    action = canonical_action(raw_action)
    spec = repertoire.spec(action)
    if spec is None:
        matches = get_close_matches(action, sorted(repertoire.known()), n=1)
        problems.append(
            Problem(
                f"{path}.action",
                f"'{action}' is not in the repertoire; GET /api/v1/repertoire lists what "
                "this dog can run",
                matches[0] if matches else None,
            )
        )
        declared: tuple[str, ...] | None = None
    else:
        declared = spec.params
        if spec.action_class is ActionClass.LOCOMOTION and not locomotion_allowed:
            problems.append(
                Problem(
                    f"{path}.action",
                    f"'{action}' moves the dog, but this routine sets allow_locomotion: false; "
                    "a routine that half-runs is worse than one that never starts",
                )
            )

    _check_params(path, action, step.get("params"), declared, problems)


def _check_params(
    path: str,
    action: str,
    raw_params: Any,
    declared: tuple[str, ...] | None,
    problems: list[Problem],
) -> None:
    """Every parameter key has to be one the action's catalog entry declares."""
    if raw_params is None:
        return
    if not isinstance(raw_params, Mapping):
        problems.append(
            Problem(f"{path}.params", f"expected a table of parameter values, got {raw_params!r}")
        )
        return
    for key, value in raw_params.items():
        if not isinstance(key, str):
            problems.append(
                Problem(f"{path}.params", f"parameter names must be strings, got {key!r}")
            )
            continue
        if declared is not None and key not in declared:
            matches = get_close_matches(key, list(declared), n=1)
            reads = ", ".join(declared) if declared else "no parameters"
            problems.append(
                Problem(
                    f"{path}.params.{key}",
                    f"'{action}' does not read '{key}'; the catalog says it reads {reads}",
                    matches[0] if matches else None,
                )
            )
        if not _is_scalar(value):
            problems.append(
                Problem(
                    f"{path}.params.{key}",
                    f"expected a string, number or true/false, got {type(value).__name__}",
                )
            )


def _coerce_step(entry: Any) -> RoutineStep | None:
    if not isinstance(entry, Mapping):
        return None
    raw_action = entry.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return None
    return RoutineStep(
        action=canonical_action(raw_action), params=_coerce_params(entry.get("params"))
    )


def _coerce_params(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return MappingProxyType({})
    return MappingProxyType(
        {key: item for key, item in value.items() if isinstance(key, str) and _is_scalar(item)}
    )

