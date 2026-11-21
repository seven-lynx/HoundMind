"""`safety/health_monitor.py` through the `Module` contract (#401).

It was the one module no test named, so a change to it could land unobserved. The interesting parts
are all in one tick: the sampling cadence, what "degraded" means, the high-water marks, and the two
intervals it throttles. The four system readers are patched — a test may not read `/sys`, and on a
workstation there is no `/sys/class/thermal` to read.
"""

from __future__ import annotations

import pytest

from houndmind_ai.safety import health_monitor


class Context:
    """The two-method object a `Module` actually uses."""

    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {"settings": settings or {}}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


@pytest.fixture
def readings(monkeypatch):
    """Patch the four readers. Returns a setter so a test picks the sample."""

    sample = {"load": 0.2, "temp": 45.0, "gpu": 46.0, "mem": 20.0}

    def read_load():
        return sample["load"]

    def read_temp():
        return sample["temp"]

    def read_gpu():
        return sample["gpu"]

    def read_mem():
        return sample["mem"]

    monkeypatch.setattr(health_monitor, "_read_load_1m", read_load)
    monkeypatch.setattr(health_monitor, "_read_cpu_temp_c", read_temp)
    monkeypatch.setattr(health_monitor, "_read_gpu_temp_c", read_gpu)
    monkeypatch.setattr(health_monitor, "_read_mem_used_pct", read_mem)
    return sample


def build(settings: dict | None = None) -> tuple[health_monitor.HealthMonitorModule, Context]:
    context = Context(settings)
    module = health_monitor.HealthMonitorModule("health")
    module.start(context)
    return module, context


def test_start_publishes_the_neutral_state() -> None:
    module, context = build()

    assert context.get("health_degraded") is False
    assert context.get("scan_interval_override_s") is None
    assert context.get("vision_frame_interval_override_s") is None
    assert context.get("health_status_last_log_ts") == 0.0
    assert module.name == "health"


def test_a_healthy_sample_publishes_the_numbers_and_no_override(readings) -> None:
    module, context = build()

    module.tick(context)

    status = context.get("health_status")
    assert status["load_1m"] == 0.2
    assert status["temp_c"] == 45.0
    assert status["mem_used_pct"] == 20.0
    assert status["cpu_cores"] >= 1
    assert status["degraded"] is False
    assert status["degraded_reasons"] == []
    assert context.get("health_degraded") is False
    assert context.get("scan_interval_override_s") is None
    assert context.get("health_high_water")["temp_c"] == 45.0


def test_a_hot_cpu_is_degraded_and_throttles_the_scan_interval(readings) -> None:
    readings["temp"] = 80.0
    module, context = build({"performance": {"health_actions": ["throttle_scans"]}})

    module.tick(context)

    status = context.get("health_status")
    assert status["degraded"] is True
    assert status["degraded_reasons"] == ["temp"]
    assert context.get("health_degraded") is True
    # min(0.5 x 2.0, 0.5 + 1.0) — both sides of the rule, so either cap wins honestly.
    assert context.get("scan_interval_override_s") == 1.0


def test_throttle_vision_is_a_separate_switch(readings) -> None:
    readings["mem"] = 99.0
    module, context = build({"performance": {"health_actions": ["throttle_vision"]}})

    module.tick(context)

    assert context.get("health_status")["degraded_reasons"] == ["memory"]
    assert context.get("vision_frame_interval_override_s") == pytest.approx(0.4)
    assert context.get("scan_interval_override_s") is None, "vision was asked for, not scans"


def test_the_sample_happens_on_its_own_cadence(readings) -> None:
    module, context = build({"performance": {"health_monitor_interval_s": 60.0}})

    module.tick(context)
    first = context.get("health_status")["timestamp"]
    readings["temp"] = 90.0
    module.tick(context)

    assert context.get("health_status")["timestamp"] == first, "a second tick inside the window runs"
    assert context.get("health_status")["temp_c"] == 45.0


def test_high_water_marks_keep_the_worst_sample(readings) -> None:
    module, context = build({"performance": {"health_monitor_interval_s": 0.0}})

    module.tick(context)
    readings["temp"] = 71.0
    module.tick(context)
    readings["temp"] = 50.0
    module.tick(context)

    assert context.get("health_high_water")["temp_c"] == 71.0


def test_a_config_value_that_is_not_a_number_does_not_raise(readings) -> None:
    """Bare `float(cfg_value)` on user input is the defect the numeric rule exists for (#402)."""
    module, context = build(
        {
            "performance": {
                "health_monitor_interval_s": "soon",
                "health_temp_warn_c": None,
                "health_actions": ["throttle_scans"],
            },
            "navigation": {"scan_interval_s": "fast"},
        }
    )

    module.tick(context)

    assert context.get("health_status")["degraded"] is False
    assert context.get("health_status")["temp_c"] == 45.0


def test_stop_clears_the_overrides() -> None:
    module, context = build()
    module.tick(context)
    context.set("scan_interval_override_s", 9.0)

    module.stop(context)

    assert context.get("health_degraded") is False
    assert context.get("scan_interval_override_s") is None
