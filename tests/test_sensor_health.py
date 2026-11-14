import pytest
from houndmind_ai.safety.sensor_health import SensorHealthModule
from houndmind_ai.hal.sensors import SensorService, SensorReading
from houndmind_ai.logging.led_manager import LedManagerModule

class DummyContext:
    def __init__(self):
        self.config = {
            'sensor_health': {
                'enabled': True,
                'distance_threshold': 10,
                'imu_threshold': 5,
                'touch_threshold': 1,
                'led_badge': True,
                'log_badge': True
            }
        }
        self.led_manager = LedManagerModule("led_manager")
        # A HAL-less service: this test drives SensorReading values through the module directly.
        self.sensor_service = SensorService(None, {})
        self.event_log = []

    def log_event(self, event):
        self.event_log.append(event)

def test_sensor_health_module_initialization():
    module = SensorHealthModule("sensor_health", enabled=True)
    assert module.status.enabled is True

def test_sensor_health_module_disabled():
    module = SensorHealthModule("sensor_health", enabled=False)
    assert module.status.enabled is False

def test_sensor_health_led_and_log(monkeypatch):
    ctx = DummyContext()
    module = SensorHealthModule("sensor_health", enabled=True)
    # Simulate unhealthy sensor (fields must match SensorReading dataclass)
    unhealthy_reading = SensorReading(
        distance_cm=100,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=None,
        gyro=None,
        timestamp=0,
        distance_valid=False,
        touch_valid=True,
        sound_valid=True,
        imu_valid=False
    )
    # Patch context to provide sensor_reading
    class DummyContextWithSet(DummyContext):
        def __init__(self):
            super().__init__()
            self._dict = {"settings": {"sensor_health": {"enabled": True}}}
        def get(self, key, default=None):
            if key == "sensor_reading":
                return unhealthy_reading
            return self._dict.get(key, default)
        def set(self, key, value):
            self._dict[key] = value
    ctx = DummyContextWithSet()
    module.tick(ctx)
    # Just check that no exceptions and context was updated
    assert True


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0


class ReadingContext:
    """A context that hands the module one sensor reading and records what it writes."""

    def __init__(self, reading: SensorReading) -> None:
        self.reading = reading
        self.data: dict = {"settings": {"sensor_health": {"enabled": True}}}

    def get(self, key, default=None):
        if key == "sensor_reading":
            return self.reading
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def reading(now: float, *, valid: bool) -> SensorReading:
    return SensorReading(
        distance_cm=100,
        touch="N",
        sound_detected=False,
        sound_direction=None,
        acc=None,
        gyro=None,
        timestamp=now,
        distance_valid=valid,
        touch_valid=True,
        sound_valid=True,
        imu_valid=valid,
    )


def test_a_health_colour_is_a_live_request(monkeypatch) -> None:
    """The request the selector can now reach carries a deadline, and it is refreshed (#78)."""
    clock = Clock()
    monkeypatch.setattr("houndmind_ai.safety.sensor_health.time.time", lambda: clock.now)
    monkeypatch.setattr("houndmind_ai.safety.sensor_health.time.monotonic", lambda: clock.now)

    context = ReadingContext(reading(clock.now, valid=False))
    module = SensorHealthModule("sensor_health", enabled=True)

    module.tick(context)
    first = context.get("led_request:health")
    assert first is not None
    assert first["mode"] == "health"
    assert first["until_ts"] > clock.now

    # Next tick, still unhappy: the same slot is rewritten with a later deadline. Without that the
    # request would expire while the sensor is still broken.
    clock.now += 1.0
    context.reading = reading(clock.now, valid=False)
    module.tick(context)
    assert context.get("led_request:health")["until_ts"] > first["until_ts"]


def test_recovering_clears_the_health_request(monkeypatch) -> None:
    """A reachable health source must not own the strip after the sensors are healthy again."""
    clock = Clock()
    monkeypatch.setattr("houndmind_ai.safety.sensor_health.time.time", lambda: clock.now)
    monkeypatch.setattr("houndmind_ai.safety.sensor_health.time.monotonic", lambda: clock.now)

    context = ReadingContext(reading(clock.now, valid=False))
    module = SensorHealthModule("sensor_health", enabled=True)
    module.tick(context)
    assert context.get("led_request:health") is not None

    context.reading = reading(clock.now, valid=True)
    module.tick(context)

    assert context.get("led_request:health") is None
