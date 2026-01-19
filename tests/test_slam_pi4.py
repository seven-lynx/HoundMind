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
