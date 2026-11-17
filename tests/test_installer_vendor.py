"""The installer's vendor gaps, tested without a Pi (#255, #256, #259, #181).

`scripts/` is not a package, so the module is loaded by path - the same seam
`tests/test_installer_preflight.py` uses, and safe because the installer does no I/O at import.

Each case here is a defect that stayed silent on the dog: a vendor dependency nothing installed, a
sound pack `pip install` dropped on the floor, and an RTAB-Map build that spent an hour on a tree
that had no bindings source in it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _installer():
    spec = importlib.util.spec_from_file_location(
        "installer_core_vendor_under_test", ROOT / "scripts" / "installer_core.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = _installer()


def test_pyserial_is_probed_as_serial_and_installed_as_pyserial() -> None:
    """#255: `robot_hat doctor` checks `serial`, and PyPI's `serial` is a different package."""
    assert "serial" in installer.ROBOT_HAT_DEPS
    assert installer.vendor_pip_names(["serial", "lgpio"]) == ["pyserial", "lgpio"]


def test_the_sound_pack_lands_where_pidog_looks_for_it(tmp_path) -> None:
    """#256: `Pidog.SOUND_DIR` is `~/pidog/sounds`, and the clone keeps the pack at its root."""
    home = tmp_path / "home"
    source = tmp_path / "clone" / "sounds"
    source.mkdir(parents=True)
    (source / "single_bark_1.mp3").write_bytes(b"bark")
    (source / "angry.wav").write_bytes(b"grr")

    copied = installer.install_vendor_sounds(source, home=home)

    target = home / "pidog" / "sounds"
    assert copied == 2
    assert sorted(item.name for item in target.iterdir()) == ["angry.wav", "single_bark_1.mp3"]
    assert installer.vendor_sounds_present(home) is True


def test_a_second_run_copies_nothing_and_keeps_what_is_there(tmp_path) -> None:
    """The target is on the dog's filesystem, so it is user data: never overwritten."""
    home = tmp_path / "home"
    source = tmp_path / "clone" / "sounds"
    source.mkdir(parents=True)
    (source / "single_bark_1.mp3").write_bytes(b"bark")
    installer.install_vendor_sounds(source, home=home)

    edited = home / "pidog" / "sounds" / "single_bark_1.mp3"
    edited.write_bytes(b"mine")

    assert installer.install_vendor_sounds(source, home=home) == 0
    assert edited.read_bytes() == b"mine"


def test_a_missing_pack_is_reported_and_is_not_a_failure(tmp_path, capsys) -> None:
    copied = installer.install_vendor_sounds(tmp_path / "absent", home=tmp_path / "home")

    assert copied == 0
    assert "Sound pack not found" in capsys.readouterr().out
    assert installer.vendor_sounds_present(tmp_path / "home") is False


def test_an_empty_or_absent_sounds_dir_is_not_a_pack(tmp_path) -> None:
    (tmp_path / "pidog" / "sounds").mkdir(parents=True)

    assert installer.vendor_sounds_present(tmp_path) is False
    assert installer.vendor_sounds_present(tmp_path / "never-created") is False


def test_the_gap_report_names_the_missing_pack_and_the_documented_setters(tmp_path, capsys) -> None:
    """#256 + #259: both vendor data directories are absent, and both have a replacement."""
    installer.report_pidog_data_gaps(home=tmp_path)

    out = capsys.readouterr().out
    assert "sound pack missing" in out
    assert "PIDOG-SENSORS.md" in out


def test_the_gap_report_names_the_tool_only_when_the_checkout_has_it(tmp_path, capsys) -> None:
    """A command that is not in the tree is worse than a pointer; `main` had neither at the time."""
    (tmp_path / "src" / "tools").mkdir(parents=True)
    (tmp_path / "src" / "tools" / "imu_calibrate.py").write_text("", encoding="utf-8")

    installer.report_pidog_data_gaps(home=tmp_path / "home", repo_root=tmp_path)

    out = capsys.readouterr().out
    assert "tools.imu_calibrate" in out
    assert "PIDOG-SENSORS.md" not in out


def test_the_gap_report_stays_quiet_about_sounds_once_the_pack_is_there(tmp_path, capsys) -> None:
    target = tmp_path / "pidog" / "sounds"
    target.mkdir(parents=True)
    (target / "single_bark_1.mp3").write_bytes(b"bark")

    installer.report_pidog_data_gaps(home=tmp_path)

    assert "sound pack missing" not in capsys.readouterr().out


def test_rtabmap_bindings_source_needs_an_installable_python_dir(tmp_path) -> None:
    """#181: a `python/` directory without `setup.py` is not something pip can install."""
    assert installer.rtabmap_bindings_source(tmp_path) is None

    (tmp_path / "python").mkdir()
    assert installer.rtabmap_bindings_source(tmp_path) is None

    (tmp_path / "python" / "setup.py").write_text("", encoding="utf-8")
    assert installer.rtabmap_bindings_source(tmp_path) == tmp_path / "python"
