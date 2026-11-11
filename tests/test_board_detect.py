"""Board detection — the answer a profile is chosen from.

The device tree is the only authority on which Pi is running, and every branch here is
reachable on a workstation: `classify_model` is pure and `detect` takes the path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from houndmind_ai.board.detect import BoardInfo, classify_model, detect


@pytest.mark.parametrize(
    ("model", "kind"),
    [
        ("Raspberry Pi 5 Model B Rev 1.0", "pi5"),
        ("Raspberry Pi 500 Rev 1.0", "pi5"),
        ("Raspberry Pi Compute Module 5 Rev 1.0", "pi5"),
        ("Raspberry Pi 4 Model B Rev 1.4", "pi4"),
        ("Raspberry Pi 400 Rev 1.0", "pi4"),
        ("Raspberry Pi Compute Module 4 Rev 1.0", "pi4"),
        ("Raspberry Pi 3 Model B Plus Rev 1.3", "unsupported"),
        ("Raspberry Pi 2 Model B Rev 1.1", "unsupported"),
        ("Raspberry Pi Zero 2 W Rev 1.0", "unsupported"),
        ("", "unknown"),
        ("Banana Pi BPI-M4", "unknown"),
    ],
)
def test_the_model_string_names_the_board(model: str, kind: str) -> None:
    assert classify_model(model) == kind


def test_a_revision_number_is_not_a_generation() -> None:
    """The shortcut is to look for the digit "5", and it is wrong.

    A Pi 4 at revision 1.5 is still a Pi 4. This is the failure mode the word boundaries in
    `_GENERATIONS` exist to prevent, and it is the one a later "simplification" reintroduces.
    """
    assert classify_model("Raspberry Pi 4 Model B Rev 1.5") == "pi4"
    assert classify_model("Raspberry Pi 5 Model B Rev 1.4") == "pi5"


def test_the_attribute_is_nul_terminated(tmp_path: Path) -> None:
    """The kernel writes a trailing NUL; it must not reach the stored model string."""
    model = tmp_path / "model"
    model.write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")

    info = detect(model)

    assert info.kind == "pi5"
    assert info.model == "Raspberry Pi 5 Model B Rev 1.0"
    assert info.supported is True


def test_a_missing_device_tree_is_unknown_and_not_fatal(tmp_path: Path) -> None:
    """CI, a workstation and a container have no device tree, and all three run the runtime."""
    info = detect(tmp_path / "absent")

    assert info.kind == "unknown"
    assert info.model == ""
    assert info.supported is False


def test_the_default_path_answers_without_raising() -> None:
    """`detect()` with no argument is what a caller gets; it must never raise."""
    assert detect().kind in {"pi4", "pi5", "unsupported", "unknown"}


@pytest.mark.parametrize(
    ("kind", "supported"),
    [("pi4", True), ("pi5", True), ("unsupported", False), ("unknown", False)],
)
def test_only_the_shipped_editions_are_supported(kind: str, supported: bool) -> None:
    assert BoardInfo(kind=kind).supported is supported