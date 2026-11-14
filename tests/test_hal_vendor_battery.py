"""The battery feed, end to end: vendor read -> snapshot -> reading -> the published key.

`SensorSnapshot.battery_v` existed, `FakeDogHAL.set_battery` filled it, and on a real dog nothing
did: `PidogHAL.read` left the field at its default, `SensorReading` had nowhere to put it, and no
code path set `battery_voltage`, so the low-voltage veto in `act/interlock.py` and the `battery`
section of `behavior/fsm.py` were both unreachable (#119).
"""

from __future__ import annotations

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.sensors import SensorModule, SensorReading
from houndmind_ai.hal.vendor import PidogHAL

# One distance sample and no delay: the snapshot read has to stay fast, and the distance path is
# covered by its own tests.
FAST = {
    "sensors": {
        "distance_samples": 1,
        "distance_sample_delay_s": 0.0,
        "battery_poll_s": 2.0,
    }
}


class ScriptedDog:
    """The one vendor method the battery read uses."""

    def __init__(self, volts: float | None = None, error: Exception | None = None) -> None:
        self.volts = volts
        self.error = error
        self.calls = 0

    def get_battery_voltage(self) -> float:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.volts is not None
        return self.volts


def test_the_vendor_reading_reaches_the_snapshot() -> None:
    dog = ScriptedDog(7.42)
    hal = PidogHAL(settings=FAST, dog=dog, clock=lambda: 100.0)

    snapshot = hal.read()

    assert snapshot.battery_v == 7.42
    assert snapshot.battery_valid is True


def test_the_pack_is_polled_on_its_own_cadence() -> None:
    """The read is an ADC transaction on the servo bus, so it is cached for `battery_poll_s`."""
    dog = ScriptedDog(7.42)
    hal = PidogHAL(settings=FAST, dog=dog)

    assert hal._read_battery(dog, now=100.0) == (7.42, True)
    assert hal._read_battery(dog, now=101.0) == (7.42, True)
    assert dog.calls == 1
    assert hal._read_battery(dog, now=103.0) == (7.42, True)
    assert dog.calls == 2


def test_a_disconnected_sense_line_is_not_a_flat_pack() -> None:
    """0 V is what a floating ADC reads; vetoing motion on it would freeze the dog for good."""
    dog = ScriptedDog(0.0)
    hal = PidogHAL(settings=FAST, dog=dog)

    assert hal._read_battery(dog, now=100.0) == (None, False)


def test_a_failed_read_keeps_the_last_good_value_but_reports_it_invalid() -> None:
    dog = ScriptedDog(7.42)
    hal = PidogHAL(settings=FAST, dog=dog)
    assert hal._read_battery(dog, now=100.0) == (7.42, True)

    dog.error = OSError("i2c")
    assert hal._read_battery(dog, now=103.0) == (7.42, False)

    # A feed that goes to 0 V afterwards must not resurrect the old value as valid.
    dog.error = None
    dog.volts = 0.0
    assert hal._read_battery(dog, now=107.0) == (None, False)


def test_the_module_publishes_the_key_the_interlock_reads() -> None:
    """The hop that was missing: a HAL snapshot becomes `battery_voltage` in the context."""
    hal = FakeDogHAL()
    hal.set_battery(7.42)
    context = RuntimeContext()
    module = SensorModule("hal_sensors")

    # `_publish` is what both the polling service and `tick` call. Driving it directly keeps this
    # test off the sensor thread; the thread itself is `tests/test_hal_wiring.py`.
    module._publish(context, SensorReading.from_snapshot(hal.read()))

    assert context.get("battery_voltage") == 7.42
    assert context.get("sensor_health")["battery_valid"] is True


def test_an_invalid_reading_does_not_overwrite_the_last_good_value() -> None:
    hal = FakeDogHAL()
    context = RuntimeContext()
    module = SensorModule("hal_sensors")
    hal.set_battery(7.42)
    module._publish(context, SensorReading.from_snapshot(hal.read()))

    hal.set_battery(None)
    module._publish(context, SensorReading.from_snapshot(hal.read()))

    assert context.get("battery_voltage") == 7.42
    assert context.get("sensor_health")["battery_valid"] is False
