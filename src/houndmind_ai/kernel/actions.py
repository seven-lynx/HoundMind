"""The repertoire: what the dog can do, and how much safety each thing answers to.

`config/actions.jsonc` has always listed the dog's actions; what it never said is what *kind* of
thing each one is. That gap is why the interlock could only ever ask one question — "is this a
gait?" — and why everything that is not a gait was checked against nothing at all.

This module supplies the missing half. Every action carries a class, and the class — never the
name — decides which part of the envelope applies (`act/interlock.py`):

| Class | Tilt latch | Obstacle stop | Battery floor | Deadman |
|---|---|---|---|---|
| ``locomotion`` | yes | yes | yes | yes |
| ``posture`` / ``expression`` | yes | no | yes | yes |
| ``non_motion`` | no | no | no | yes |

Membership is data in `config/actions.jsonc` — the catalog is already user-editable, and a user
who adds an action must be able to classify it in the same file. What lives *here* is the floor:
``forward``, ``backward``, ``turn_left``, ``turn_right`` and ``trot`` move the dog, and a config
file cannot say otherwise. The floor is applied twice on purpose — once at load, so a
misclassification is a loud `ConfigError` instead of a missing obstacle stop, and once at lookup,
so a repertoire built by a test or a hand-written dict cannot slip past it either.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

from houndmind_ai.hal.iface import DOG_ACTIONS
from houndmind_ai.kernel.commands import (
    KNOWN_ACTIONS,
    MOTION_ACTIONS,
    ActionClass,
    canonical_action,
)
from houndmind_ai.kernel.config_schema import Problem

logger = logging.getLogger(__name__)

__all__ = [
    "LOCOMOTION_FLOOR",
    "ActionSpec",
    "Repertoire",
    "action_classes_payload",
    "build_repertoire",
    "check_repertoire",
    "repertoire_from_settings",
]

# The actions that move the dog. They are `locomotion` in every repertoire, whatever a config file
# says: a class map that could downgrade `forward` would be a way to switch the obstacle stop off,
# and the safety envelope is not user config (`docs/ARCHITECTURE.md`).
LOCOMOTION_FLOOR: frozenset[str] = frozenset(MOTION_ACTIONS)

# The classification the runtime ships with: every action the HAL implements itself, so a gateway
# built with no config at all — a unit test, an embedding — still answers coherently.
_BUILTIN_CLASSES: dict[str, ActionClass] = {
    **{name: ActionClass.LOCOMOTION for name in MOTION_ACTIONS},
    "stand": ActionClass.POSTURE,
    "sit": ActionClass.POSTURE,
    "lie": ActionClass.POSTURE,
    "stretch": ActionClass.POSTURE,
    "wag_tail": ActionClass.EXPRESSION,
    "bark": ActionClass.EXPRESSION,
    "head": ActionClass.NON_MOTION,
    "rgb": ActionClass.NON_MOTION,
    "rpy": ActionClass.NON_MOTION,
    "sound": ActionClass.NON_MOTION,
    "speak": ActionClass.NON_MOTION,
    "stop": ActionClass.NON_MOTION,
}

# A hole here would be an action the HAL can execute and a config-free runtime cannot classify.
# `KNOWN_ACTIONS` covers the rest of the built-in vocabulary, so only a genuinely new HAL action
# can trip this. The table above is a literal; this fires only if the two are edited apart.
_unclassified = DOG_ACTIONS - set(_BUILTIN_CLASSES) - set(KNOWN_ACTIONS)
if _unclassified:  # pragma: no cover - a literal table, checked once at import
    logger.warning("HAL actions with no built-in class: %s", ", ".join(sorted(_unclassified)))


def _apply_floor(name: str, action_class: ActionClass) -> ActionClass:
    """Never let a weaker class reach one of the four actions that move the dog."""
    if name in LOCOMOTION_FLOOR and action_class is not ActionClass.LOCOMOTION:
        return ActionClass.LOCOMOTION
    return action_class


def _coerce_class(value: Any) -> ActionClass | None:
    if isinstance(value, ActionClass):
        return value
    if isinstance(value, str):
        try:
            return ActionClass(value.strip().lower())
        except ValueError:
            return None
    return None


def _coerce_params(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


@dataclass(frozen=True)
class ActionSpec:
    """One action: its canonical name, its class, and the parameters it reads."""

    name: str
    action_class: ActionClass
    params: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "class": self.action_class.value,
            "params": list(self.params),
        }


@dataclass(frozen=True)
class Repertoire:
    """A loaded classification. Lookups are canonical-name in, class out."""

    specs: Mapping[str, ActionSpec]

    @staticmethod
    def builtin() -> Repertoire:
        """The shipped floor plus the HAL's own actions, with nothing read from a file."""
        return Repertoire(
            specs={
                name: ActionSpec(name=name, action_class=_apply_floor(name, action_class))
                for name, action_class in _BUILTIN_CLASSES.items()
            }
        )

    def spec(self, action: str) -> ActionSpec | None:
        """The spec for `action`, or None when nothing classifies it."""
        return self.specs.get(canonical_action(action))

    def classify(self, action: str) -> ActionClass | None:
        spec = self.spec(action)
        return None if spec is None else spec.action_class

    def known(self) -> frozenset[str]:
        """Every canonical name this repertoire can judge."""
        return frozenset(self.specs)


def build_repertoire(raw_actions: Any) -> Repertoire:
    """Parse a classification table into a repertoire.

    Garbage entries are skipped rather than raised on: this runs wherever a settings table is
    read, and a runtime must not fall over because a hand-built context carried a bad class. The
    load path refuses bad input loudly instead (`check_repertoire`), which is where that belongs.
    """
    specs = dict(Repertoire.builtin().specs)
    if isinstance(raw_actions, Mapping):
        for key, entry in raw_actions.items():
            if not isinstance(key, str) or not isinstance(entry, Mapping):
                continue
            action_class = _coerce_class(entry.get("class"))
            if action_class is None:
                continue
            name = canonical_action(key)
            specs[name] = ActionSpec(
                name=name,
                action_class=_apply_floor(name, action_class),
                params=_coerce_params(entry.get("params")),
            )
    return Repertoire(specs=specs)


def action_classes_payload(raw_actions: Any) -> dict[str, dict[str, Any]]:
    """The canonical-keyed, JSON-shaped table that goes into `settings.behavior.action_classes`."""
    payload: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_actions, Mapping):
        return payload
    for key, entry in raw_actions.items():
        if not isinstance(key, str) or not isinstance(entry, Mapping):
            continue
        action_class = _coerce_class(entry.get("class"))
        if action_class is None:
            continue
        payload[canonical_action(key)] = {
            "class": action_class.value,
            "params": list(_coerce_params(entry.get("params"))),
        }
    return payload


def repertoire_from_settings(settings: Any) -> Repertoire:
    """The repertoire a runtime is actually running, from the context's `settings`.

    A runtime with no classification loaded gets the built-in one, so a module can be tested, or
    embedded, without a config file.
    """
    behavior = settings.get("behavior") if isinstance(settings, Mapping) else None
    raw = behavior.get("action_classes") if isinstance(behavior, Mapping) else None
    return build_repertoire(raw)


def check_repertoire(raw_actions: Any, catalog: Any) -> list[Problem]:
    """Every problem with a classification table, for a load-time refusal.

    Called by `core/config.py` after the catalog is attached, because the rule that matters is a
    cross-check: a name a bucket can offer must have a class, or the FSM can publish an intent the
    interlock then has to refuse. A class for a name no bucket uses is expected, not suspicious —
    that is exactly what `stop`, `head`, `rgb` and the audio actions are.

    `raw_actions` is the file's own text, before normalisation, so a downgraded `forward` is
    reported against the spelling the operator actually wrote.
    """
    problems: list[Problem] = []
    classified: dict[str, str] = {}
    valid = tuple(action_class.value for action_class in ActionClass)

    if raw_actions is None:
        raw_actions = {}
    if not isinstance(raw_actions, Mapping):
        return [
            Problem(
                "actions.actions",
                f"expected a table of action classes, got {raw_actions!r}",
            )
        ]

    for key, entry in raw_actions.items():
        if not isinstance(key, str):
            problems.append(
                Problem("actions.actions", f"action names must be strings, got {key!r}")
            )
            continue
        name = canonical_action(key)
        if name in classified:
            problems.append(
                Problem(
                    f"actions.actions.{key}",
                    f"'{name}' is already classified as '{classified[name]}'; one action cannot "
                    "appear twice",
                )
            )
            continue
        if not isinstance(entry, Mapping):
            problems.append(
                Problem(f"actions.actions.{key}", "expected a table with a 'class'")
            )
            continue
        action_class = entry.get("class")
        if not isinstance(action_class, str) or action_class not in valid:
            matches = get_close_matches(str(action_class), list(valid), n=1)
            problems.append(
                Problem(
                    f"actions.actions.{key}.class",
                    f"class must be one of {', '.join(valid)}, got {action_class!r}",
                    matches[0] if matches else None,
                )
            )
            continue
        for extra in entry:
            if extra not in ("class", "params"):
                matches = get_close_matches(str(extra), ["class", "params"], n=1)
                problems.append(
                    Problem(
                        f"actions.actions.{key}.{extra}",
                        "unknown key; it would be ignored",
                        matches[0] if matches else None,
                    )
                )
        params = entry.get("params")
        if params is not None and (
            not isinstance(params, list) or any(not isinstance(item, str) for item in params)
        ):
            problems.append(
                Problem(
                    f"actions.actions.{key}.params",
                    "expected a list of parameter names",
                )
            )
        classified[name] = action_class
        if name in LOCOMOTION_FLOOR and action_class != ActionClass.LOCOMOTION.value:
            problems.append(
                Problem(
                    f"actions.actions.{key}",
                    f"'{name}' moves the dog; it cannot be anything weaker than "
                    f"'{ActionClass.LOCOMOTION.value}'",
                )
            )

    for bucket, actions in _catalog_entries(catalog, problems):
        for index, action in enumerate(actions):
            if not isinstance(action, str):
                problems.append(
                    Problem(
                        f"actions.catalog.{bucket}[{index}]",
                        f"action names must be strings, got {action!r}",
                    )
                )
                continue
            name = canonical_action(action)
            if name not in classified:
                matches = get_close_matches(name, sorted(classified), n=1)
                problems.append(
                    Problem(
                        "actions.actions",
                        f"'{name}' is listed in the '{bucket}' catalog and has no class; "
                        'add it to "actions"',
                        matches[0] if matches else None,
                    )
                )
    return problems


def _catalog_entries(
    catalog: Any, problems: list[Problem]
) -> Iterator[tuple[str, list[Any]]]:
    """Yield `(bucket, actions)` for every well-formed bucket, reporting the others."""
    if catalog is None:
        return
    if not isinstance(catalog, Mapping):
        problems.append(
            Problem("actions.catalog", f"expected a table of buckets, got {catalog!r}")
        )
        return
    for bucket, actions in catalog.items():
        if not isinstance(actions, list):
            problems.append(
                Problem(f"actions.catalog.{bucket}", "expected a list of action names")
            )
            continue
        yield str(bucket), actions
