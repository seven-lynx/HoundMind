"""The legacy HTTP servers stay deleted.

Four modules used to open their own `ThreadingHTTPServer` — face recognition on 8098/8088, the
vision feed on 8090, voice control on 8091 and the telemetry dashboard on 8092. Three of them
answered without any token at all, and one of those was a motion path: `GET /command?action=` on
8091 set `behavior_override` and moved the dog without passing the interlock, the deadman or the
audit log. The control plane (`services/api.py`, port 8420) is the only listener now.

This test is the reason a future module cannot quietly add a fifth one. It is cheaper than
re-auditing four files, and it fails at review time rather than on a user's LAN.
"""

from __future__ import annotations

import ast
from pathlib import Path

import json5

from houndmind_ai.core.config import default_config_path
from houndmind_ai.kernel.config_schema import validate_config_tree

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "houndmind_ai"


def paths(problems) -> list[str]:
    return [problem.path for problem in problems]


def _source_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_no_module_imports_the_stdlib_http_server() -> None:
    """A `Module` that serves HTTP is a second control plane with no auth and no audit."""
    forbidden = ("http.server", "socketserver", "SimpleHTTPServer", "CGIHTTPServer")
    offenders: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                root = node.module or ""
                if root.startswith(forbidden):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} → {root}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno} → {alias.name}"
                        )
    assert offenders == [], f"stdlib HTTP servers are back: {offenders}"


def test_the_shipped_config_has_no_per_module_http_block() -> None:
    raw = json5.loads(default_config_path().read_text(encoding="utf-8"))
    settings = raw["settings"]
    carrying = [name for name, section in settings.items() if isinstance(section, dict) and "http" in section]
    assert carrying == [], f"these sections still carry an `http` block: {carrying}"
    assert "telemetry_dashboard" not in settings
    assert "telemetry_dashboard" not in raw["modules"]


def test_an_old_config_with_an_http_block_is_refused_with_a_hint() -> None:
    """The removal is only safe if it is loud: a leftover block must not load and be ignored."""
    problems = validate_config_tree({"settings": {"vision_pi4": {"http": {}}}})
    assert paths(problems) == ["config.settings.vision_pi4.http"], problems


def test_a_leftover_telemetry_section_is_refused() -> None:
    """The section is gone, so an existing file must fail at load rather than quietly keep it."""
    problems = validate_config_tree({"settings": {"telemetry_dashboard": {}}})
    assert paths(problems) == ["config.settings.telemetry_dashboard"], problems