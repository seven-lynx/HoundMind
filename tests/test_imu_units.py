"""Raw IMU counts to physical units, and the heading that follows from them.

The defect behind this file: `Pidog.accData`/`gyroData` are raw LSB counts (the driver thread
reads `_sh3001_getimudata()`, `pidog.py:461`), while `SensorSnapshot` promises g and deg/s
(`hal/iface.py:133`). With the shipped `orientation.gyro_scale: 1.0` the module integrated counts
as if they were deg/s, so a real 90° turn accumulated roughly 16x as much heading.
"""

from __future__ import annotations

import pytest

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.vendor import ACC_LSB_PER_G, GYRO_LSB_PER_DPS, to_physical
from houndmind_ai.navigation.orientation import OrientationModule


def test_nominal_acc_scale_turns_counts_into_g() -> None:
    acc = to_physical((ACC_LSB_PER_G, 0.0, -ACC_LSB_PER_G), ACC_LSB_PER_G, ACC_LSB_PER_G)
    assert acc[0] == pytest.approx(1.0)
    assert acc[1] == pytest.approx(0.0)
    assert acc[2] == pytest.approx(-1.0)


def test_nominal_gyro_scale_turns_counts_into_degrees_per_second() -> None:
    raw = 90.0 * GYRO_LSB_PER_DPS
    gyro = to_physical((0.0, 0.0, raw), GYRO_LSB_PER_DPS, GYRO_LSB_PER_DPS)
    assert gyro[2] == pytest.approx(90.0)


def test_a_vendor_calibration_wins_over_the_nominal_scale() -> None:
    scale = (20000.0, ACC_LSB_PER_G, ACC_LSB_PER_G)
    acc = to_physical((20000.0, ACC_LSB_PER_G, 0.0), scale, ACC_LSB_PER_G)
    assert acc[0] == pytest.approx(1.0)
    assert acc[1] == pytest.approx(1.0)


def test_an_unusable_scale_falls_back_instead_of_dividing_by_zero() -> None:
    for bad in (0.0, None, "nope", (0.0, 0.0, 0.0), ()):
        acc = to_physical((ACC_LSB_PER_G, 0.0, 0.0), bad, ACC_LSB_PER_G)
        assert acc[0] == pytest.approx(1.0)


def test_a_short_scale_uses_the_nominal_for_the_missing_axis_only() -> None:
    acc = to_physical((16384.0, 16384.0, 16384.0), (32768.0,), ACC_LSB_PER_G)
    assert acc[0] == pytest.approx(0.5)
    assert acc[1] == pytest.approx(1.0)
    assert acc[2] == pytest.approx(1.0)


def test_bias_is_subtracted_before_the_scale() -> None:
    gyro = to_physical(
        (0.0, 0.0, GYRO_LSB_PER_DPS), GYRO_LSB_PER_DPS, GYRO_LSB_PER_DPS, (0.0, 0.0, GYRO_LSB_PER_DPS)
    )
    assert gyro[2] == pytest.approx(0.0)


class _Reading:
    """The two attributes `OrientationModule` reads off a sensor reading."""

    def __init__(self, gyro: tuple[float, float, float], timestamp: float) -> None:
        self.gyro = gyro
        self.timestamp = timestamp


def test_a_ninety_degree_turn_in_one_second_reads_ninety_degrees() -> None:
    context = RuntimeContext()
    context.set("settings", {"orientation": {"calibration_enabled": False, "gyro_scale": 1.0}})
    module = OrientationModule("orientation", enabled=True)
    module.start(context)

    for step in range(6):  # 5 intervals of 0.2 s after the first tick sets the clock
        context.set("sensor_reading", _Reading((0.0, 0.0, 90.0), float(step) * 0.2))
        module.tick(context)

    assert context.get("current_heading") == pytest.approx(90.0, abs=0.5)
