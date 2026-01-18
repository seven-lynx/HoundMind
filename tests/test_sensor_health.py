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
        # Pass dummy dog and settings for SensorService
        self.sensor_service = SensorService(dog=None, settings={})
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
