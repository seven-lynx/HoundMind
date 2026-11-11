"""The runtime must be able to import and construct itself on a machine with no hardware.

`python -m houndmind_ai` used to die with ModuleNotFoundError before it read a config, because
a module-scope `import cv2` deep in the vision path was pulled in eagerly. CI never caught it
because CI installs OpenCV; the installer's lite fallback does not.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

from houndmind_ai.core.config import load_config


def _all_module_names() -> list[str]:
    import houndmind_ai

    names = []
    for info in pkgutil.walk_packages(houndmind_ai.__path__, "houndmind_ai."):
        names.append(info.name)
    return sorted(names)


def test_every_module_imports_without_a_dog_or_a_camera() -> None:
    """Import time must not require pidog, cv2, numpy, flask or a model on disk."""
    failures = {}
    for name in _all_module_names():
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            failures[name] = f"{type(exc).__name__}: {exc}"
    assert not failures, f"modules failed to import: {failures}"


def test_build_modules_constructs_every_entry() -> None:
    """`main.build_modules` passes config sections as kwargs; a signature mismatch here
    would take down the whole runtime at startup."""
    from houndmind_ai.main import build_modules

    modules = build_modules(load_config())
    assert modules
    names = [module.name for module in modules]
    assert len(names) == len(set(names)), "module names must be unique"


def test_module_names_are_unique_across_the_registry() -> None:
    from houndmind_ai.main import build_modules

    names = [m.name for m in build_modules(load_config())]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates


@pytest.mark.parametrize("required", [True])
def test_no_optional_module_is_marked_required(required: bool) -> None:
    """Only HAL belongs in `required`: a vision failure must not stop the dog."""
    from houndmind_ai.main import build_modules

    hal = {"hal_sensors", "hal_motors"}
    for module in build_modules(load_config()):
        if module.status.required:
            assert module.name in hal, f"{module.name} is required but is not HAL"