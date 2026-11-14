"""The `requirements*.txt` mirrors against the extras they mirror.

`40-delivery.md` calls these files pinned mirrors for installs that bypass extras, which is only
true while they agree. They did not: `requirements.txt` was missing `pyttsx3` and `vosk` (#127), so
an install that followed it got a voice stack that could neither speak nor listen, and
`requirements-dev.txt` carried a bare `ruff` against the exact pin `pyproject.toml` keeps on
purpose. Nothing tested either, which is why both drifted unnoticed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# `name[extras]>=1.2` -> `name`. The spec suffix is stripped on purpose: this compares which
# packages a mirror carries, not which versions, except for the one pin `test_the_ruff_pin` names.
_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _extras() -> dict[str, list[str]]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    return project["optional-dependencies"]


def _mirror(name: str) -> list[str]:
    """The requirement lines of one mirror, comments and blank lines removed."""
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _names(specs: list[str]) -> set[str]:
    """Normalised package names: `SpeechRecognition` and `speech-recognition` are one package."""
    names: set[str] = set()
    for spec in specs:
        match = _NAME.match(spec)
        assert match, f"{spec!r} does not start with a package name"
        names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return names


def test_the_full_extra_and_its_mirror_carry_the_same_packages() -> None:
    assert _names(_mirror("requirements.txt")) == _names(_extras()["full"])


def test_the_dev_extra_and_its_mirror_carry_the_same_packages() -> None:
    assert _names(_mirror("requirements-dev.txt")) == _names(_extras()["dev"])


def test_the_ruff_pin_is_identical_in_both_files() -> None:
    """A bare `ruff` in the mirror is the drift the exact pin exists to prevent."""
    pinned = [spec for spec in _extras()["dev"] if _names([spec]) == {"ruff"}]
    assert pinned == ["ruff==0.17.4"]
    assert "ruff==0.17.4" in _mirror("requirements-dev.txt")


def test_the_lite_extra_stays_empty() -> None:
    """`lite` is deliberately empty: json5 and aiohttp are core dependencies, not extras."""
    assert _extras()["lite"] == []
    assert _mirror("requirements-lite.txt") == []
