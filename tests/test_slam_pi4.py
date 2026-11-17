import time

from houndmind_ai.optional.slam_pi4 import SlamPi4Module
from houndmind_ai.core.runtime import RuntimeContext


def test_slam_stub_updates_pose():
    ctx = RuntimeContext()
    settings = {"slam_pi4": {"enabled": True, "backend": "stub", "gyro_scale": 0.5}}
    ctx.set("settings", settings)

    # initial sensor reading with a small z-gyro
    gyro = [0.0, 0.0, 1.0]
    ctx.set("sensor_reading", {"gyro": gyro, "acc": None, "timestamp": time.time()})

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    m.tick(ctx)

    pose = ctx.get("slam_pose")
    assert isinstance(pose, dict)
    # yaw should change from zero due to gyro integration
    assert abs(pose.get("yaw", 0.0)) > 0.0


def test_rtabmap_fallback_to_stub_when_unavailable():
    ctx = RuntimeContext()
    settings = {"slam_pi4": {"enabled": True, "backend": "rtabmap"}}
    ctx.set("settings", settings)

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    status = ctx.get("slam_status")
    # if RTAB-Map bindings are not present, module should report stub backend
    assert isinstance(status, dict)
    assert status.get("backend") in ("stub", "rtabmap")


def test_a_rtabmap_module_without_the_class_is_not_a_backend(monkeypatch, caplog):
    import sys
    import types

    fake = types.ModuleType("rtabmap")
    # A partial bindings build: helper classes, no Rtabmap.
    fake.PyMatcher = object
    monkeypatch.setitem(sys.modules, "rtabmap", fake)

    ctx = RuntimeContext()
    ctx.set("settings", {"slam_pi4": {"enabled": True, "backend": "rtabmap"}})

    m = SlamPi4Module("slam", enabled=True)
    with caplog.at_level("WARNING"):
        m.start(ctx)

    # The status line is what a consumer decides on, so it must not say rtabmap.
    assert ctx.get("slam_status") == {"status": "ready", "backend": "stub"}
    assert m._rtabmap_failed is True
    assert "no Rtabmap class" in caplog.text


def test_a_rtabmap_class_that_refuses_to_start_is_not_a_backend(monkeypatch, caplog):
    import sys
    import types

    fake = types.ModuleType("rtabmap")

    class Rtabmap:
        def __init__(self) -> None:
            raise RuntimeError("no database support")

    fake.Rtabmap = Rtabmap
    monkeypatch.setitem(sys.modules, "rtabmap", fake)

    ctx = RuntimeContext()
    ctx.set("settings", {"slam_pi4": {"enabled": True, "backend": "rtabmap"}})

    m = SlamPi4Module("slam", enabled=True)
    with caplog.at_level("WARNING"):
        m.start(ctx)

    assert ctx.get("slam_status") == {"status": "ready", "backend": "stub"}
    assert "could not start" in caplog.text


def test_usable_bindings_are_reported_as_the_rtabmap_backend(monkeypatch) -> None:
    import sys
    import types

    fake = types.ModuleType("rtabmap")

    class Rtabmap:
        def __init__(self) -> None:
            self.params = None

        def set_parameters(self, params: dict) -> None:
            self.params = params

    fake.Rtabmap = Rtabmap
    monkeypatch.setitem(sys.modules, "rtabmap", fake)

    ctx = RuntimeContext()
    ctx.set(
        "settings",
        {
            "slam_pi4": {
                "enabled": True,
                "backend": "rtabmap",
                "rtabmap": {"params": {"RGB/Enabled": "true"}},
            }
        },
    )

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)

    assert ctx.get("slam_status") == {"status": "ready", "backend": "rtabmap"}
    assert m.available is True
    assert m._adapter is not None
    assert m._adapter._rtab.params == {"RGB/Enabled": "true"}

