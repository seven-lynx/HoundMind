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


def test_the_module_counts_what_it_did_with_the_frames(monkeypatch) -> None:
    """A replay quotes processed-versus-lost, so the module has to count both (plan S)."""
    import sys
    import types

    fake = types.ModuleType("rtabmap")

    class Rtabmap:
        def __init__(self) -> None:
            self.frames = 0

        def process(self, frame, imu=None, timestamp=None) -> None:
            self.frames += 1

        def get_pose(self):
            return None

    fake.Rtabmap = Rtabmap
    monkeypatch.setitem(sys.modules, "rtabmap", fake)

    ctx = RuntimeContext()
    ctx.set(
        "settings",
        {"slam_pi4": {"enabled": True, "backend": "rtabmap", "interval_s": 0.0}},
    )
    ctx.set("vision_frame", b"frame")
    ctx.set("sensor_reading", {"gyro": [0.0, 0.0, 0.0], "acc": [0.0, 0.0, 9.81], "timestamp": time.time()})

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    m.tick(ctx)

    stats = ctx.get("slam_stats")
    assert stats == {
        "frames_in": 1,
        "frames_skipped": 0,
        "frames_processed": 1,
        "frames_dropped": 0,
        "frames_failed": 0,
        "buffered": 0,
    }


def test_the_stub_counts_frames_it_never_processed() -> None:
    ctx = RuntimeContext()
    ctx.set("settings", {"slam_pi4": {"enabled": True, "backend": "stub", "interval_s": 0.0}})
    ctx.set("vision_frame", b"frame")
    ctx.set("sensor_reading", {"gyro": [0.0, 0.0, 0.0], "acc": None, "timestamp": time.time()})

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    m.tick(ctx)

    stats = ctx.get("slam_stats")
    # Dead reckoning does not consume frames; saying so is the honest report.
    assert stats["frames_in"] == 1
    assert stats["frames_processed"] == 0
    assert stats["buffered"] == 1


def test_a_frame_the_producer_has_not_replaced_is_buffered_once() -> None:
    """The loop re-reads `vision_frame` until the producer replaces it; a copy is not new work (#366)."""
    ctx = RuntimeContext()
    ctx.set("settings", {"slam_pi4": {"enabled": True, "backend": "stub", "interval_s": 0.0}})
    ctx.set("vision_frame", b"frame-1")
    ctx.set("vision_frame_ts", 100.0)
    ctx.set("sensor_reading", {"gyro": [0.0, 0.0, 0.0], "acc": None, "timestamp": time.time()})

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    for _ in range(6):
        m.tick(ctx)

    stats = ctx.get("slam_stats")
    assert stats["frames_in"] == 1
    assert stats["frames_skipped"] == 5
    assert stats["buffered"] == 1


def test_a_new_frame_and_stamp_is_buffered_as_new_work() -> None:
    ctx = RuntimeContext()
    ctx.set("settings", {"slam_pi4": {"enabled": True, "backend": "stub", "interval_s": 0.0}})
    ctx.set("sensor_reading", {"gyro": [0.0, 0.0, 0.0], "acc": None, "timestamp": time.time()})

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    ctx.set("vision_frame", b"frame-1")
    ctx.set("vision_frame_ts", 1.0)
    m.tick(ctx)
    ctx.set("vision_frame", b"frame-2")
    ctx.set("vision_frame_ts", 2.0)
    m.tick(ctx)

    stats = ctx.get("slam_stats")
    assert stats["frames_in"] == 2
    assert stats["frames_skipped"] == 0
    assert stats["buffered"] == 2


def test_a_producer_without_a_stamp_is_deduped_by_identity() -> None:
    """A publisher that sets no `vision_frame_ts` still must not hand the backend the same array twice."""
    ctx = RuntimeContext()
    ctx.set("settings", {"slam_pi4": {"enabled": True, "backend": "stub", "interval_s": 0.0}})
    ctx.set("sensor_reading", {"gyro": [0.0, 0.0, 0.0], "acc": None, "timestamp": time.time()})

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    ctx.set("vision_frame", b"frame-1")
    m.tick(ctx)
    m.tick(ctx)

    stats = ctx.get("slam_stats")
    assert stats["frames_in"] == 1
    assert stats["frames_skipped"] == 1


def test_a_tick_with_no_published_frame_buffers_nothing() -> None:
    """`imu` is built as a dict every tick, so the old `or imu is not None` guard appended a `None`
    frame even with no camera at all (#366)."""
    ctx = RuntimeContext()
    ctx.set("settings", {"slam_pi4": {"enabled": True, "backend": "stub", "interval_s": 0.0}})

    m = SlamPi4Module("slam", enabled=True)
    m.start(ctx)
    for _ in range(3):
        m.tick(ctx)

    stats = ctx.get("slam_stats")
    assert stats["frames_in"] == 0
    assert stats["frames_skipped"] == 3
    assert stats["buffered"] == 0
    assert not m._buffer


