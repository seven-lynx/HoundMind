# PiDog & RobotHAT — Motion

Status: **reference** — the `Pidog` object: what it starts, how a movement reaches a servo, and
where the motion code is broken.
Version: v2026.01.18 • Author: 7Lynx
Verified against: `sunfounder/pidog@cee4bff`, `sunfounder/robot-hat@4556bd8` (2.5.x)
Pairs with: `HARDWARE.md` §2–§3 (channel map, limits), `ROBOTHAT.md` §5 (speed model),
`PIDOG-ACTIONS.md` (named actions)

Sections: §1 construction · §2 threads · §3 lifecycle · §4 leg/head/tail movement ·
§5 waiting and cancelling · §6 body pose and kinematics · §7 known defects · §8 sensor
attributes

---

## 1. Construction

```python
from pidog import Pidog

dog = Pidog(
    leg_pins=None,            # default [2, 3, 7, 8, 0, 1, 10, 11]
    head_pins=None,           # default [4, 6, 5]  = yaw, roll, pitch
    tail_pin=None,            # default [9]
    leg_init_angles=None,     # default = first frame of the 'lie' action
    head_init_angles=None,    # default [0, 0, 45]
    tail_init_angle=None,     # default [0]
)
```

The constructor does a great deal, in this order:

1. `utils.reset_mcu()` and a 0.2 s settle — the MCU is power-cycled on every construction.
2. Builds `ActionDict`, sets `body_height = 80`, `pose`, `rpy`.
3. Builds three `Robot` objects (`legs`, `head`, `tail`) against
   `~/.config/pidog/pidog.conf`. The legs are initialised in the order
   `[0, 2, 4, 6, 1, 3, 5, 7]` — shoulders before knees, to keep the current spike down.
4. Sets `max_dps` per group (`HARDWARE.md` §3.2) and creates per-part action buffers and locks.
5. Builds the sensors: `Sh3001`, `RGBStrip(addr=0x74, nums=11)`, `DualTouch('D2','D3')`,
   `SoundDirection()`, `Music()`.
6. Starts five action threads plus the ultrasonic worker thread.

Every sensor block is wrapped in its own `try/except`: a missing IMU or LED board logs `fail` and
leaves the attribute absent, and the dog still walks. Anything that imports `dog.rgb_strip`
without a `hasattr`/`getattr` check will find that out the hard way.

```python
from pidog import Pidog
dog = Pidog()          # ~1 s of MCU reset + servo init noise; the dog moves to 'lie'
```

`Pidog()` moves the servos to the lie pose during construction. **That is motion.** Do not
construct one on a desk without clearance.

---

## 2. The threads you now own

| Thread | Name | Job | Cadence |
|---|---|---|---|
| legs | `legs_thread` | pop one 8-angle frame, `servo_move` it | as fast as moves allow |
| head | `head_thread` | pop one 3-angle frame, clamp, `+45` pitch, move | same |
| tail | `tail_thread` | pop one angle frame, move | same |
| rgb | `rgb_strip_thread` | `rgb_strip.show()` forever | continuous |
| imu | `imu_thread` | read SH3001, apply offsets, compute pitch/roll | 20 Hz (`sleep 0.05`) |
| sensory | `sensory_thread` | read ultrasonic into `distance` | `sleep 0.01` between reads; real cadence is bounded by the sensor (see `PIDOG-SENSORS.md` §5) |

All are daemon threads created in the constructor. Everything is shared mutable state with a
lock per buffer — which is workable but means **you must not call movement methods from several
threads at once**; the lock protects the list, not the sequence (`PATTERNS.md` §2).

Two consequences:

- The RGB thread calls `show()` in a tight loop with no sleep, so the LED board costs a constant
  slice of the single I2C bus for the life of the process. It is the main source of bus
  contention on a hot loop.
- The IMU thread never stops reading, even if you never look at `dog.pitch`.

---

## 3. Lifecycle

### 3.1 `stop_and_lie(speed=85)`

Stops all three buffers, then lies down, centres the head (raw `[0,0,0]`) and centres the tail,
waiting for each. This is the "put the dog down" primitive.

### 3.2 `close()`

Installs a `SIGINT` handler, arms a 5-second `SIGALRM` as a watchdog, then:

1. restarts the action threads if they had exited,
2. `stop_and_lie()`,
3. sets the exit flag,
4. closes the touch pads, the sound-direction sensor and the ultrasonic,
5. joins the legs/head/tail threads, stops and joins the RGB thread, joins the IMU thread,
6. stops the sensory thread with a 1 s timeout.

Everything is inside one `try/except` that logs `Close error: …` — so a failure halfway leaves
some threads running and the process alive.

```python
try:
    ...                      # your program
finally:
    dog.close()              # always: it is what returns the dog to a safe pose
```

`SIGALRM` does not exist on Windows, but `pidog` only runs on a Pi, so that is fine there and
irrelevant here.

### 3.3 Why `close()` is not optional


---

## 4. Moving a part

Three methods, one shape: `(targets, immediately=True, speed=50)`. `targets` is a **list of
frames**; each frame is one servo write.

### 4.1 `head_move` — yaw/roll/pitch, and the cross-mix

```python
dog.head_move([[yaw, roll, pitch]], roll_comp=0, pitch_comp=0, immediately=True, speed=50)
```

Each frame is `[yaw, roll, pitch]` in degrees, converted before it is queued:

```
ratio       = abs(yaw) / 90
pitch_servo = roll * ratio        + pitch * (1 - ratio) + pitch_comp
roll_servo  = -(sign(yaw) * (roll * (1 - ratio) + pitch * ratio) + roll_comp)
yaw_servo   = yaw
```

Read that twice. At yaw 0 it behaves as you expect (`pitch` → pitch servo, `roll` → roll servo).
As yaw approaches ±90 the two channels **blend into each other**, because two of the three head
servos are mounted such that a "level head" at 90° of yaw is a different pair of angles. This is
deliberate. It also means a head pose cannot be reasoned about one axis at a time.

Then, in the head thread, before the write:

- yaw is clamped to ±90, roll to ±70, pitch to −45…+30;
- `HEAD_PITCH_OFFSET` (45) is added to the pitch channel.

`head_move_raw(targets, immediately=True, speed=50)` skips the conversion but **still** gets the
clamp and the `+45`. It is raw *angles*, not raw *PWM*.

```python
dog.head_move([[30, 0, 0]], speed=70)        # look left, level
dog.head_move([[0, 0, -20]], speed=70)       # look down 20°
dog.head_move([[0, 25, 10]], speed=60)       # tilt right and up a little
```

### 4.2 `legs_move` — and `immediately`

```python
dog.legs_move(frames, immediately=True, speed=50)     # frames: list of 8-angle lists
```

`immediately=True` **cancels what is queued** (`legs_stop()` clears the buffer and waits for the
current frame to finish) and then appends. `immediately=False` appends behind it.

```python
dog.legs_move([lie_pose], speed=60)                     # now
dog.legs_move([stand_frames[0]], speed=60)              # stand, cancelling anything queued
dog.legs_move(more_frames, immediately=False)            # queue behind the current frame
```

So a multi-frame motion is written as `do_action(name, step_count=n)`, or by passing a list of
frames. The buffer is a plain list per part; there is no depth limit, so
`legs_move(frames * 100)` queues 10 000 frames of motion with no way to inspect or trim it
except `legs_stop()`.

### 4.3 `tail_move`

```python
dog.tail_move([[angle]], immediately=True, speed=50)
```

One servo, so each frame is a one-element list. Range is the servo's ±90, not a dog-specific
limit.

### 4.4 Speed is per part, not per frame — the queue gotcha

`legs_move` sets `self.legs_speed = speed` and *then* appends. The worker reads
`self.legs_speed` at execution time, not at queue time. So:

```python
dog.legs_move(frames_a, immediately=False, speed=20)   # queued slowly
dog.legs_move(frames_b, immediately=False, speed=95)   # queued fast
# every frame, including frames_a, now runs at 95
```

If a gait needs mixed speeds, split it into separate calls and wait in between.

### 4.5 `legs_simple_move` — bypass the thread

```python
dog.legs_simple_move(angles, speed=90)
```

Adds the servo offsets and writes the eight angles directly, then sleeps for a delay derived
from `speed` (5–50 ms). No buffer, no interpolation, no `max_dps` guard. It is the "I know what I
am doing, give me the raw write" path — and it races the legs thread if that thread is running,
which it always is. Only use it when the buffer is empty and the thread is idle.

### 4.6 `do_action` — the named path

```python
dog.do_action('sit', step_count=1, speed=70, pitch_comp=0)
```

Looks the name up in the action dictionary, then pushes `step_count` copies of every frame into
the right buffer (legs, head or tail). Details and the full name list are in
`PIDOG-ACTIONS.md` §2–§3.

---

## 5. Waiting, cancelling, polling

| Method | Effect |
|---|---|
| `wait_legs_done()` / `wait_head_done()` / `wait_tail_done()` | busy-wait at 1 kHz until that buffer is empty |
| `wait_all_done()` | the three, in order |
| `is_legs_done()` / `is_head_done()` / `is_tail_done()` / `is_all_done()` | `True` when the buffer is empty |
| `legs_stop()` / `head_stop()` / `tail_stop()` | clear that buffer, then wait |
| `body_stop()` | all three |

Three things to understand:

1. **"Done" means "buffer is empty"**, not "the servo has arrived". The worker pops the frame
   *before* calling `servo_move`, so a `wait_*_done()` that returns may still have one frame in
   flight inside `servo_move`. On a slow bus that is tens of milliseconds of unmodelled motion.
2. Waiting is a 1 ms poll loop, not an event. `wait_all_done()` on the main thread is fine;
   calling it from the callback of a `UserButton` or an audio thread burns CPU for nothing.
3. `*_stop()` blocks until the in-flight frame completes, so a "stop" from a safety path can take
   a full frame time (up to ~1 s at `speed=0`). If you need an immediate halt, you need a
   different mechanism than clearing a buffer.

---

## 6. Body pose and kinematics

This is what makes the PiDog more than twelve servos: describe where the body should sit and
where each foot should land, and the library solves the angles.

### 6.1 The coordinate model

Each leg is a two-link arm (`LEG` 42 mm + `FOOT` 76 mm) hanging from a shoulder. A foot position
is a pair `(y, z)` in millimetres relative to that shoulder: `y` is the lateral/forward offset,
`z` is height. 95 mm is the standing reference used by the `stand` action.

```python
dog.set_legs([[0, 0], [0, 0], [0, 0], [0, 0]])       # four (y, z) foot positions
dog.set_pose(x=0, y=0, z=80)                          # body translation, mm
dog.set_rpy(roll=0, pitch=0, yaw=0)                   # body orientation, degrees
angles = dog.pose2legs_angle()                        # 8 servo angles
dog.legs_move([angles], speed=60)
```

`set_rpy(..., pid=True)` fuses the IMU: it adds a proportional offset derived from
`target_rpy - (pitch, roll)`. `KP` is 0.033 and `KI`/`KD` are 0 — a P controller with a fixed
gain. The balance examples call it in a loop, once per cycle.

### 6.2 What each function does

| Function | Input | Output |
|---|---|---|
| `set_legs(list)` | 4 × `(y, z)` foot offsets | builds `legpoint_struc`; **required before `pose2coords`** |
| `set_pose(x, y, z)` | mm, body frame | stores the target translation |
| `set_rpy(roll, pitch, yaw, pid=False)` | degrees | stores the target orientation (radians) |
| `pose2coords()` | — | `{"leg": [...], "body": [...]}`, four entries each |
| `pose2legs_angle()` | — | 8 servo angles for the current pose |
| `coord2polar((y, z))` | one foot | `(alpha, beta)` = leg angle, foot angle |
| `fieldcoord2polar((y, z))` | one foot, pose-aware | same, with body pitch folded in |
| `legs_angle_calculation(coords)` | 4 × `(y, z)` | the 8-angle list, with the right-side sign flip |
| `limit(lo, hi, x)` | — | clamp helper |

`coord2polar` is the law of cosines with the arccosine clamped to [−1, 1]: an unreachable foot
target produces a clamped angle instead of a `math domain error`. It does **not** report that the
target was unreachable — the leg simply stops where the kinematics allow.

### 6.3 The gait generators

`Walk(fb, lr)` and `Trot(fb, lr)` are coordinate generators used by `ActionDict`, not `Pidog`
methods. Each produces frames of four `(y, z)` pairs, which `legs_angle_calculation` converts.

| Generator | Sections | Steps/section | Raise order | Stride | Body offset |
|---|---|---|---|---|---|
| `Walk` | 8 | 6 | `1, 0, 4, 0, 2, 0, 3, 0` | 80 mm | −15 mm |
| `Trot` | 2 | 3 | `[1, 4]`, `[2, 3]` (diagonal pairs) | 100 mm | −17 mm |

`Walk` raises one leg at a time with a pause between — slow and stable. `Trot` raises diagonal
pairs together — faster, with more body sway. `fb` is `FORWARD` (1) / `BACKWARD` (−1); `lr` is
`LEFT` (−1) / `STRAIGHT` (0) / `RIGHT` (1), and note that **`LEFT` is the negative one**.

`TURNING_RATE` (0.3 for walk, 0.5 for trot) scales the stride of the inside legs, which is what
turns "walk" into "turn".

---

## 7. Known defects in the motion path

Verified by reading the pinned commit. None of these are documented upstream, and each one
changes what you are allowed to call.

### 7.1 `set_angle()` is unusable

```python
def set_angle(self, angles_list, speed=50, israise=False):
    for angles in angles_list:
        result, angles = self.limit_angle(angles)      # AttributeError
```

`Pidog` defines `limit(min, max, x)`, never `limit_angle`. The function also reads
`self.coord_temp`, and its fallback calls `polar2coord`, which uses `self.A`, `self.B` and
`self.C` — none of which are assigned anywhere in the package. Every call raises `AttributeError`
on the first line of the loop.

**Use `legs_move(legs_angle_calculation(coords))` instead.** That is the working path, and it is
what the action dictionary uses.

### 7.2 `pose2coords()` needs `set_legs()` first

`legpoint_struc` is created only by `set_legs()`. Calling `pose2coords()` or
`pose2legs_angle()` on a fresh `Pidog` raises `AttributeError: legpoint_struc`.

### 7.3 There is no `read_touch`, `read_sound_direction` or `read_imu`

Sensor access is by **attribute**: `dog.dual_touch.read()`, `dog.ears.read()`, `dog.accData`,
`dog.gyroData`, `dog.pitch`, `dog.roll`. See §8.

### 7.4 `read_distance()` returns −1.0 until the sensor has been read once

`self.distance` is a `multiprocessing.Value('f', -1.0)` filled by the sensory thread. Right after
construction it is still −1.0, and it stays −1.0 forever if the ultrasonic failed to initialise
(that failure raises inside the thread and leaves `dog.ultrasonic` absent).


### 7.5 A typo in an action name is silent

`do_action` catches `KeyError` **and** `Exception`, then prints a coloured error line to stdout.
No exception reaches the caller, so `do_action('sitt')` does nothing and the program continues as
though the dog had moved.

### 7.6 `compare_version` is broken, and the dead branch would recurse

```python
return (or_v >= or_v)      # compares the left side with itself: always True
...
else:
    def numpy_mat(data):
        return numpy_mat(data)      # infinite recursion, unreachable
```

Because it always returns `True`, `numpy_mat` is always `np.asmatrix`. The numpy<2 branch would
recurse forever, but nothing can reach it. Do not "fix" this without confirming that
`np.asmatrix` still exists on the numpy you are running.

### 7.7 `legs_switch()` does nothing

It sets `self.legs_sw_flag`, which no other line in the package reads. Vestigial — do not build a
gait interlock on it.

---

## 8. Sensor attributes on the dog object

Read through these; do not reach into `robot_hat` to get to them. Behaviour is in
`PIDOG-SENSORS.md`.

| Attribute | Type | Source |
|---|---|---|
| `dog.read_distance()` | method → cm float, −1 sentinel | cached ultrasonic thread value |
| `dog.ultrasonic` | `Ultrasonic`, or absent | created inside the sensory thread |
| `dog.dual_touch` | `DualTouch`, `.read()` → `'N' 'L' 'R' 'LS' 'RS'` | GPIO D2/D3 |
| `dog.ears` | `SoundDirection`, `.isdetected()` / `.read()` | SPI + GPIO 6 |
| `dog.imu` | `Sh3001` | I2C 0x36 |
| `dog.accData`, `dog.gyroData` | `[x, y, z]` int LSB, offset-corrected | IMU thread, 20 Hz |
| `dog.pitch`, `dog.roll` | degrees | computed in the IMU thread |
| `dog.rgb_strip` | `RGBStrip`, 11 pixels | I2C 0x74 |
| `dog.music` | `Music` | audio |
| `dog.touch` | `'N'` — **never updated** | assigned once in the constructor |

`dog.touch` is a trap: it is set to `'N'` at construction and nothing writes it again. Read
`dog.dual_touch.read()` for the live value.

---

## Used by HoundMind

| Vendor call | Where |
|---|---|
| `Pidog()` construction | `src/houndmind_ai/hal/vendor.py` → `_ensure_dog` |
| `do_action` / `head_move` / `wait_all_done` | `hal/vendor.py` → `_direct`, `_head` |
| `legs_stop` / `head_stop` / `tail_stop` | `hal/vendor.py` → `_stop_locked` |
| `close()` | `hal/vendor.py` → `close` |
| camera-free motion tests | `hal/fake.py::FakeDogHAL` implements `DogHAL` without any of this |
