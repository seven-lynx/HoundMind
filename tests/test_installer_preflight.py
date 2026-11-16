"""The installer's preflight, tested without a Pi (REL P1-S4).

`scripts/` is not a package, so the module is loaded by path. It does no I/O at import - the
convention `10-python.md` requires - which is what makes that safe.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _installer():
    spec = importlib.util.spec_from_file_location(
        "installer_core_under_test", ROOT / "scripts" / "installer_core.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = _installer()


def test_a_clean_boot_has_nothing_to_say() -> None:
    assert installer.throttle_warning("throttled=0x0") is None
    assert installer.throttle_warning("0x0") is None


def test_the_sticky_bits_name_what_happened() -> None:
    """Bits 16-18 are the since-boot record; that is what makes a post-reboot reading useful."""
    assert "under-voltage" in (installer.throttle_warning("throttled=0x10000") or "")
    both = installer.throttle_warning("throttled=0x50000") or ""
    assert "under-voltage" in both
    assert "throttling" in both


def test_the_current_condition_bits_alone_are_not_a_warning() -> None:
    """`0x5` is happening *now*; the sticky bits are the ones a long install should respect."""
    assert installer.throttle_warning("throttled=0x5") is None


@pytest.mark.parametrize("raw", [None, "", "garbage", "throttled=", "0xzz"])
def test_an_unreadable_reading_is_not_a_warning(raw) -> None:
    assert installer.throttle_warning(raw) is None


def test_free_space_is_measured_and_a_missing_path_is_not() -> None:
    assert installer.free_gb(ROOT) > 0
    assert installer.free_gb(ROOT / "no-such-directory") is None


def test_preflight_passes_on_a_roomy_checkout(tmp_path, capsys) -> None:
    assert installer.preflight(tmp_path) == 0
    assert "Free space:" in capsys.readouterr().out


def test_low_space_stops_the_run(tmp_path, capsys, monkeypatch) -> None:
    """The one refusal preflight is allowed: the card cannot hold the install."""
    monkeypatch.setattr(installer, "free_gb", lambda path: 0.5)

    assert installer.preflight(tmp_path) == 2

    out = capsys.readouterr().out
    assert "Preflight:" in out
    assert "free" in out


def test_a_throttled_pack_warns_without_stopping(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(installer, "free_gb", lambda path: 20.0)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "/usr/bin/vcgencmd" if name == "vcgencmd" else None)
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *a, **k: type("Done", (), {"stdout": "throttled=0x50000"})(),
    )

    assert installer.preflight(tmp_path) == 0

    out = capsys.readouterr().out
    assert "Power:" in out
    assert "under-voltage" in out
