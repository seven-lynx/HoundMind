"""A real schema for `config/settings.jsonc`.

The previous validator was ~170 lines of ``warnings.append(...)`` that only logged. Nothing
was rejected, so ``tick_hz: "fast"`` loaded, a misspelled key vanished without a word, and —
worst of all — any key placed under ``modules.<name>`` beyond ``enabled``/``required`` was
silently discarded by the config model while still being documented as if it worked.

This module makes a bad config a load-time error with a path and a suggestion, before any
hardware is touched. It is deliberately dependency-free: specs are plain dataclasses, so
validation costs nothing on a Pi and adds nothing to the install.

Scope: `loop`, `modules` and `profiles` are strict today. `settings` is validated
structurally only (it must be a table) and grows section by section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

__all__ = [
    "AnyValue",
    "Bool",
    "ConfigError",
    "FloatSpec",
    "IntSpec",
    "ListOf",
    "MapOf",
    "Problem",
    "Section",
    "StrSpec",
    "validate_config_tree",
]


@dataclass(frozen=True)
class Problem:
    """One reason a config file was rejected."""

    path: str
    message: str
    hint: str | None = None

    def __str__(self) -> str:
        suffix = f" (did you mean '{self.hint}'?)" if self.hint else ""
        return f"{self.path}: {self.message}{suffix}"


class ConfigError(ValueError):
    """Raised when a config file cannot be accepted."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = list(problems)
        super().__init__(self.format())

    def format(self) -> str:
        if not self.problems:
            return "configuration is invalid"
        lines = [f"configuration has {len(self.problems)} problem(s):"]
        lines.extend(f"  - {problem}" for problem in self.problems)
        return "\n".join(lines)


# --------------------------------------------------------------------------- specs


class Spec:
    """Base spec. Subclasses return (normalised_value, problems)."""

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        raise NotImplementedError


@dataclass(frozen=True)
class AnyValue(Spec):
    """Pass-through, for sections that are only checked for being the right shape."""

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        return value, []


@dataclass(frozen=True)
class Bool(Spec):
    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if isinstance(value, bool):
            return value, []
        return value, [Problem(path, f"expected true or false, got {value!r}")]


@dataclass(frozen=True)
class IntSpec(Spec):
    minimum: int | None = None
    maximum: int | None = None
    allow_none: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if value is None and self.allow_none:
            return None, []
        # bool is an int subclass; `"enabled": true` is not a tick rate.
        if isinstance(value, bool) or not isinstance(value, int):
            return value, [Problem(path, f"expected an integer, got {value!r}")]
        if self.minimum is not None and value < self.minimum:
            return value, [Problem(path, f"must be >= {self.minimum}, got {value}")]
        if self.maximum is not None and value > self.maximum:
            return value, [Problem(path, f"must be <= {self.maximum}, got {value}")]
        return value, []


@dataclass(frozen=True)
class FloatSpec(Spec):
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    allow_none: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if value is None and self.allow_none:
            return None, []
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value, [Problem(path, f"expected a number, got {value!r}")]
        number = float(value)
        if number != number:  # NaN
            return value, [Problem(path, "must be a real number, got NaN")]
        if self.minimum is not None:
            if self.exclusive_minimum and number <= self.minimum:
                return value, [Problem(path, f"must be > {self.minimum}, got {number}")]
            if not self.exclusive_minimum and number < self.minimum:
                return value, [Problem(path, f"must be >= {self.minimum}, got {number}")]
        if self.maximum is not None and number > self.maximum:
            return value, [Problem(path, f"must be <= {self.maximum}, got {number}")]
        return number, []


@dataclass(frozen=True)
class StrSpec(Spec):
    choices: tuple[str, ...] = ()

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if not isinstance(value, str):
            return value, [Problem(path, f"expected a string, got {value!r}")]
        if self.choices and value not in self.choices:
            suggestion = get_close_matches(value, self.choices, n=1)
            return value, [
                Problem(
                    path,
                    f"must be one of {', '.join(self.choices)}, got {value!r}",
                    suggestion[0] if suggestion else None,
                )
            ]
        return value, []


@dataclass(frozen=True)
class ListOf(Spec):
    item: Spec = field(default_factory=AnyValue)

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if not isinstance(value, list):
            return value, [Problem(path, f"expected a list, got {value!r}")]
        problems: list[Problem] = []
        out: list[Any] = []
        for index, entry in enumerate(value):
            normalised, found = self.item.validate(entry, f"{path}[{index}]")
            out.append(normalised)
            problems.extend(found)
        return out, problems


@dataclass(frozen=True)
class MapOf(Spec):
    """A table whose keys are user-chosen: module names, profile names, section names."""

    value: Spec = field(default_factory=AnyValue)

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if not isinstance(value, dict):
            return value, [Problem(path, f"expected a table, got {value!r}")]
        problems: list[Problem] = []
        out: dict[str, Any] = {}
        for key, entry in value.items():
            if not isinstance(key, str):
                problems.append(Problem(path, f"keys must be strings, got {key!r}"))
                continue
            normalised, found = self.value.validate(entry, f"{path}.{key}")
            out[key] = normalised
            problems.extend(found)
        return out, problems


@dataclass(frozen=True)
class Section(Spec):
    """A fixed-shape table. Unknown keys are an error, with a suggestion."""

    fields: dict[str, Spec] = field(default_factory=dict)
    allow_extra: bool = False

    def validate(self, value: Any, path: str) -> tuple[Any, list[Problem]]:
        if not isinstance(value, dict):
            return value, [Problem(path, f"expected a table, got {value!r}")]
        problems: list[Problem] = []
        out: dict[str, Any] = {}
        known = list(self.fields)
        for key, entry in value.items():
            if key not in self.fields:
                if self.allow_extra:
                    out[key] = entry
                    continue
                suggestion = get_close_matches(str(key), known, n=1)
                problems.append(
                    Problem(
                        f"{path}.{key}",
                        "unknown key; it would be ignored",
                        suggestion[0] if suggestion else None,
                    )
                )
                continue
            normalised, found = self.fields[key].validate(entry, f"{path}.{key}")
            out[key] = normalised
            problems.extend(found)
        return out, problems


# ------------------------------------------------------------------ tree schema

_LOOP = Section(
    fields={
        "tick_hz": IntSpec(minimum=1, maximum=100),
        # None means "run until stopped", which is the only sane default for a service.
        "max_cycles": IntSpec(minimum=1, allow_none=True),
    }
)

_MODULE_ENTRY = Section(fields={"enabled": Bool(), "required": Bool()})

_PROFILES = MapOf(
    Section(
        fields={
            "loop": _LOOP,
            "modules": MapOf(_MODULE_ENTRY),
            "settings": Section(fields={}, allow_extra=True),
        }
    )
)

_TOP = Section(
    fields={
        "profile": StrSpec(),
        "profiles": _PROFILES,
        "loop": _LOOP,
        "modules": MapOf(_MODULE_ENTRY),
        # Section-by-section validation of `settings` arrives incrementally; it must at
        # least be a table so a stray value cannot masquerade as a config section.
        "settings": MapOf(),
    }
)


def validate_config_tree(raw: Any) -> list[Problem]:
    """Validate and normalise a parsed settings tree.

    Returns the list of problems found. Non-empty means the config must not be used: callers
    raise :class:`ConfigError` so the process stops before it can move a servo.
    """
    _, problems = _TOP.validate(raw, "config")
    return problems