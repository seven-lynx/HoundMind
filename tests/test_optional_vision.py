"""`optional/vision.py` is a frame producer, not only a viewfinder (#98).

The Pi 3 path started Vilib, published `{"status": "ready"}` and nothing else, so `vision_frame`
stayed `None` and every detector behind it — `face_recognition`, `semantic_labeler`, and the
occupancy `perception` derives from faces — was blind for the life of the run while each module
reported itself healthy. These cases hold the two halves of the repair: a frame reaches the context
with the timestamp contract `vision_pi4.py` uses, and a build that cannot produce one says so
instead of reporting `ready`.

`vilib` is not on PyPI and cannot be imported here, so a stand-in is installed in `sys.modules` —
the same shape `monkeypatch` is used for elsewhere. Nothing in this file touches a camera.
"""

from __future__ import annotations

import sys
import types

from houndmind_ai.optional.vision import VisionModule


class Vilib:
    """Only what the module touches: start, display, close, and the newest frame."""

    img: object | None = None
    started = 0
    displayed = 0
    closed = 0

    @classmethod
    def camera_start(cls, **kwargs) -> None:
        cls.started += 1

    @classmethod
    def display(cls, **kwargs) -> None:
        cls.displayed += 1

    @classmethod
    def camera_close(cls) -> None:
        cls.closed += 1


class Context:
    """The subset of `RuntimeContext` a module may use: `get` and `set`."""

    def __init__(self) -> None:
        self.data: dict = {"tick_ts": 0.0}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


def install_vilib(monkeypatch, frame: object | None = None) -> types.ModuleType:
    Vilib.img = frame
    module = types.ModuleType("vilib")
    module.Vilib = Vilib  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vilib", module)
    return module


def test_a_new_frame_is_published_with_the_timestamp_contract(monkeypatch) -> None:
    """Same two keys and same clock as `vision_pi4.py`, so no consumer can tell the paths apart."""
    first, second = object(), object()
    install_vilib(monkeypatch, first)
    module = VisionModule("vision", enabled=True)
    context = Context()

    module.start(context)
    assert context.get("vision_status") == {
        "status": "ready",
        "backend": "vilib",
        "frames": True,
    }

    module.tick(context)
    assert context.get("vision_frame") is first
    assert isinstance(context.get("vision_frame_ts"), float)
    stamp = context.get("vision_frame_ts")

    module.tick(context)
    assert context.get("vision_frame_ts") == stamp, "an unchanged frame must not look fresh"

    Vilib.img = second
    module.tick(context)
    assert context.get("vision_frame") is second
    assert context.get("vision_frame_ts") >= stamp


def test_a_build_with_no_frame_says_so_instead_of_reporting_ready(monkeypatch, caplog) -> None:
    """Silence was the defect: the reason has to reach the context a support bundle carries."""
    install_vilib(monkeypatch, None)
    monkeypatch.delattr(Vilib, "img", raising=False)
    module = VisionModule("vision", enabled=True)
    context = Context()

    module.start(context)
    assert context.get("vision_status")["frames"] is False

    with caplog.at_level("WARNING"):
        module.tick(context)
        module.tick(context)

    status = context.get("vision_status")
    assert status["frames"] is False
    assert "frame" in status["reason"]
    assert context.get("vision_frame") is None
    warnings = [r for r in caplog.records if "viewfinder" in r.getMessage()]
    assert len(warnings) == 1, "warn once, not once per tick"


def test_a_missing_vilib_disables_the_module_with_a_reason(monkeypatch) -> None:
    """A missing wheel degrades to a disabled module — never to a healthy one that does nothing."""
    monkeypatch.setitem(sys.modules, "vilib", None)
    module = VisionModule("vision", enabled=True)

    module.start(Context())

    assert module.status.enabled is False
    assert "Vision unavailable" in (module.status.disabled_reason or "")


def test_stop_closes_the_camera_it_opened(monkeypatch) -> None:
    install_vilib(monkeypatch, object())
    module = VisionModule("vision", enabled=True)
    context = Context()
    module.start(context)
    before = Vilib.closed

    module.stop(context)

    assert Vilib.closed == before + 1
