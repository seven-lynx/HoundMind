"""A re-run of the installer is a repair, so it must not cost the user their data (#317).

`~/.houndmind/` holds the routines, the places, the face roster and the session marker; the config
lives in the checkout and the vendor sound pack in `~/pidog/sounds`. None of that is the installer's
to rewrite, which is a claim three of these tests check and the fourth pins as behaviour.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _installer_core() -> ModuleType:
    """`scripts/installer_core.py`, loaded by path because it is not an importable package."""
    path = ROOT / "scripts" / "installer_core.py"
    spec = importlib.util.spec_from_file_location("_installer_core_user_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_inventory_finds_routines_places_and_people(tmp_path) -> None:
    data = tmp_path / ".houndmind"
    (data / "routines").mkdir(parents=True)
    (data / "routines" / "patrol.json").write_text("{}", encoding="utf-8")
    (data / "places.json").write_text("{}", encoding="utf-8")
    (data / "face").mkdir()

    inventory = _installer_core().user_data_inventory(tmp_path)

    assert inventory["routines"]["present"] is True
    assert inventory["routines"]["count"] == 1
    assert inventory["places"]["present"] is True
    assert inventory["people"]["present"] is True


def test_an_empty_home_reports_absent_rather_than_missing(tmp_path) -> None:
    inventory = _installer_core().user_data_inventory(tmp_path)

    assert all(entry["present"] is False for entry in inventory.values())


def test_the_printout_names_every_kind(tmp_path, capsys) -> None:
    data = tmp_path / ".houndmind"
    (data / "routines").mkdir(parents=True)
    (data / "routines" / "patrol.json").write_text("{}", encoding="utf-8")
    (data / "places.json").write_text("{}", encoding="utf-8")
    config = tmp_path / "settings.jsonc"
    config.write_text("{}", encoding="utf-8")

    _installer_core().print_user_data(home=tmp_path, config_path=config)

    printed = capsys.readouterr().out
    assert "routines" in printed and "places" in printed and "people" in printed
    assert "1 routine(s)" in printed
    assert "config: present" in printed


def test_the_sound_pack_copy_is_additive(tmp_path) -> None:
    """The only write the installer puts in a user's home must never overwrite a file."""
    source = tmp_path / "pack"
    source.mkdir()
    (source / "bark.wav").write_text("new bark", encoding="utf-8")
    (source / "sit.wav").write_text("new sit", encoding="utf-8")

    home = tmp_path / "home"
    target = home / "pidog" / "sounds"
    target.mkdir(parents=True)
    (target / "sit.wav").write_text("the user's own sit", encoding="utf-8")

    copied = _installer_core().install_vendor_sounds(source, home)

    assert copied == 1, "only the file that was absent"
    assert (target / "sit.wav").read_text(encoding="utf-8") == "the user's own sit"
    assert (target / "bark.wav").exists()
