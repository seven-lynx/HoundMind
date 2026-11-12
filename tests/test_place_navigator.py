"""The place navigator, driven end to end through the gateway and the fake dog.

Each test names the rule it covers:

- a request publishes a `place` intent, and one accepted `forward` is one `step_cm`,
- an obstacle outranks the goal, because `Place` sits under `Navigation` (canon §6.3),
- arrival stops the dog and writes the visit **once**, not once per tick,
- a store that does not know the place is a refusal with a suggestion, never a guess,
- the anchor is a precondition: unconfirmed, or taught against another one, is a refusal,
- no heading means no movement, and a goal that cannot get there times out instead of walking on,
- a failed approach decays only a confidence that was measured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from houndmind_ai.act.gateway import MotionGatewayModule
from houndmind_ai.core.config import load_config
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.module import HalModule
from houndmind_ai.hal.motors import MotorModule
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.kernel.commands import Source, mode_allows
from houndmind_ai.kernel.place_store import PlaceStore
from houndmind_ai.navigation.place_navigator import (
    ABANDONED,
    ARRIVED,
    REFUSED,
    TRAVELLING,
    PlaceNavigatorModule,
    heading_error,
)


class DummyContext:
    """The runtime context, minus the locking: these tests are single-threaded."""

    def __init__(self, settings: dict) -> None:
        self.data: dict = {"settings": settings}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


class Clock:
    """The navigator's clock, owned by the test: nothing here sleeps through a timeout."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def place_model(**overrides: Any) -> dict:
    """One place in the stored shape. `id` is the slug of the name, filled in by the loader."""
    body: dict[str, Any] = {"name": "Kitchen", "heading_deg": 0.0, "distance_cm": 100.0}
    body.update(overrides)
    return body


def write_places(path: Path, *places: dict) -> Path:
    path.write_text(json.dumps({"version": 1, "places": list(places)}), encoding="utf-8")
    return path


def stored(path: Path) -> list[dict]:
    """The places file as it is on disk right now."""
    return json.loads(path.read_text(encoding="utf-8"))["places"]


def settings_for(**places: Any) -> dict:
    """The shipped settings with the motor cooldown zeroed and `settings.places` overridable.

    The cooldown is off because the tick loop here runs far faster than a real one; the interval
    is the subject of its own test elsewhere.
    """
    settings = dict(load_config().settings)
    settings["motors"] = {**settings.get("motors", {}), "min_action_interval_s": 0.0}
    settings["places"] = {**settings.get("places", {}), **places}
    return settings


class Rig:
    """The four modules a goal passes through, ticked in the registry's order."""

    def __init__(
        self,
        path: Path,
        *,
        heading: float | None = 0.0,
        distance_cm: float = 200.0,
        clock: Clock | None = None,
        **places: Any,
    ) -> None:
        self.path = path
        self.hal = FakeDogHAL()
        self.hal.set_distance(distance_cm)
        self.context = DummyContext(settings_for(**places))
        # Every write the store makes, by file name: the proof that a visit is written once.
        self.writes: list[str] = []
        HalModule("hal", hal=self.hal).start(self.context)
        self.gateway = MotionGatewayModule("motion_gateway")
        self.gateway.start(self.context)
        self.motors = MotorModule("hal_motors")
        self.motors.start(self.context)
        self.clock = clock or Clock()
        self.navigator = PlaceNavigatorModule(
            "place_navigator", store=PlaceStore(str(path), write_text=self._write), clock=self.clock
        )
        self.navigator.start(self.context)
        if heading is not None:
            self.context.set("current_heading", heading)

    def _write(self, path: Path, text: str) -> None:
        self.writes.append(Path(path).name)
        Path(path).write_text(text, encoding="utf-8")

    def tick(self, count: int = 1) -> None:
        for _ in range(count):
            self.context.set("sensor_reading", SensorReading.from_snapshot(self.hal.read()))
            self.gateway.tick(self.context)
            self.motors.tick(self.context)
            self.navigator.tick(self.context)

    def request(self, place_id: str, **body: Any) -> None:
        self.context.set("place_request", {"id": place_id, **body})
        self.tick(1)

    def goal(self) -> dict:
        return self.context.get("place_goal") or {}

    def board(self):
        return self.context.get("intent_board")

    def motion(self) -> dict:
        return self.context.get("motion_command") or {}

    def acted(self, *names: str) -> list[str]:
        return [name for name, _ in self.hal.calls if name in names]

    def close(self) -> None:
        self.navigator.stop(self.context)
        self.motors.stop(self.context)
        self.gateway.stop(self.context)


# --------------------------------------------------------------- the goal, in motion


def test_a_request_publishes_a_place_intent(tmp_path: Path) -> None:
    """The segment's first claim: a goal reaches the gateway as `Source.PLACE`."""
    path = write_places(tmp_path / "places.json", place_model())
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchen", at_anchor=True)
        command = rig.board().find(Source.PLACE)
        assert command is not None, "the goal must publish an intent"
        assert command.action == "forward", "already facing the place, so walk"
        assert rig.goal()["state"] == TRAVELLING
        assert rig.goal()["distance_cm"] == 100.0
    finally:
        rig.close()


def test_one_accepted_forward_is_one_step(tmp_path: Path) -> None:
    """Distance is dead reckoning over commands the gateway accepted — never over ticks."""
    path = write_places(tmp_path / "places.json", place_model(distance_cm=200.0))
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchen", at_anchor=True)
        rig.tick(9)
        forwards = rig.acted("forward")
        assert forwards, "the dog must be asked to walk"
        assert rig.goal()["walked_cm"] == 25.0 * len(forwards)
    finally:
        rig.close()


def test_an_obstacle_outranks_the_goal(tmp_path: Path) -> None:
    """`Place` sits under `Navigation`: two producers, two slots, no stutter (canon §6.3)."""
    path = write_places(tmp_path / "places.json", place_model(distance_cm=200.0))
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchen", at_anchor=True)
        rig.board().publish("backward", Source.NAVIGATION)
        rig.tick(1)
        assert rig.motion()["source"] == "navigation", "avoidance must win the tick"

        rig.board().retract(Source.NAVIGATION)
        # Two ticks: the gateway runs before the producers, so a goal published this tick is
        # resolved by the next one — the same one-tick lag every producer has.
        rig.tick(2)
        assert rig.motion()["source"] == "place", "with the hazard gone the goal resumes"
    finally:
        rig.close()


def test_arrival_stops_the_dog_and_writes_one_visit(tmp_path: Path) -> None:
    """A visit is a transition: one write, one `visits + 1`, one stop."""
    path = write_places(tmp_path / "places.json", place_model(distance_cm=30.0))
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchen", at_anchor=True)
        rig.tick(4)
        goal = rig.goal()
        assert goal["state"] == ARRIVED
        assert goal["visits"] == 1
        assert goal["confidence"] == 0.1, "one arrival is one measurement"
        assert "stop" in rig.acted("stop")

        after = len(rig.writes)
        rig.tick(5)
        assert rig.goal()["state"] == ARRIVED, "a finished goal stays finished"
        assert len(rig.writes) == after, "standing on the place must not keep writing"
        assert stored(path)[0]["visits"] == 1
    finally:
        rig.close()


def test_an_unknown_place_is_refused_with_a_suggestion(tmp_path: Path) -> None:
    path = write_places(tmp_path / "places.json", place_model())
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchin", at_anchor=True)
        goal = rig.goal()
        assert goal["state"] == REFUSED
        assert goal["reason"] == "unknown_place"
        assert goal["suggestion"] == "kitchen"
        assert rig.hal.calls == [], "a refusal moves nothing"
        assert rig.board().find(Source.PLACE) is None
    finally:
        rig.close()


def test_a_request_that_does_not_confirm_the_anchor_is_refused(tmp_path: Path) -> None:
    path = write_places(tmp_path / "places.json", place_model())
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchen")
        assert rig.goal()["reason"] == "anchor_unconfirmed"
        assert rig.hal.calls == []
    finally:
        rig.close()


def test_a_place_taught_against_another_anchor_is_refused(tmp_path: Path) -> None:
    path = write_places(
        tmp_path / "places.json", place_model(anchor="kitchen_baseline")
    )
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchen", at_anchor=True)
        assert rig.goal()["reason"] == "anchor_mismatch"
        assert rig.hal.calls == []
    finally:
        rig.close()


def test_no_heading_means_no_movement(tmp_path: Path) -> None:
    """A navigator that cannot say which way it faces must not pick a turn."""
    path = write_places(tmp_path / "places.json", place_model())
    rig = Rig(path, heading=None)
    try:
        rig.request("kitchen", at_anchor=True)
        assert rig.goal()["state"] == ABANDONED
        assert rig.goal()["reason"] == "no_heading"
        assert rig.hal.calls == []
    finally:
        rig.close()




# --------------------------------------------------------- what a goal must not do


def test_a_refused_forward_is_not_progress(tmp_path: Path) -> None:
    """An obstacle blocks every step; the goal reports the veto instead of counting a step."""
    path = write_places(tmp_path / "places.json", place_model(distance_cm=200.0))
    rig = Rig(path, heading=0.0, distance_cm=8.0)
    try:
        rig.request("kitchen", at_anchor=True)
        rig.tick(4)
        goal = rig.goal()
        assert goal["walked_cm"] == 0.0, "a vetoed forward moves nothing"
        assert goal["veto"] == "obstacle", "the refusal must be visible, not silent"
        assert rig.acted("forward") == []
    finally:
        rig.close()


def test_a_goal_that_cannot_get_there_times_out(tmp_path: Path) -> None:
    path = write_places(tmp_path / "places.json", place_model(distance_cm=200.0))
    rig = Rig(path, heading=0.0, distance_cm=8.0, timeout_s=10.0)
    try:
        rig.request("kitchen", at_anchor=True)
        rig.tick(2)
        rig.clock.advance(30.0)
        rig.tick(2)
        goal = rig.goal()
        assert goal["state"] == ABANDONED
        assert goal["reason"] == "timeout"
        assert stored(path)[0]["visits"] == 0, "a failed approach is not a visit"
    finally:
        rig.close()


def test_an_abandoned_goal_decays_a_measured_confidence(tmp_path: Path) -> None:
    path = write_places(tmp_path / "places.json", place_model(confidence=0.5))
    rig = Rig(path, heading=0.0, distance_cm=8.0, timeout_s=10.0)
    try:
        rig.request("kitchen", at_anchor=True)
        rig.tick(2)
        rig.clock.advance(30.0)
        rig.tick(2)
        assert rig.goal()["state"] == ABANDONED
        assert stored(path)[0]["confidence"] == 0.4
        assert stored(path)[0]["visits"] == 0
    finally:
        rig.close()


def test_an_unmeasured_confidence_stays_unmeasured(tmp_path: Path) -> None:
    """Nothing measured this place yet, so a blocked approach has no confidence to take away."""
    path = write_places(tmp_path / "places.json", place_model())
    rig = Rig(path, heading=0.0, distance_cm=8.0, timeout_s=10.0)
    try:
        rig.request("kitchen", at_anchor=True)
        rig.tick(2)
        rig.clock.advance(30.0)
        rig.tick(2)
        assert rig.goal()["state"] == ABANDONED
        assert stored(path)[0]["confidence"] is None
    finally:
        rig.close()


def test_stopping_the_module_retracts_its_intent(tmp_path: Path) -> None:
    path = write_places(tmp_path / "places.json", place_model(distance_cm=200.0))
    rig = Rig(path, heading=0.0)
    try:
        rig.request("kitchen", at_anchor=True)
        assert rig.board().find(Source.PLACE) is not None
        rig.navigator.stop(rig.context)
        assert rig.board().find(Source.PLACE) is None
        assert rig.context.get("place_goal") is None
    finally:
        rig.motors.stop(rig.context)
        rig.gateway.stop(rig.context)


# --------------------------------------------------------------- pieces on their own


def test_heading_error_takes_the_short_way_round() -> None:
    assert heading_error(90.0, 0.0) == 90.0, "a target to the right is a positive turn"
    assert heading_error(350.0, 10.0) == -20.0, "wrapping past north turns left, not 340 right"
    assert heading_error(10.0, 350.0) == 20.0
    assert heading_error(180.0, 0.0) == -180.0


def test_a_place_intent_is_admitted_in_the_autonomy_modes_only() -> None:
    """`rest` parks the servos; a hand on the wheel may still name a place."""
    assert mode_allows("idle", Source.PLACE)
    assert mode_allows("patrol", Source.PLACE)
    assert mode_allows("manual", Source.PLACE)
    assert not mode_allows("rest", Source.PLACE)


def test_the_store_is_published_for_the_control_plane(tmp_path: Path) -> None:
    """PL5's routes write through *this* instance or not at all.

    `PlaceStore` guards its read-modify-write pairs with a per-instance lock, so the API building its
    own store over the same path would be a second writer with a second lock — the lost update the
    lock is there to prevent. The navigator publishes the one store, and takes it away when it stops.
    """
    rig = Rig(tmp_path / "places.json")
    assert rig.context.get("place_store") is rig.navigator.store

    rig.navigator.stop(rig.context)
    assert rig.context.get("place_store") is None

