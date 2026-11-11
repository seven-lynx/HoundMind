"""The servo bus has one owner at a time (P3-2).

Three callers now reach the same I2C bus: the loop's motors, the scan worker's head moves and
distance sampling, and the attention module. The vendor action queue is not thread-safe, so the
adapter serialises them. `PidogHAL` takes an injected `dog`, which is how this is tested without
importing `pidog` on a workstation.
"""

from __future__ import annotations

import threading
import time

from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.hal.motors import MotorModule
from houndmind_ai.hal.vendor import PidogHAL


class StubDog:
    """Just enough of `pidog.Pidog` to see whether two callers overlap."""

    def __init__(self, hold_s: float = 0.05) -> None:
        self.hold_s = hold_s
        self.inside = 0
        self.max_inside = 0
        self.lock = threading.Lock()
        self.head_calls = 0

    def _enter(self) -> None:
        with self.lock:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        time.sleep(self.hold_s)
        with self.lock:
            self.inside -= 1

    def head_move(self, *args, **kwargs) -> None:
        self.head_calls += 1
        self._enter()

    def do_action(self, name: str, step_count: int = 1, speed: int = 200) -> None:
        self._enter()

    def wait_all_done(self) -> None:
        return None

    def read_distance(self) -> float:
        self._enter()
        return 100.0

    def read_touch(self) -> str:
        return "N"

    def read_sound_direction(self) -> int | None:
        return None

    def get_acceleration(self):
        return (0.0, 0.0, 9.8)

    def get_gyroscope(self):
        return (0.0, 0.0, 0.0)

    def ultra_sound(self):
        return self.read_distance()


def test_the_adapter_satisfies_the_protocol() -> None:
    assert isinstance(PidogHAL(settings={}, dog=StubDog()), DogHAL)


def test_two_threads_never_share_the_bus() -> None:
    dog = StubDog(hold_s=0.02)
    hal = PidogHAL(settings={}, dog=dog)

    def move(yaw: float) -> None:
        hal.action("head", {"yaw": yaw, "pitch": 0, "speed": 70, "wait": True})

    threads = [threading.Thread(target=move, args=(float(index),)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)

    assert dog.head_calls == 6
    assert dog.max_inside == 1, "two vendor calls overlapped on the bus"


def test_sampling_and_reading_do_not_overlap_either() -> None:
    dog = StubDog(hold_s=0.02)
    hal = PidogHAL(settings={}, dog=dog)

    def sample() -> None:
        hal.sample_distance(3, 0.0)

    def read() -> None:
        hal.read()

    threads = [threading.Thread(target=sample), threading.Thread(target=read)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)

    assert dog.max_inside == 1


def test_stop_takes_the_bus_too() -> None:
    """An emergency stop must not interleave with a step in progress."""
    dog = StubDog(hold_s=0.02)
    dog.emergency_stop = dog._enter
    hal = PidogHAL(settings={}, dog=dog)

    mover = threading.Thread(
        target=lambda: hal.action("forward", {"speed": 100, "steps": 1, "wait": True})
    )
    stopper = threading.Thread(target=hal.stop)

    mover.start()
    stopper.start()
    mover.join(5.0)
    stopper.join(5.0)

    assert dog.max_inside == 1


def test_head_following_does_not_block_the_tick() -> None:
    """A cosmetic head move must never set the loop's cadence (P3-2)."""
    hal = FakeDogHAL()
    seen: list[dict] = []

    class Recorder:
        def __init__(self) -> None:
            self.calls = seen

        def action(self, name, params):
            self.calls.append({"name": name, **params})

    context = type(
        "Ctx",
        (),
        {
            "data": {
                "settings": {
                    "motors": {
                        "head_turn_follow_enabled": True,
                        "head_turn_follow_deg": 45,
                        "head_turn_follow_speed": 70,
                    }
                },
                "hal": Recorder(),
            },
            "set": lambda self, key, value: self.data.__setitem__(key, value),
            "get": lambda self, key, default=None: self.data.get(key, default),
        },
    )()

    module = MotorModule("hal_motors")
    module.hal = context.get("hal")
    module._apply_head_follow("left", context)

    head = [call for call in seen if call["name"] == "head"]
    assert head, seen
    assert head[0]["wait"] is False


def test_a_scan_owns_the_head() -> None:
    """While a sweep is running, nothing else may move the head."""
    hal = FakeDogHAL()
    context = type(
        "Ctx",
        (),
        {
            "data": {
                "settings": {
                    "motors": {
                        "head_turn_follow_enabled": True,
                        "head_turn_follow_deg": 45,
                        "head_turn_follow_speed": 70,
                    }
                },
                "hal": hal,
                "scan_in_flight": True,
            },
            "set": lambda self, key, value: self.data.__setitem__(key, value),
            "get": lambda self, key, default=None: self.data.get(key, default),
        },
    )()

    module = MotorModule("hal_motors")
    module.hal = hal
    module._apply_head_follow("left", context)

    assert not [name for name, _ in hal.calls if name == "head"]