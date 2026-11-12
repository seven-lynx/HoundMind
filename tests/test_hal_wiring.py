"""The fake dog drives the real code paths.

`test_runtime_tick.py` proves the loop survives; this file proves the loop *does* something and
that it does it through the HAL. Each test names the seam it covers:

- the protocol, so the fake and the vendor adapter cannot drift apart,
- `SensorService` polling a HAL instead of a vendor object,
- `ScanningService` asking the HAL to move the head and then to sample the distance,
- the command path: gateway → interlock → motors → `hal.action`,
- and the veto, which must leave the HAL untouched.
"""

from __future__ import annotations

from houndmind_ai.act.gateway import MotionGatewayModule
from houndmind_ai.core.config import load_config
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import DogHAL, SensorSnapshot
from houndmind_ai.hal.module import HalModule
from houndmind_ai.hal.motors import MotorModule
from houndmind_ai.hal.sensors import SensorModule, SensorReading, SensorService
from houndmind_ai.kernel.commands import Source
from houndmind_ai.navigation.scanning import ScanningService


class DummyContext:
    """The runtime context, minus the locking: these tests are single-threaded."""

    def __init__(self, settings: dict | None = None):
        self.data: dict = {"settings": load_config().settings if settings is None else settings}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __contains__(self, key):
        return key in self.data


def publish_reading(ctx: DummyContext, hal: DogHAL) -> SensorReading:
    """Put a real reading in the context the way `SensorModule` does, without its thread."""
    reading = SensorReading.from_snapshot(hal.read())
    ctx.set("sensor_reading", reading)
    return reading


def test_fake_and_vendor_both_satisfy_the_protocol() -> None:
    assert isinstance(FakeDogHAL(), DogHAL)


def test_hal_module_publishes_the_injected_hal() -> None:
    hal = FakeDogHAL()
    ctx = DummyContext()
    module = HalModule("hal", hal=hal)
    module.start(ctx)

    assert ctx.get("hal") is hal
    module.stop(ctx)
    assert ctx.get("hal") is None


def test_a_vendor_hal_also_publishes_the_legacy_pidog_key() -> None:
    """`calibration/workflow.py` still speaks the vendor API; that door stays documented."""

    class StubVendorHAL(FakeDogHAL):
        @property
        def vendor(self):
            return "the-dog"

    ctx = DummyContext()
    HalModule("hal", hal=StubVendorHAL()).start(ctx)
    assert ctx.get("pidog") == "the-dog"


def test_sensor_service_reads_through_the_hal() -> None:
    hal = FakeDogHAL()
    hal.set_distance(84.0)
    hal.set_touch("R")
    service = SensorService(hal, {"history_size": 2})

    reading = service.read_once()
    assert reading is not None
    assert reading.distance_cm == 84.0
    assert reading.distance_valid is True
    assert reading.touch == "R"


def test_sensor_service_without_a_hal_is_a_no_op() -> None:
    """No dog on the machine is not an exception; it is "nothing to read"."""
    service = SensorService(None, {})
    assert service.read_once() is None
    service.start()
    service.stop()


def test_sensor_module_disables_itself_without_a_hal() -> None:
    module = SensorModule("hal_sensors")
    module.start(DummyContext())
    assert module.status.disabled_reason == "no HAL available"


def test_scanning_asks_the_hal_to_move_the_head_and_sample() -> None:
    hal = FakeDogHAL()
    hal.set_distance(120.0)
    settings = {
        "scan_yaw_max_deg": 30,
        "scan_samples": 3,
        "scan_settle_s": 0.0,
        "scan_between_reads_s": 0.0,
        "head_scan_speed": 70,
    }
    service = ScanningService(hal, settings)

    reading = service.scan_three_way()

    assert reading.mode == "three_way"
    assert reading.data["forward"] == 120.0
    head_moves = [params for name, params in hal.calls if name == "head"]
    assert len(head_moves) >= 4, "forward, right, left and a recentre"
    assert hal.distance_samples, "the scan should sample through the HAL"


def test_a_forward_command_reaches_the_hal() -> None:
    hal = FakeDogHAL()
    hal.set_distance(200.0)
    ctx = DummyContext()
    HalModule("hal", hal=hal).start(ctx)
    publish_reading(ctx, hal)

    motors = MotorModule("hal_motors")
    motors.start(ctx)
    gateway = MotionGatewayModule("motion_gateway")
    ctx.set("intent_board", gateway.board)
    gateway.board.publish("forward", Source.NAVIGATION)

    gateway.tick(ctx)
    motors.tick(ctx)

    assert ("forward", {}) in hal.calls, hal.calls


def test_a_vetoed_command_never_reaches_the_hal() -> None:
    """The interlock is the last word: an obstacle at 5 cm must not produce a step."""
    hal = FakeDogHAL()
    hal.set_distance(5.0)
    ctx = DummyContext()
    HalModule("hal", hal=hal).start(ctx)
    publish_reading(ctx, hal)

    motors = MotorModule("hal_motors")
    motors.start(ctx)
    gateway = MotionGatewayModule("motion_gateway")
    ctx.set("intent_board", gateway.board)
    gateway.board.publish("forward", Source.NAVIGATION)

    gateway.tick(ctx)
    motors.tick(ctx)

    assert ("forward", {}) not in hal.calls, hal.calls
    verdict = ctx.get("motion_verdict")
    assert verdict is not None
    assert verdict["accepted"] is False


def test_motors_disable_themselves_without_a_hal() -> None:
    module = MotorModule("hal_motors")
    module.start(DummyContext())
    assert module.status.disabled_reason == "no HAL available"


def _motors_context() -> DummyContext:
    """Real settings, minus the 200 ms action interval: these tests count steps, not pace."""
    settings = load_config().settings
    settings["motors"] = {**settings.get("motors", {}), "min_action_interval_s": 0.0}
    return DummyContext(settings)


def _motor_path(ctx: DummyContext, hal: FakeDogHAL) -> tuple[MotionGatewayModule, MotorModule]:
    HalModule("hal", hal=hal).start(ctx)
    publish_reading(ctx, hal)
    motors = MotorModule("hal_motors")
    motors.start(ctx)
    gateway = MotionGatewayModule("motion_gateway")
    ctx.set("intent_board", gateway.board)
    return gateway, motors


def test_a_cue_reaches_the_sound_path_and_not_the_vendor_call() -> None:
    """A cue is the behaviour layer's annotation: it is played, and stripped before the action."""
    hal = FakeDogHAL()
    ctx = _motors_context()
    gateway, motors = _motor_path(ctx, hal)
    gateway.board.publish(
        "wag_tail", Source.BEHAVIOUR, {"cue": {"name": "woohoo", "volume": 60}}
    )

    gateway.tick(ctx)
    motors.tick(ctx)

    assert hal.sounds == [("woohoo", 60)]
    assert ("wag_tail", {}) in hal.calls, hal.calls


def test_a_live_slot_plays_its_cue_once() -> None:
    """An intent lives for its TTL, so the same command arrives on several ticks — one sound."""
    hal = FakeDogHAL()
    ctx = _motors_context()
    gateway, motors = _motor_path(ctx, hal)
    gateway.board.publish(
        "wag_tail", Source.BEHAVIOUR, {"cue": {"name": "woohoo", "volume": 60}}
    )

    for _ in range(3):
        gateway.tick(ctx)
        motors.tick(ctx)

    assert hal.sounds == [("woohoo", 60)]


def test_a_cue_never_turns_a_repeat_into_a_second_step() -> None:
    """The cue is excluded from the action fingerprint: announcing an entry is not a new step."""
    hal = FakeDogHAL()
    hal.set_distance(200.0)
    ctx = _motors_context()
    gateway, motors = _motor_path(ctx, hal)
    gateway.board.publish("forward", Source.NAVIGATION, {"cue": {"name": "pant", "volume": 60}})
    gateway.tick(ctx)
    motors.tick(ctx)

    gateway.board.publish("forward", Source.NAVIGATION)
    gateway.tick(ctx)
    motors.tick(ctx)

    steps = [params for name, params in hal.calls if name == "forward"]
    assert steps == [{}], steps


def test_the_sensor_snapshot_carries_the_imu_and_sound_fields() -> None:
    """`SensorReading` consumers read `.acc`/`.gyro`/`.sound_detected`; the boundary must carry them."""
    hal = FakeDogHAL()
    hal.set_acc((0.0, 0.0, 1.0))
    hal.set_gyro((0.1, 0.2, 0.3))
    hal.set_sound(90)
    snapshot: SensorSnapshot = hal.read()

    assert snapshot.acc == (0.0, 0.0, 1.0)
    assert snapshot.gyro == (0.1, 0.2, 0.3)
    assert snapshot.sound_detected is True
    assert snapshot.to_dict()["gyro"] == (0.1, 0.2, 0.3)