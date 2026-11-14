"""The supported interpreter range, held equal in the two places that carry a copy of it.

`pyproject.toml` declares `>=3.11,<3.14`. `scripts/installer_core.py` picks the interpreter before
anything is installed, and `src/tools/installer_verify.py` is the check `docs/INSTALL.md` tells a
user to run after installing. The first cannot import the second - `scripts/` is not a package and
the package does not exist yet - so the rule is mirrored and this file holds the copies equal, the
same bargain `tests/test_board_detect.py` makes for board detection.

#111 was that drift in one direction: the verifier certified a 3.10 environment the package refuses.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import pytest

from tools.installer_verify import is_supported_python

ROOT = Path(__file__).resolve().parents[1]

# Both ends of the range, one either side, and a major that is not 3 at all.
VERSIONS = [(3, 9), (3, 10), (3, 11), (3, 12), (3, 13), (3, 14), (3, 15), (4, 0)]


@lru_cache(maxsize=1)
def _installer_core() -> ModuleType:
    """`scripts/installer_core.py`, loaded by path because it is not an importable package."""
    path = ROOT / "scripts" / "installer_core.py"
    spec = importlib.util.spec_from_file_location("_installer_core", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared_range() -> tuple[tuple[int, int], tuple[int, int]]:
    """`requires-python` as a floor and an exclusive ceiling, or a failure saying what it read."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        declared = str(tomllib.load(handle)["project"]["requires-python"]).strip()
    match = re.fullmatch(r">=(\d+)\.(\d+),<(\d+)\.(\d+)", declared)
    assert match is not None, f"requires-python is not a closed range: {declared!r}"
    floor_major, floor_minor, cap_major, cap_minor = (int(part) for part in match.groups())
    return (floor_major, floor_minor), (cap_major, cap_minor)


@pytest.mark.parametrize("version", VERSIONS)
def test_the_verifier_and_the_installer_agree(version: tuple[int, int]) -> None:
    """One rule, two copies; a copy that drifts is what #111 was."""
    assert is_supported_python(version) == _installer_core().is_supported_python(version)


@pytest.mark.parametrize("version", VERSIONS)
def test_both_copies_answer_for_what_pyproject_declares(version: tuple[int, int]) -> None:
    """Neither copy is allowed to be right on its own, so this checks both against the declaration."""
    (floor_major, floor_minor), (cap_major, cap_minor) = _declared_range()
    expected = version[0] == floor_major and floor_minor <= version[1] < cap_minor
    assert is_supported_python(version) is expected
    assert _installer_core().is_supported_python(version) is expected


WRAPPERS = [ROOT / "scripts" / "install_houndmind.sh", ROOT / "scripts" / "install_houndmind.ps1"]


@pytest.mark.parametrize("wrapper", WRAPPERS, ids=lambda path: path.name)
def test_the_wrappers_probe_the_declared_range_newest_first(wrapper: Path) -> None:
    """The wrapper is step 1 of the install guide, and it used to refuse 3.12 and 3.13 (#113).

    The probe order is load-bearing too: a Pi with both 3.10 and 3.11 on PATH was silently given the
    3.10, and the `pip install -e .` that followed was refused.
    """
    text = wrapper.read_text(encoding="utf-8")
    # A comment may explain why 3.10 is refused; the code may not accept it.
    assert "python3.10" not in text
    assert "'3.10'" not in text, "the PowerShell accept-list still carries 3.10"
    assert "3.10)" not in text, "a shell case arm still accepts 3.10"
    assert re.findall(r"python3\.(1[0-9])", text)[:3] == ["13", "12", "11"]


def test_the_installer_clones_the_robot_hat_the_reference_set_documents() -> None:
    """`docs/pidog/` is verified against 2.5.x; a `v2.0` default installed a tree it does not describe."""
    assert _installer_core().ROBOT_HAT_BRANCH == "2.5.x"


def test_the_installer_probes_the_robot_hat_surface_pidog_imports() -> None:
    """Installed is not usable: `robot_hat/__init__.py` gates the names `pidog` imports (#114)."""
    probe = _installer_core().ROBOT_HAT_PROBE
    for name in ("Robot", "Pin", "Ultrasonic", "utils", "Music", "I2C"):
        assert name in probe


def test_310_is_refused_and_311_through_313_are_not() -> None:
    """The defect in one line: the verifier said `Python: 3.10 -> OK` and pip then refused it."""
    assert is_supported_python((3, 10)) is False
    assert [is_supported_python((3, minor)) for minor in (11, 12, 13)] == [True, True, True]
    assert is_supported_python((3, 14)) is False
