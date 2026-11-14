"""`--preset` on the installer: the flag means the same thing on every board (#29).

A Pi 4 used to force `full` whatever the flag said, so `--preset lite` attempted the
dlib/opencv/rtabmap stack the user had just asked to skip - while the same flag on a Pi 5 meant
lite. `auto` keeps the documented defaults, so the change is to the flag, not to a fresh install.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


@lru_cache(maxsize=1)
def _installer():
    """`scripts/installer_core.py`, loaded by path because it is not an importable package."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "installer_core.py"
    spec = importlib.util.spec_from_file_location("_installer_core_preset", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("pi_class", "requested", "expected"),
    [
        ("pi4", "lite", "lite"),
        ("pi4", "full", "full"),
        ("pi5", "lite", "lite"),
        ("pi5", "full", "full"),
        ("unknown", "lite", "lite"),
        # `auto` is unchanged: a Pi 4 still gets the full set, everything else gets lite.
        ("pi4", "auto", "full"),
        ("pi5", "auto", "lite"),
        ("unknown", "auto", "lite"),
        ("unsupported", "auto", "lite"),
    ],
)
def test_an_explicit_preset_wins_and_auto_keeps_the_board_default(
    pi_class: str, requested: str, expected: str
) -> None:
    assert _installer().resolve_preset(pi_class, requested) == expected
