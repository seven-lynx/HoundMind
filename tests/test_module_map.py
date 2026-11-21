"""`docs/MODULES.md` lists exactly the modules `main.build_registry` registers (#411).

The page is a reference for "which module owns this context key", so drift is the failure: a module
added without a row reads as one that does not exist to the next person debugging a key, and a row
for a module that was removed sends them to a file that is gone. The name set is cheap to pin; the
keys are prose the module's own tests and the docs review keep honest.
"""

from __future__ import annotations

from pathlib import Path

from houndmind_ai.core.config import load_config
from houndmind_ai.main import build_modules

DOC = Path(__file__).resolve().parents[1] / "docs" / "MODULES.md"


def documented() -> set[str]:
    """The first cell of every table row that names a module in backticks."""
    names: set[str] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cell = line.split("|")[1].strip()
        if cell.startswith("`") and cell.endswith("`"):
            names.add(cell.strip("`"))
    return names


def test_every_registered_module_has_a_row() -> None:
    registered = {module.name for module in build_modules(load_config())}

    missing = registered - documented()
    assert missing == set(), f"registered but not in docs/MODULES.md: {sorted(missing)}"


def test_no_row_names_a_module_that_is_not_registered() -> None:
    registered = {module.name for module in build_modules(load_config())}

    stale = documented() - registered
    assert stale == set(), f"in docs/MODULES.md but not registered: {sorted(stale)}"
