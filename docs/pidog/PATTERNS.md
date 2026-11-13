# PiDog & RobotHAT — Patterns

Status: **guide** — how to structure vendor code so it does not wedge the bus, plus the index of
every quirk this set has found.
Verified against: `sunfounder/pidog@cee4bff`, `sunfounder/robot-hat@4556bd8` (2.5.x)
Pairs with: `INDEX.md` (router), `src/houndmind_ai/hal/vendor.py` (the port of all of this)

Sections: §1 a safe script · §2 concurrency · §3 motion safety · §4 sensor validity ·
§5 quirk index · §6 units cheat sheet · §7 porting into the HAL · §8 testing without hardware

---

## 1. A script that will not wedge the bus

```python
"""Move the head, read the distance, put the dog down. Dry by default."""
import argparse
import logging

from pidog import Pidog

log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--move", action="store_true", help="actually move the dog")
    args = parser.parse_args()
    if not args.move:
        log.info("dry run: pass --move to drive the servos")
        return 0

    dog = Pidog()                       # this alone moves the dog to 'lie'
    try:
        dog.head_move([[30, 0, 0]], speed=60)
        dog.wait_head_done()
        log.info("distance %.1f cm", dog.read_distance())

        dog.do_action("wag_tail", speed=100, step_count=2)
        dog.wait_all_done()
    finally:
        dog.body_stop()
        dog.close()                     # returns the dog to 'lie' and stops the threads
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The four rules this encodes:

1. **Construct once.** `Pidog()` resets the MCU and initialises twelve servos. Two constructions in
   one process leave the first one's threads running against a re-initialised board.
2. **One owner per dog.** Two processes both holding a `Pidog` means two sets of threads writing
   the same I2C bus and two gaits fighting for the same legs. There is no lock across processes.
3. **`close()` in a `finally`.** It is what stops five threads and returns the dog to a known
   pose.
4. **Dry by default.** Anything that reaches a servo behind an explicit flag is the only version
   of this code that is safe to run by accident.

Logging, not `print`: `pidog` itself prints to stdout, and mixing the two makes a support bundle
unreadable. HoundMind's runtime uses `logging.getLogger(__name__)` per module with `%`-style lazy
formatting, so a disabled log level costs nothing.

---

## 2. Concurrency

The dog object is not thread-safe in any useful sense. It is a dozen attributes mutated by six
threads, with per-buffer locks that protect the lists and nothing else.

### 2.1 What is already concurrent

`legs_thread`, `head_thread`, `tail_thread`, `rgb_strip_thread`, `imu_thread` and `sensory_thread`
start in the constructor and run until `close()` (`PIDOG-MOTION.md` §2). Your code is a seventh
writer.

### 2.2 The rules

| Rule | Why |
|---|---|
| Call `legs_move` / `head_move` / `tail_move` / `do_action`, never `servo_move` | those take the buffer lock; `servo_move` does not |
| One thread issues motion, others observe | `immediately=True` cancels the queue, so two issuers fight |
| Never block the thread that owns the tick | `wait_all_done()` can take seconds; `speak()` shells out |
| Never call `read()` on the sound sensor from two places | it resets the module's busy line |
| Expect `immediately=True` to be a cancel, not a merge | it calls `*_stop()` first |

### 2.3 The pattern that works

One producer (the thread that decides), many readers (threads that report), and every motion
request funnelled through one queue that the producer drains:

```python
import queue
import threading

requests: queue.Queue = queue.Queue()


def worker(dog) -> None:
    while (name := requests.get()) is not None:
        dog.do_action(name, speed=60)
        dog.wait_all_done()


t = threading.Thread(target=worker, args=(dog,), daemon=True)
t.start()
requests.put("sit")
...
requests.put(None)
t.join()
```

This is the shape HoundMind uses in `act/gateway.py` — a single consumer that owns the hardware,
with typed intents coming in from everywhere else.

---

## 3. Motion safety

- **Construction is motion.** `Pidog()` moves the dog to the lie pose. So does `close()`.
- **`do_action` returns immediately.** If you never wait, the next call with `immediately=True`
  discards what you queued, and a gait that "didn't happen" is usually a gait that was cancelled.
- **A clamped angle is silent.** The head path clamps; the legs path can raise (in theory) but the
  working path clamps too. A pose that looks wrong is usually a value that was limited.
- **Low speeds drag.** The `sit_2_stand` call site warns `speed > 70`; in general, legs below
  about 40 move slowly enough that the body sags between steps.
- **A buffer is unbounded.** `legs_move(frames * 100)` is 10 000 frames of motion with no trim
  except `legs_stop()`.
- **`ActionFlow` idles with motion.** A started flow animates the dog every 2–6 s
  (`PIDOG-ACTIONS.md` §4.4).

Anything you write that can move the dog defaults to dry and requires an explicit flag. Nobody runs
it for you: a motion path is opt-in, and a run needs a human who has looked at the dog and cleared the
floor around it.


---

## 4. Sensor validity

The vendor gives you values without validity. Three of them have sentinels; the rest simply go
stale. The discipline that survives both:

```python
reading = dog.read_distance()
if reading is None or reading <= 0:
    distance_cm, valid = None, False
else:
    distance_cm, valid = reading, True
```

1. **Sentinel before value.** `PIDOG-SENSORS.md` §6.1 lists them per sensor. `-1`, `-2` and
   `False` are all "no data", and all of them will happily flow into arithmetic.
2. **Freeze is not freshness.** `accData`, `pitch`, `roll` and `distance` keep their last value
   when their thread dies. Stamp what you act on.
3. **Debounce physical events.** A touch pad read once is a coin flip; the slide detector alone
   needs two reads inside 500 ms.
4. **Median, not mean, for distance.** One missed echo gives −1; three samples and a median
   survives it. `hal/vendor.py::sample_distance` is the reference implementation.

`hal/iface.py::SensorSnapshot` is the shape to copy: every field paired with a `*_valid` flag, and
`None` where there is no value, never `0`.

---

## 5. Quirk index

Everything this set found that will cost you an afternoon. Each row points at the detail.

| Quirk | Where |
|---|---|
| A missing `smbus2`/`lgpio`/`pyaudio`/`pygame` disables every `robot_hat` import | `ROBOTHAT.md` §1.2 |
| I2C failures return `False` instead of raising | `ROBOTHAT.md` §6.1 |
| PWM channels share a timer, so `freq()` on one changes another | `ROBOTHAT.md` §4.2 |
| `Servo.angle()` clamps to ±90 silently | `ROBOTHAT.md` §5.1 |
| `speed` is a duration, and saturates against `max_dps` | `ROBOTHAT.md` §5.3 |
| `Robot.do_action` needs a `move_list` nobody fills | `ROBOTHAT.md` §11.5 |
| `device.set_led()` never drives the pin | `ROBOTHAT.md` §11.2 |
| `Pin.value()` flips the pin to input when read | `ROBOTHAT.md` §11.3 |
| `active_state` is accepted and dropped | `ROBOTHAT.md` §11.4 |
| `import pidog` silences all warnings process-wide | `ROBOTHAT.md` §11.1 |
| `Pidog.speak` shells out to `sudo killall pulseaudio` | `PIDOG-EXPRESSION.md` §2.3 |
| Sound files are found in `~/pidog/sounds`, not in site-packages | `PIDOG-EXPRESSION.md` §2.1 |
| The LED thread never sleeps and shares the bus | `PIDOG-EXPRESSION.md` §5 |
| `head_move` blends roll and pitch as yaw approaches ±90° | `PIDOG-MOTION.md` §4.1 |
| Queued frames run at the *latest* speed, not the speed at queue time | `PIDOG-MOTION.md` §4.4 |
| "Done" means the buffer is empty, not that the servo arrived | `PIDOG-MOTION.md` §5 |
| `set_angle()` raises `AttributeError` on every call | `PIDOG-MOTION.md` §7.1 |
| `pose2coords()` needs `set_legs()` first | `PIDOG-MOTION.md` §7.2 |
| `read_distance()` is −1.0 until the sensor thread samples | `PIDOG-MOTION.md` §7.4 |
| A misspelled action name is silent | `PIDOG-MOTION.md` §7.5 |
| `dog.touch` is never updated | `PIDOG-MOTION.md` §8 |
| `ActionDict` iterates empty; the catalogue is properties | `PIDOG-ACTIONS.md` §2 |
| `actions_dict.set_height()` has no effect | `PIDOG-ACTIONS.md` §2 |
| `ActionFlow.stop()` can hang on an empty queue | `PIDOG-ACTIONS.md` §6 |
| The `"stop"` operation does nothing | `PIDOG-ACTIONS.md` §6 |
| An idle `ActionFlow` moves the dog by itself | `PIDOG-ACTIONS.md` §4.4 |
| Two IMU calibrations exist and apply to different outputs | `PIDOG-SENSORS.md` §4.5 |
| `sh3001_getimudata` raises `TypeError` on a failed read | `PIDOG-SENSORS.md` §4.1 |
| `pitch`/`roll` use `atan`, so they saturate near vertical | `PIDOG-SENSORS.md` §4.3 |
| Calibration files resolve from `SUDO_USER`, so sudo sees a different file | `HARDWARE.md` §6 |
| The GPIO chip number moves across Pi 5 kernels | `HARDWARE.md` §7.2 |
| Multiplying `brightness` above 1 asks for values past 255 | `PIDOG-EXPRESSION.md` §1.3 |

---

## 6. Units cheat sheet

| You are passing | Unit | Range | Clamped? |
|---|---|---|---|
| `Servo.angle()` | degrees | −90…90 | yes, silently |
| head `[yaw, roll, pitch]` | degrees | ±90 / ±70 / −45…30 | yes, in the thread |
| leg angles | degrees | −90…90 per servo | yes |
| `speed` | 0–100 (a duration, see §5.3 of `ROBOTHAT.md`) | 0–100 | yes, in `servo_move` |
| `bpm` | beats per minute | positive | no |
| foot position | mm, `(y, z)` from the shoulder | reachable set | geometry clamps |
| body pose | mm / degrees | — | no |
| distance | cm | 0–290 | no |
| sound bearing | degrees, 20° steps | 0–359, or −1 | no |
| IMU | LSB | int16 | n/a |
| `volume` | 0–100 | — | by `pygame`, not by the vendor |
| `brightness` | multiplier | 0–1 | **no** |
| `bps` | frames per second | > 0 | no |
| battery | volts | 6.0–8.4 | no |


---

## 7. Porting vendor code into the HAL

In HoundMind, `src/houndmind_ai/hal/vendor.py` is the **only** file allowed to import `pidog` — it
and `optional/` are the two places a vendor import may appear. Everything above it sees a `DogHAL`.

The procedure, in order:

1. **Decide whether it belongs in the HAL at all.** If the value can be derived above the
   boundary — a threshold, a decision, a clamp — it does not.
2. **Import lazily.** `from pidog import Pidog` goes inside the method, never at module scope, so
   a workstation import costs nothing: `hal/vendor.py:112` does exactly this.
3. **Guard with `hasattr`.** The vendor's surface moves between builds:
   `if hasattr(dog, "head_move"): …` (`hal/vendor.py:408`).
4. **Take the bus lock.** `self._bus` guards every call that reaches a device, because the vendor
   has no lock of its own (`ROBOTHAT.md` §6.2).
5. **Return a dataclass with a validity flag**, never a bare value and never `None` where `0` is
   meaningful (`hal/iface.py::SensorSnapshot`).
6. **Do not block the tick.** No `wait_all_done()`, no `speak_block()`, no `sound_play()` on the
   caller's thread — hand it to a worker (`hal/vendor.py::_say`).
7. **Never raise into the loop.** Catch the narrow exception where you can, the broad one at the
   hardware boundary, and `logger.debug(..., exc_info=True)` so a support bundle has the trace.
8. **Extend `DogHAL` and `FakeDogHAL` in the same change.** A new protocol method without a fake
   implementation breaks `tests/test_hal_contract.py`.

The failure this prevents: a second module that imports `pidog` directly, which makes the whole
runtime un-importable on a workstation and untestable in CI.

---

## 8. Testing without hardware

| Want to | Do |
|---|---|
| Exercise logic that consumes sensors | `hal/fake.py::FakeDogHAL` |
| Test a new HAL method | add it to the fake first, then the contract test |
| Check that your module tolerates a missing vendor | import with `PYTHONPATH=src` and no `pidog` installed |
| Prove anything about servo motion | you cannot — that needs the Pi (`pi-verify`) |

```powershell
cd 'C:\Users\Seito\Github\HoundMind'
$env:PYTHONPATH='src'; python -m pytest -q tests\test_hal_contract.py
```

What a fake can never cover: real servo current draw, whether a pose is mechanically reachable,
I2C timing under load, or whether the head actually points where the kinematics say. Those are
device experiments, and a claim about them without a Pi run is a hypothesis.
