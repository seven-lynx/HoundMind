"""The dummy inference thread is gone; the scheduler is a tool with no model (M-03, #9).

`vision_pi4` used to start a background thread on every install that enabled the camera: it slept
50 ms and returned `{"result": "ok"}`. These tests pin the replacement — no model, no thread — and
keep the scheduler itself, which is the piece a real model will use.
"""

from __future__ import annotations

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.optional.vision_pi4 import VisionPi4Module


def context(**vision):
    ctx = RuntimeContext()
    settings = {
        "enabled": True,
        "backend": "opencv",
        "device_index": 0,
        "frame_interval_s": 0.2,
        "inference_scheduler_enabled": False,
        "preprocessing": {},
    }
    settings.update(vision)
    ctx.set("settings", {"vision_pi4": settings})
    return ctx


def test_the_shipped_default_is_off() -> None:
    from houndmind_ai.core.config import load_config

    shipped = load_config().settings["vision_pi4"]
    assert shipped["inference_scheduler_enabled"] is False


def test_off_by_default_starts_no_thread() -> None:
    ctx = context()
    module = VisionPi4Module("vision_pi4")
    module.start(ctx)
    try:
        assert module._inference_scheduler is None
        assert ctx.get("vision_inference_status")["state"] == "disabled"
    finally:
        module.stop(ctx)


def test_enabling_it_with_no_model_says_so() -> None:
    """The old behaviour was to invent a result. Reporting is the honest version."""
    ctx = context(inference_scheduler_enabled=True)
    module = VisionPi4Module("vision_pi4")
    module.start(ctx)
    try:
        assert module._inference_scheduler is None
        status = ctx.get("vision_inference_status")
        assert status["state"] == "unconfigured"
        assert "no model" in status["detail"]
    finally:
        module.stop(ctx)


def test_a_wired_model_still_uses_the_scheduler() -> None:
    """The scheduler and preprocessor are kept: they are what a real model will plug into."""
    ctx = context(inference_scheduler_enabled=True)
    seen: list[str] = []
    module = VisionPi4Module("vision_pi4", inference_fn=lambda frame: seen.append(frame) or "ok")
    module._cv2 = _FakeCV2()
    module.start(ctx)
    try:
        assert module._inference_scheduler is not None
        assert ctx.get("vision_inference_status")["state"] == "ready"
    finally:
        module.stop(ctx)


class _FakeCapture:
    def isOpened(self) -> bool:
        return True

    def read(self):
        return False, None

    def release(self) -> None:
        return None


class _FakeCV2:
    def VideoCapture(self, index: int) -> _FakeCapture:
        return _FakeCapture()

    def imencode(self, *args, **kwargs):
        return True, b"jpeg"