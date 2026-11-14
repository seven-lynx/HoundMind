"""The calibration flow end to end, on the fake dog (#10).

Before this, `servo_zero` read `context["pidog"]` — a raw vendor handle `FakeDogHAL` cannot
provide — so the one workflow that reports user-visible servo trim was the one path no test could
reach. This file drives the real `HalModule` and `CalibrationModule` against `FakeDogHAL`.

Motion: none. `servo_zero` only reads, and the calibration tool is a separate device CLI.
"""

from __future__ import annotations

import json

from houndmind_ai.calibration.workflow import CalibrationModule
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import LEG_SERVO_NAMES
from houndmind_ai.hal.module import HalModule


class DummyContext:
    """The runtime context, minus the locking: these tests are single-threaded."""

    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {"settings": settings or {}}

    def set(self, key, value) -> None:
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __contains__(self, key) -> bool:
        return key in self.data


def fake_with_trim() -> FakeDogHAL:
    hal = FakeDogHAL()
    hal.set_offsets({name: float(index) for index, name in enumerate(LEG_SERVO_NAMES)})
    return hal


def settings_for(tmp_path) -> dict:
    return {"calibration": {"persist_path": str(tmp_path / "calibration.json")}}


def test_hal_module_publishes_no_vendor_handle() -> None:
    """The last door out of the boundary: `context["pidog"]` no longer exists."""
    fake = FakeDogHAL()
    ctx = DummyContext()
    module = HalModule("hal", hal=fake)

    module.start(ctx)
    assert ctx.get("hal") is fake
    assert "pidog" not in ctx.data

    module.stop(ctx)
    assert "pidog" not in ctx.data


def test_servo_zero_reports_what_the_hal_reads(tmp_path) -> None:
    hal = fake_with_trim()
    ctx = DummyContext(settings_for(tmp_path))
    HalModule("hal", hal=hal).start(ctx)
    ctx.set("calibration_request", "servo_zero")

    CalibrationModule("calibration").tick(ctx)

    result = ctx.get("calibration_result")
    assert result["status"] == "ok"
    assert result["servo_zero_offsets"] == hal.read_offsets()
    assert hal.offsets_applied == [], "reading the trim must not write it"

    payload = json.loads((tmp_path / "calibration.json").read_text(encoding="utf-8"))
    assert payload["last_result"]["servo_zero_offsets"] == hal.read_offsets()


def test_servo_zero_without_a_hal_is_no_data_not_a_crash(tmp_path) -> None:
    ctx = DummyContext(settings_for(tmp_path))
    ctx.set("calibration_request", "servo_zero")

    CalibrationModule("calibration").tick(ctx)

    result = ctx.get("calibration_result")
    assert result["status"] == "no_data"
    assert result["servo_zero_offsets"] == {}


def test_the_request_can_come_from_settings(tmp_path) -> None:
    hal = fake_with_trim()
    settings = settings_for(tmp_path)
    settings["calibration"]["request"] = "servo_zero"
    ctx = DummyContext(settings)
    HalModule("hal", hal=hal).start(ctx)

    CalibrationModule("calibration").tick(ctx)

    assert ctx.get("calibration_result")["status"] == "ok"


def test_the_same_request_is_not_re_run_every_tick(tmp_path) -> None:
    """The guard that stops a config-set request from rewriting the file 5 times a second."""
    hal = fake_with_trim()
    ctx = DummyContext(settings_for(tmp_path))
    HalModule("hal", hal=hal).start(ctx)
    ctx.set("calibration_request", "servo_zero")
    module = CalibrationModule("calibration")

    module.tick(ctx)
    first = ctx.get("calibration_result")
    module.tick(ctx)

    assert ctx.get("calibration_result") is first


def test_an_api_request_carries_an_id_so_the_same_read_can_run_twice(tmp_path) -> None:
    """`POST /calibration/run` twice with the same name is two runs (#17).

    The re-run guard exists to stop a *config* request rewriting the file five times a second. It
    compares the pair (request, id), so the API can ask for the same reading again while a config
    that never changes still runs once.
    """
    hal = fake_with_trim()
    ctx = DummyContext(settings_for(tmp_path))
    HalModule("hal", hal=hal).start(ctx)
    module = CalibrationModule("calibration")

    ctx.set("calibration_request", {"request": "servo_zero", "id": "a1"})
    module.tick(ctx)
    first = ctx.get("calibration_result")
    assert first["request_id"] == "a1"
    assert first["status"] == "ok"

    module.tick(ctx)
    assert ctx.get("calibration_result") is first, "the same id is the request already answered"

    ctx.set("calibration_request", {"request": "servo_zero", "id": "b2"})
    module.tick(ctx)
    second = ctx.get("calibration_result")
    assert second is not first
    assert second["request_id"] == "b2"
    assert hal.offsets_applied == [], "two reads are still reads"


def test_a_persist_path_that_cannot_be_written_does_not_break_the_tick(tmp_path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    hal = fake_with_trim()
    ctx = DummyContext({"calibration": {"persist_path": str(blocker / "calibration.json")}})
    HalModule("hal", hal=hal).start(ctx)
    ctx.set("calibration_request", "servo_zero")

    CalibrationModule("calibration").tick(ctx)

    assert ctx.get("calibration_result")["status"] == "ok"
