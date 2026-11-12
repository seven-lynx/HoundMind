# PiDog & RobotHAT — Sensors

Status: **reference** — the four sensors, what a bad read looks like, and how much each read
costs. Every value here is a vendor return, not a HoundMind abstraction.
Version: v2026.01.18 • Author: 7Lynx
Verified against: `sunfounder/pidog@cee4bff`, `sunfounder/robot-hat@4556bd8` (2.5.x)
Pairs with: `PIDOG-MOTION.md` §8 (attribute list), `PATTERNS.md` §4 (validity discipline)

Sections: §1 ultrasonic · §2 dual touch · §3 sound direction · §4 IMU · §5 timing and cost ·
§6 validity rules

---

## 1. Ultrasonic ranging

`Pidog` builds it inside the sensory thread:

```python
Ultrasonic(Pin('D1'), Pin('D0'), timeout=0.017)    # trig, echo, seconds
```

### 1.1 The `Ultrasonic` class

```python
Ultrasonic(trig, echo, timeout=0.02)
Ultrasonic.SOUND_SPEED = 343.3      # m/s
```

| Call | Returns |
|---|---|
| `read(times=10)` | centimetres, or **−1** if every attempt timed out |
| `_read()` | one attempt: cm, or −1 timeout, or **−2** no pulse edge |
| `close()` | releases both pins |

`read()` retries internally up to `times` attempts and returns the first result that is not −1.
A −2 **is** returned as a result, because the retry only filters −1 — so callers can see −2.

`trig`/`echo` must be `Pin` objects; the constructor closes them and re-creates them by GPIO
number, with the echo pin forced to `IN` + `PULL_DOWN`.

### 1.2 Distance on the dog is cached, not live

```python
dog.read_distance()      # round(self.distance.value, 2)
```

`self.distance` is a `multiprocessing.Value('f', -1.0)` written by `_ultrasonic_thread` every
~10 ms (plus the read time). So `read_distance()` is a cheap read of the last sample — and it is
**−1.0 before the first sample**, which is every moment between `Pidog()` returning and the
sensor thread's first successful read.

```python
cm = dog.read_distance()
if cm <= 0:
    cm = None            # -1 = no sample yet, -2 = no echo
```

### 1.3 Range and accuracy

The timeout sets the maximum range: 0.017 s round trip is about **290 cm** at 343 m/s, and the
sensor's own floor is a few centimetres. Anything outside that is reported as a timeout, not as
"too far". Soft surfaces, angled walls and cloth absorb the pulse — a missed echo on a carpet is
normal and is *not* evidence of a fault.

Refresh the reading after moving the head: the transducer is mounted on the head, so
`read_distance()` describes the direction the head was pointing when the sample was taken. A
head scan needs a fresh sample after each move, not the cached one.

---

## 2. Dual touch

```python
DualTouch(sw1='D2', sw2='D3')
```

Both pins are inputs with pull-ups and read active-low.

| Return | Meaning |
|---|---|
| `'N'` | nothing touched |
| `'L'` | the `sw1` pad (`D2`) |
| `'R'` | the `sw2` pad (`D3`) |
| `'LS'` | left pad pressed within 0.5 s of a right press (a stroke rear→front) |
| `'RS'` | right pad pressed within 0.5 s of a left press (front→rear) |

`SLIDE_MAX_INTERVAL = 0.5` is the slide window. The class is a polled edge detector: it keeps
`last_touch` and `last_touch_time`, so **you must call `read()` often enough to catch a press**.
A 200 ms poll will miss a light tap; the pads are only debounced by the polling interval, there is
no interrupt path.

`dog.touch` exists but is never updated — read `dog.dual_touch.read()` (`PIDOG-MOTION.md` §8).

---

## 3. Sound direction

```python
SoundDirection(busy_pin=6)
```

An SPI device (`spidev` on bus 0, CS 0, 10 MHz) plus one GPIO for the busy line.

| Call | Returns |
|---|---|
| `isdetected()` | `True` while the module holds the busy line low |
| `read()` | degrees 0–359 in 20° steps, or **−1** if no direction is ready |
| `close()` | closes SPI and frees the pin |

The protocol is request/response: the module pulls busy low when it has a bearing, the Pi reads
six bytes and takes `bytes[4:]` as `(low, high)`. `read()` then calls `busy_reset()`, which
releases the pin, drives it high for 10 ms, and re-arms it as an input — that 10 ms is inside
every `read()` call.

Consequences:

- **`read()` is destructive and not thread-safe.** Two callers interleaving `busy_reset()` will
  corrupt each other. Call it from one place only.
- **It shares SPI0 CS0.** Any other device you add on that chip select will fight it.
- Accuracy is 20°, which is five positions per 100° — enough for "turn toward the noise", not for
  a precise bearing.

```python
if dog.ears.isdetected():
    bearing = dog.ears.read()      # -1, or 0..359
```


---

## 4. The IMU (SH3001)

I2C address `0x36`, six axes, configured at ±2 g and ±2000 °/s by `sh3001_init`. Two independent
calibrations exist and they are easy to confuse (§4.5).

### 4.1 Raw values

`dog.accData` and `dog.gyroData` are `[x, y, z]` **signed 16-bit counts**, refreshed by the IMU
thread at 20 Hz and corrected by `Pidog`'s additive offsets.

| Quantity | LSB per unit |
|---|---|
| acceleration | 16384 per g |
| angular rate | 16.4 per °/s |

Direct access, with the axis/quantity selectors:

```python
dog.imu.sh3001_getimudata('acc', 'xyz')     # [x, y, z] counts
dog.imu.sh3001_getimudata('gyro', 'z')      # one axis
dog.imu.sh3001_getimudata('all', 'xyz')     # (acc, gyro)
```

`_sh3001_getimudata()` (the raw 12-byte burst) returns `False` on any failure instead of raising.
`sh3001_getimudata` unpacks it and will raise `TypeError` when it gets that `False` — check the raw
call if you read directly.

### 4.2 Calibrated values in physical units

```python
data = dog.imu.get_calibrated_data()      # (acc_in_g, gyro_in_deg_per_s) or False
```

Each axis is corrected as `(raw - bias) / scale`. With no stored calibration the datasheet
nominals (16384, 16.4) are used, so this always works — it may just be inaccurate.

### 4.3 `dog.pitch` and `dog.roll`

Computed in the IMU thread from the accelerometer alone:

```python
ay = -acc[1]; az = -acc[2]
pitch = atan(ay / sqrt(ax*ax + az*az)) * 57.2958
roll  = atan(az / sqrt(ax*ax + ay*ay)) * 57.2958
```

Three things follow:

- These are **tilt** estimates, not attitude. There is no yaw and no gyro integration — the gyro
  is available but unused by this computation.
- `atan`, not `atan2`, so each angle is limited to ±90° and degrades near vertical.
- Both come from the same triplet, so a body that is pitched *and* rolled reports values that are
  not independent.

Good enough for "am I level?" and for a proportional balance loop — which is exactly how
`set_rpy(pid=True)` uses them. Not good enough for dead reckoning.

### 4.4 Temperature

```python
dog.imu.sh3001_gettempdata()      # °C
```


### 4.5 Two calibration systems — know which one you are writing

| System | Stored in | Keys | Applied to |
|---|---|---|---|
| `Pidog` additive offsets | `pidog.conf` | `imu_acc_offset`, `imu_gyro_offset` | `dog.accData`, `dog.gyroData`, `dog.pitch` |
| `Sh3001` bias + scale | `pidog.conf` | `calibrate_bias_list`, `calibrate_scale_list`, `calibrate_gyro_bias_list`, `calibrate_gyro_scale_list` | `get_calibrated_data()` only |

`Pidog`'s own calibration runs **once, at startup, and only when nothing is saved**:

```python
if not self.load_imu_offsets():
    # 10 samples at 0.1 s, assumes the dog is still and level
    imu_acc_offset[0] = round(-16384 - mean_ax, 0)
    ...
```

The first run on a new install therefore spends about a second assuming stillness. If the dog was
moving, those offsets are wrong — and they are **not** saved, so the next start repeats the
calibration. Only `set_imu_offsets` persists anything, and `load_imu_offsets` refuses values that
are not 3 long or that exceed 65536 in magnitude.

| Method | Effect |
|---|---|
| `dog.set_imu_offsets(acc_offset, gyro_offset)` | sets and **saves** |
| `dog.save_imu_offsets()` | saves what is currently in memory |
| `dog.load_imu_offsets()` | `True` if a saved calibration was applied |
| `dog.reset_imu_offsets()` | drops the saved values; next start auto-calibrates |
| `dog.imu.set_acc_calibration(bias, scale)` | writes the bias/scale pair and saves |
| `dog.imu.set_gyro_calibration(bias, scale)` | the same for the gyro |
| `dog.imu.reset_calibration()` | back to datasheet nominals |
| `dog.imu.calibrate('acc')` / `acc_calibrate_cmd()` | **interactive**: rotate 720° per axis |

The last row moves nothing but asks you to wave the dog around. Treat it as a device task with
clearance, and treat every row as a write to user data.

---

## 5. What a read costs

Reading is not free, and the costs differ by two orders of magnitude.

| Reading | Path | Typical cost | Notes |
|---|---|---|---|
| distance (cached) | attribute read | microseconds | no bus traffic, may be stale |
| distance (fresh) | `ultrasonic.read()` | 20–170 ms | up to 10 attempts × 17 ms timeout |
| touch | GPIO level | microseconds | two pins, no bus |
| sound direction | SPI + 10 ms busy reset | ≥ 10 ms | also resets the module's state |
| IMU (cached) | attribute read | microseconds | 50 ms cadence |
| IMU (fresh) | 12-byte I2C read | ~1 ms | shares the bus with the servos and the LEDs |
| battery | one ADC read | ~1 ms | `device.get_battery_voltage()` |
| LED board | 11 pixels, many writes | milliseconds | its own thread, continuously |

The ultrasonic retry loop is the one that matters: a single `read()` on carpet can occupy the
calling thread for 170 ms while it retries. Sample it from one place, with a median — which is
what HoundMind's HAL does.

---

## 6. Validity rules

### 6.1 Sentinels, per sensor

| Reading | Invalid when | Why |
|---|---|---|
| `dog.read_distance()` | `<= 0` | −1 = no sample yet / timeout, −2 = no pulse edge |
| `Ultrasonic.read()` | `<= 0` | the same two sentinels |
| `dog.ears.read()` | `< 0` | −1 means the module had no bearing |
| `dog.dual_touch.read()` | never | `'N'` is both "not touched" and "not read yet" |
| `dog.accData` / `gyroData` | no signal exists | values freeze silently if the IMU thread dies |
| `dog.pitch` / `dog.roll` | no signal exists | same |
| `get_calibrated_data()` | `is False` | the read failed |
| `dog.get_battery_voltage()` | `< 6.0` | below the pack floor: a flat pack or a bad read |

### 6.2 The rules that keep a reading honest

1. **Branch on validity before the value.** `distance_cm = 100` marked invalid must never be read
   as "clear at one metre" — that is how a dog walks into a wall with a working sensor.
2. **A frozen value is worse than a missing one.** `accData`, `pitch`, `roll` and `distance` all
   stop updating without any error if their thread exits (ten consecutive failures is enough).
   Timestamp what you act on.
3. **Never synthesise.** If a sensor is absent, say so; do not default to 0 or to a mid-range
   guess. `hal/iface.py::SensorSnapshot` exists to make that explicit — every value has a
   companion `*_valid` flag.
4. **Re-read after you move the head.** Distance is directional.
5. **Debounce anything physical.** One ultrasonic sample and one touch read are noise; require N
   consistent samples before acting. The HAL does the median and the EMA for you.

---

## Used by HoundMind

| Vendor call | Where |
|---|---|
| `dual_touch.read()` | `src/houndmind_ai/hal/vendor.py` → `_read_touch` (debounced) |
| `ears.isdetected()` / `ears.read()` | `hal/vendor.py` → `_read_sound` |
| `accData` / `gyroData` | `hal/vendor.py` → `_read_imu` (low-passed) |
| `read_distance()` / `ultrasonic.read_distance()` | `hal/vendor.py` → `_read_distance`, `sample_distance` |
| temperature, `get_calibrated_data()` | not used by the runtime today |
