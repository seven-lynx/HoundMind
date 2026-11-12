"""The routine runner, driven end to end through the gateway and the fake dog.

Each test names the rule it covers:

- a routine asks for its steps one at a time, in order, and ends when it is done,
- two identical steps are two commands (`F-P2-2`, #65),
- a refusal ends the run instead of skipping the step (canon §8.2),
- a dry run never reaches the HAL,
- `settings.routines.dir` is what the runner reads, and one broken file costs nothing,
- a locomotion step carries the parameters the catalog promises (#64).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from houndmind_ai.act.gateway import MotionGatewayModule
from houndmind_ai.behavior.routine_runner import (
    DONE,
    REFUSED,
    RUNNING,
    STOPPED,
    RoutineRunnerModule,
)
from houndmind_ai.core.config import load_config
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.module import HalModule
from houndmind_ai.hal.motors import MotorModule
from houndmind_ai.hal.sensors import SensorReading
from houndmind_ai.kernel.commands import Source


class DummyContext:
    """The runtime context, minus the locking: these tests are single-threaded."""

    def __init__(self, settings: dict) -> None:
        self.data: dict = {"settings": settings}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)


def write_routine(
    directory: Path, routine_id: str, steps: list[dict], **document: Any
) -> Path:
    """One routine file, in the shape `kernel/routine.py` validates."""
    body = {"id": routine_id, "steps": steps, **document}
    path = directory / f"{routine_id}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def settings_for(directory: Path) -> dict:
    """The shipped settings, pointed at a temporary routine directory.

    The motor cooldown is zeroed on purpose: the tick loop here runs far faster than a real one,
    and the interval is the subject of its own test (`test_an_action_inside_the_interval_...`).
    """
    settings = dict(load_config().settings)
    settings["routines"] = {"dir": str(directory)}
    settings["motors"] = {**settings.get("motors", {}), "min_action_interval_s": 0.0}
    return settings


class Rig:
    """The three modules a routine passes through, ticked in the registry's order."""

    def __init__(self, directory: Path) -> None:
        self.hal = FakeDogHAL()
        self.context = DummyContext(settings_for(directory))
        HalModule("hal", hal=self.hal).start(self.context)
        self.gateway = MotionGatewayModule("motion_gateway")
        self.gateway.start(self.context)
        self.motors = MotorModule("hal_motors")
        self.motors.start(self.context)
        self.runner = RoutineRunnerModule("routine_runner")
        self.runner.start(self.context)

    def tick(self, count: int = 1) -> None:
        for _ in range(count):
            self.context.set("sensor_reading", SensorReading.from_snapshot(self.hal.read()))
            self.gateway.tick(self.context)
            self.motors.tick(self.context)
            self.runner.tick(self.context)

    def run(self, routine_id: str, **request: Any) -> None:
        self.context.set("routine_request", {"id": routine_id, **request})
        self.tick(1)

    def drain(self, timeout: float = 2.0) -> None:
        """Wait for the motor worker, which is where a parameterised step runs."""
        worker = self.motors.worker
        deadline = time.time() + timeout
        while worker is not None and worker.busy and time.time() < deadline:
            time.sleep(0.005)

    def acted(self, *names: str) -> list[str]:
        return [name for name, _ in self.hal.calls if name in names]

    def state(self):
        return self.context.get("routine_run")

    def close(self) -> None:
        self.runner.stop(self.context)
        self.motors.stop(self.context)
        self.gateway.stop(self.context)


# --------------------------------------------------------------- a run, in order


def test_a_routine_runs_its_steps_in_order(tmp_path: Path) -> None:
    write_routine(tmp_path, "calm", [{"action": "sit"}, {"action": "wag_tail"}])
    rig = Rig(tmp_path)
    try:
        rig.run("calm")
        rig.tick(10)

        assert rig.acted("sit", "wag_tail") == ["sit", "wag_tail"]
        assert rig.state().state == DONE
        assert rig.state().index == 2
    finally:
        rig.close()


def test_two_identical_steps_are_two_commands(tmp_path: Path) -> None:
    """`F-P2-2`: the gateway and the motors both drop a repeat, so the runner has to retire one."""
    write_routine(tmp_path, "twice", [{"action": "sit"}, {"action": "sit"}])
    rig = Rig(tmp_path)
    try:
        rig.run("twice")
        rig.tick(10)

        assert rig.acted("sit") == ["sit", "sit"]
        assert rig.state().state == DONE
    finally:
        rig.close()


def test_a_dry_run_moves_nothing(tmp_path: Path) -> None:
    write_routine(tmp_path, "calm", [{"action": "sit"}, {"action": "wag_tail"}])
    rig = Rig(tmp_path)
    try:
        rig.run("calm", dry_run=True)
        rig.tick(10)

        assert rig.hal.calls == []
        assert rig.state().state == DONE
        assert rig.state().dry_run is True
    finally:
        rig.close()


def test_a_refusal_ends_the_run_instead_of_skipping(tmp_path: Path) -> None:
    """Canon §8.2: a routine that cannot run a step stops, it does not walk past it."""
    write_routine(
        tmp_path, "walkabout", [{"action": "forward"}, {"action": "forward"}], allow_locomotion=True
    )
    rig = Rig(tmp_path)
    try:
        rig.hal.set_distance(5.0)  # inside the 12 cm emergency stop
        rig.run("walkabout")
        rig.tick(8)

        assert rig.acted("forward") == []
        assert rig.state().state == REFUSED
        assert rig.state().veto == "obstacle"
    finally:
        rig.close()


def test_a_stop_request_ends_the_run_and_clears_the_board(tmp_path: Path) -> None:
    write_routine(tmp_path, "calm", [{"action": "sit"}, {"action": "stand"}, {"action": "lie"}])
    rig = Rig(tmp_path)
    try:
        rig.run("calm")
        rig.tick(1)
        assert rig.state().state == RUNNING

        rig.context.set("routine_stop", True)
        rig.tick(1)

        assert rig.state().state == STOPPED
        assert rig.gateway.board.find(Source.ROUTINE) is None
    finally:
        rig.close()


def test_an_unknown_routine_is_refused_by_name(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    try:
        rig.run("nope")
        rejection = rig.context.get("routine_rejection")

        assert rig.state() is None
        assert "'nope'" in rejection["reason"]
    finally:
        rig.close()


def test_a_second_start_while_one_is_running_is_refused(tmp_path: Path) -> None:
    write_routine(tmp_path, "calm", [{"action": "sit"}, {"action": "stand"}])
    rig = Rig(tmp_path)
    try:
        rig.run("calm")
        rig.run("calm")
        rejection = rig.context.get("routine_rejection")

        assert "still running" in rejection["reason"]
        assert rig.state().routine_id == "calm"
    finally:
        rig.close()


# ------------------------------------------------------- the store and the settings


def test_a_broken_file_does_not_cost_the_good_ones(tmp_path: Path) -> None:
    write_routine(tmp_path, "calm", [{"action": "sit"}])
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    rig = Rig(tmp_path)
    try:
        runner = rig.runner
        assert runner.report is not None
        assert runner.report.refused == 1
        assert "broken.json" in runner.report.refusals
        assert runner.report.ids() == ("calm",)
        assert rig.context.get("routine_report") is runner.report

        rig.run("calm")
        rig.tick(6)
        assert rig.acted("sit") == ["sit"]
    finally:
        rig.close()


def test_the_directory_comes_from_settings_routines_dir(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    try:
        assert rig.runner.store is not None
        assert rig.runner.store.directory == tmp_path
    finally:
        rig.close()


def test_a_run_without_an_intent_board_is_refused(tmp_path: Path) -> None:
    """No gateway means nowhere to publish; the run says so instead of pretending to play."""
    write_routine(tmp_path, "calm", [{"action": "sit"}])
    context = DummyContext(settings_for(tmp_path))
    runner = RoutineRunnerModule("routine_runner")
    runner.start(context)
    context.set("routine_request", {"id": "calm"})

    runner.tick(context)

    state = context.get("routine_run")
    assert state.state == REFUSED
    assert state.veto == "no_board"


# --------------------------------------------------------- what reaches the HAL


def test_a_locomotion_step_carries_its_parameters(tmp_path: Path) -> None:
    """#64: the catalog declares `speed`/`steps` for `forward`, so the HAL has to receive them."""
    write_routine(
        tmp_path,
        "creep",
        [{"action": "forward", "params": {"speed": 150, "steps": 2}}],
        allow_locomotion=True,
    )
    rig = Rig(tmp_path)
    try:
        rig.run("creep")
        rig.tick(6)
        rig.drain()

        assert ("forward", {"speed": 150, "steps": 2}) in rig.hal.calls, rig.hal.calls
    finally:
        rig.close()


def test_an_action_inside_the_interval_is_deferred_not_dropped(tmp_path: Path) -> None:
    """#65: the cooldown delays a command; it no longer swallows it."""
    rig = Rig(tmp_path)
    try:
        rig.context.get("settings")["motors"]["min_action_interval_s"] = 0.05

        rig.gateway.board.publish("sit", Source.CLIENT)
        rig.tick(1)
        assert rig.acted("sit", "stand") == ["sit"]

        rig.gateway.board.publish("stand", Source.CLIENT)
        rig.tick(1)
        assert rig.acted("sit", "stand") == ["sit"], "the cooldown must not fire it early"
        assert rig.motors.rate_limited == 1

        time.sleep(0.06)
        rig.tick(1)
        assert rig.acted("sit", "stand") == ["sit", "stand"]
        assert rig.motors.rate_limited == 0
    finally:
        rig.close()
