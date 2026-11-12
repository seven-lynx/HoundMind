"""The runtime must be able to import and construct itself on a machine with no hardware.

`python -m houndmind_ai` used to die with ModuleNotFoundError before it read a config, because
a module-scope `import cv2` deep in the vision path was pulled in eagerly. CI never caught it
because CI installs OpenCV; the installer's lite fallback does not.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path

import pytest

from houndmind_ai.core.config import load_config
from houndmind_ai.optional.face_recognition import FaceRecognitionModule


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


def test_exactly_one_module_owns_the_servo_bus() -> None:
    from houndmind_ai.kernel.registry import Capability
    from houndmind_ai.main import build_registry

    registry = build_registry(load_config())
    assert registry.provider(Capability.MOTION) is not None
    assert registry.provider(Capability.SENSORS) is not None


def test_the_gateway_runs_before_the_motors() -> None:
    """A decision made this tick has to be the one executed this tick."""
    from houndmind_ai.main import build_registry

    names = build_registry(load_config()).names()
    assert names.index("motion_gateway") < names.index("hal_motors")


def test_every_registered_module_is_ticked() -> None:
    """A module in the registry but not in the tick list would be silently dead."""
    from houndmind_ai.main import build_modules, build_registry

    config = load_config()
    assert [m.name for m in build_registry(config)] == [m.name for m in build_modules(config)]


def test_the_sensor_health_module_is_now_wired() -> None:
    """It existed as a `Module` subclass for the life of the project without ever running."""
    from houndmind_ai.main import build_modules

    names = [m.name for m in build_modules(load_config())]
    assert "sensor_health" in names


# -------------------------------------------------------------------------------------------------
# P4 PL4: identity stays off a Pi 4, and a missing wheel degrades with a reason.
# -------------------------------------------------------------------------------------------------

# Wheels that are not on PyPI, or that need a compiler. Importing one of these at module scope is
# what breaks a bare install on a workstation and what pulls dlib onto a Pi 4 (20-hardware.md).
VENDOR_MODULES = frozenset(
    {
        "pidog",
        "robot_hat",
        "vilib",
        "dlib",
        "face_recognition",
        "cv2",
        "numpy",
        "pyaudio",
        "sounddevice",
        "vosk",
        "flask",
        "pyttsx3",
        "picamera2",
        "rtabmap_py",
    }
)


class _Context(dict):
    """A context for a module that only reads settings and writes keys."""

    def set(self, key, value):
        self[key] = value


def _package_root() -> Path:
    import houndmind_ai

    return Path(houndmind_ai.__file__).parent


def _is_type_checking(test: ast.expr) -> bool:
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def _module_scope_imports(node: ast.AST):
    """Imports that would run when the module is imported.

    Walks `try`/`if`/`with` bodies, because `try: import dlib / except ImportError: pass` at module
    scope is the shape that loads dlib on a Pi and stays invisible on CI. Never descends into a
    function, a class, or an `if TYPE_CHECKING:` block, where an import costs nothing at runtime.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.If) and _is_type_checking(child.test):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            yield child
        elif isinstance(child, (ast.Try, ast.If, ast.With)):
            yield from _module_scope_imports(child)


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module.split(".")[0]]
    return []


def test_no_vendor_wheel_is_imported_at_module_scope() -> None:
    """"A Pi 4 run imports no dlib" is the exit criterion, and this is its structural half.

    `test_every_module_imports_without_a_dog_or_a_camera` cannot see this defect: a module-scope
    `try: import dlib / except ImportError: pass` passes on CI, which has no wheel, and loads dlib
    on every machine that does. This reads the syntax tree, so an absent wheel cannot mask it.
    """
    offenders = []
    root = _package_root()
    for directory in ("hal", "optional"):
        for path in sorted((root / directory).glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in _module_scope_imports(tree):
                for name in _imported_names(node):
                    if name in VENDOR_MODULES:
                        offenders.append(f"{directory}/{path.name}:{getattr(node, 'lineno', '?')} imports {name}")
    assert not offenders, "module-scope vendor imports: " + "; ".join(offenders)


def test_constructing_the_runtime_imports_no_hardware_or_identity_wheels() -> None:
    """The dynamic half: whatever the syntax says, the process must not end up with dlib loaded."""
    from houndmind_ai.main import build_modules

    before = set(sys.modules)
    build_modules(load_config())
    added = {name.split(".")[0] for name in set(sys.modules) - before}
    loaded = sorted(added & {"pidog", "robot_hat", "vilib", "dlib", "face_recognition", "cv2"})
    assert not loaded, f"constructing the runtime imported {loaded}"


def _face_module(backend: str) -> tuple[FaceRecognitionModule, _Context]:
    module = FaceRecognitionModule("face_recognition")
    context = _Context({"settings": {"face_recognition": {"enabled": True, "backend": backend}}})
    module.start(context)
    return module, context


def test_the_dlib_backend_degrades_with_a_reason() -> None:
    """Identity requested without the wheel means a disabled module with a reason, not an exception."""
    if importlib.util.find_spec("face_recognition") is not None:
        pytest.skip("the dlib wheel is installed here; the missing-dependency path cannot run")
    module, _ = _face_module("face_recognition")
    assert module.status.enabled is False
    assert "face_recognition" in (module.status.disabled_reason or "")


def test_enrolment_without_the_wheel_disables_instead_of_returning() -> None:
    """Enrolment used to `return` on ImportError: nothing enrolled and nobody told.

    `10-python.md` forbids swallowing an error and reporting success in the same tick; the failure
    mode here is a family member believing their face was saved when no file was written.
    """
    if importlib.util.find_spec("face_recognition") is not None:
        pytest.skip("the dlib wheel is installed here")
    module, context = _face_module("stub")
    assert module.status.enabled is True
    module.backend = "face_recognition"  # the heavy backend, without the wheel behind it
    context.set("vision_frame", object())
    module._handle_command({"action": "enroll", "name": "Alice"}, context, {"enabled": True})
    assert module.status.enabled is False
    assert "face_recognition" in (module.status.disabled_reason or "")


def test_faces_are_stamped_with_the_frame_time_not_the_tick() -> None:
    """Occupancy's staleness rule is only honest if `timestamp` is the frame's own time.

    `vision_pi4.py:172` publishes `vision_frame_ts` beside the frame and the detector threw it away,
    stamping `tick_ts` instead. A frozen frame republished every tick therefore looked fresh for
    ever, and `settings.perception.occupancy.min_frames` counted ticks rather than camera frames
    (P4 PL3, `72bbcd6`).
    """
    module, context = _face_module("stub")
    context.set("tick_ts", 9_999.0)
    context.set("vision_frame", object())
    context.set("vision_frame_ts", 1_234.5)
    module.tick(context)
    assert context.get("faces")["timestamp"] == 1_234.5


def test_a_frame_without_its_own_time_falls_back_to_the_tick() -> None:
    """Not every frame producer stamps `vision_frame_ts`; the tick is the worse answer, not none."""
    module, context = _face_module("stub")
    context.set("tick_ts", 9_999.0)
    context.set("vision_frame", object())
    module.tick(context)
    assert context.get("faces")["timestamp"] == 9_999.0

