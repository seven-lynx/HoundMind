"""The unit that brings the dog back after a reboot (#211).

`packaging/systemd/houndmind.service` is a template, rendered by
`scripts/installer_core.py::install_service_unit` from the account, checkout and interpreter the
installer actually used. Nothing else in the suite reads it, so a unit that lost `[Install]`, or a
placeholder the installer stopped substituting, would pass every other test and only surface as a
dog that is silent after a power cut.

Two claims are asserted here rather than in prose:

- the unit is **enabled** at install, so `multi-user.target` starts it on every boot;
- it is **not started** at install, because an install is not the moment to open the servo bus.
"""

from __future__ import annotations

import configparser
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "packaging" / "systemd" / "houndmind.service"
# The three values only the installer knows; a fourth would ship unsubstituted.
PLACEHOLDERS = ("@HOUNDMIND_USER@", "@HOUNDMIND_ROOT@", "@HOUNDMIND_PYTHON@")
INSTALLED_AT = "/etc/systemd/system/houndmind.service"


def _installer():
    """`scripts/` is not a package, so the module is loaded by path (`test_installer_preflight`)."""
    spec = importlib.util.spec_from_file_location(
        "installer_core_systemd_under_test", ROOT / "scripts" / "installer_core.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = _installer()


def _unit() -> configparser.ConfigParser:
    # `ConfigParser` lowercases option names, so `WantedBy` reads back as `wantedby`.
    parser = configparser.ConfigParser()
    parser.read_string(UNIT.read_text(encoding="utf-8"))
    return parser


def test_the_unit_is_wanted_by_multi_user_target() -> None:
    """Without this line `systemctl enable` succeeds and nothing starts at boot."""
    assert _unit()["Install"]["wantedby"] == "multi-user.target"


def test_the_unit_runs_the_package_with_the_installer_python() -> None:
    """`python -m houndmind_ai.main` is the entry point; a stray script would skip the runtime."""
    exec_start = _unit()["Service"]["execstart"]
    assert exec_start.startswith("@HOUNDMIND_PYTHON@ ")
    assert exec_start.endswith("-m houndmind_ai.main")


def test_the_unit_supervises_and_stops_gracefully() -> None:
    """`Sensor` fields the runtime depends on: restart on failure, SIGTERM, room to close the HAL."""
    service = _unit()["Service"]
    assert service["type"] == "simple"
    assert service["restart"] == "on-failure"
    assert service["restartsec"] == "5"
    assert service["killsignal"] == "SIGTERM"
    # Longer than the runtime's own 5 s module-stop budget, so systemd never reaches for SIGKILL first.
    assert int(service["timeoutstopsec"]) > 5


def test_a_broken_config_stops_instead_of_looping() -> None:
    """A load-time config error is a person's problem; 400 restarts a minute only hides the message."""
    unit = _unit()["Unit"]
    assert unit["startlimitintervalsec"] == "60"
    assert unit["startlimitburst"] == "3"


def test_the_template_carries_exactly_the_installer_placeholders() -> None:
    """A fourth placeholder would ship unsubstituted: the installer only knows these three."""
    text = UNIT.read_text(encoding="utf-8")
    # The header comment also says `@HOUNDMIND_*@`, which is prose, not a placeholder - hence the
    # `+` rather than `*`: a token with no name inside it is not something the installer handles.
    found = set(re.findall(r"@HOUNDMIND_[A-Z_]+@", text))
    assert found == set(PLACEHOLDERS)
    for placeholder in PLACEHOLDERS:
        # Once where the header documents it, once where the setting uses it.
        assert text.count(placeholder) == 2, f"{placeholder} is not used exactly once"


def test_the_installer_renders_the_unit_and_enables_it_without_starting_it(
    monkeypatch, tmp_path: Path
) -> None:
    """The rendered copy is what systemd reads; `enable` is the boot contract, `start` is not ours."""
    monkeypatch.setattr(installer.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(installer.getpass, "getuser", lambda: "pi")

    commands: list[list[str]] = []
    rendered: dict[str, str] = {}

    def fake_run(command: list[str]) -> int:
        commands.append(list(command))
        if command[:2] == ["sudo", "install"]:
            # Read the staged file while it exists: `install_service_unit` unlinks it afterwards.
            rendered["text"] = Path(command[4]).read_text(encoding="utf-8")
            rendered["destination"] = command[5]
        return 0

    monkeypatch.setattr(installer, "run", fake_run)
    python = tmp_path / "HoundMind" / ".venv" / "bin" / "python"

    assert installer.install_service_unit(ROOT, python) == 0

    text = rendered["text"]
    assert rendered["destination"] == INSTALLED_AT
    for placeholder in PLACEHOLDERS:
        assert placeholder not in text, f"{placeholder} survived rendering"
    assert "User=pi" in text
    assert f"WorkingDirectory={ROOT}" in text
    assert f"ExecStart={python} -m houndmind_ai.main" in text

    assert ["sudo", "systemctl", "daemon-reload"] in commands
    assert ["sudo", "systemctl", "enable", "houndmind.service"] in commands
    # `enable`, never `enable --now`: the operator decides when the dog comes back on its own.
    assert not any("start" in argument for command in commands for argument in command), (
        "installing must not start the runtime"
    )
