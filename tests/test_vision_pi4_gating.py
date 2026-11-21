"""`modules.vision_pi4.enabled` is the switch; the section flag is not a second one (#396).

`settings.vision_pi4.enabled` used to return silently from every tick, so a module the operator had
enabled reported `ok` in `/api/v1/modules` while publishing no frames — and the camera route answered
`503 no camera frames are being published; enable a vision module` about a module that was enabled.
The module now disables itself with the reason, which is the shape every other module uses.
"""

from __future__ import annotations

from houndmind_ai.optional.vision_pi4 import VisionPi4Module


class Context:
    """The subset of `RuntimeContext` a module may use: `get` and `set`."""

    def __init__(self, settings: dict) -> None:
        self.data: dict = {"tick_ts": 0.0, "settings": settings}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


def test_a_section_flag_that_is_off_reports_disabled_and_says_why() -> None:
    module = VisionPi4Module("vision_pi4", enabled=True)
    context = Context({"vision_pi4": {"enabled": False}})

    module.start(context)

    assert module.status.enabled is False
    assert module.status.started is False
    assert "settings.vision_pi4.enabled" in (module.status.disabled_reason or "")
    assert context.get("vision_frame") is None


def test_the_flag_turning_off_mid_run_is_reported_too() -> None:
    """A config reload that turns the flag off must not leave `ok` behind."""
    module = VisionPi4Module("vision_pi4", enabled=True)
    context = Context({"vision_pi4": {"enabled": True}})
    module.available = True

    context.data["settings"] = {"vision_pi4": {"enabled": False}}
    module.tick(context)

    assert module.status.enabled is False
    assert "settings.vision_pi4.enabled" in (module.status.disabled_reason or "")
