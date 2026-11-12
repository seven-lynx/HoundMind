# PiDog & RobotHAT — Hardware

Status: **reference** — physical layout, channel map, travel limits, power. Facts come from
`pidog/pidog.py` (class constants) and `robot_hat/device.py` (pin and HAT tables).
Version: v2026.01.18 • Author: 7Lynx
Verified against: `sunfounder/pidog@cee4bff`, `sunfounder/robot-hat@4556bd8` (2.5.x)
Pairs with: `INDEX.md` (router), `ROBOTHAT.md` (how to drive the channels)

---

## 1. What the machine is

A PiDog is a Raspberry Pi plus a Robot HAT plus twelve servos and five sensors.

| Part | Count | Driven by | Documented in |
|---|---|---|---|
| Leg servos | 8 | `Robot('legs')` → 8 × `Servo` | §2, `PIDOG-MOTION.md` §4 |
| Head servos (yaw, roll, pitch) | 3 | `Robot('head')` | §2 |
| Tail servo | 1 | `Robot('tail')` | §2 |
| Ultrasonic ranger | 1 | `Ultrasonic(Pin D1 trig, Pin D0 echo)` | `PIDOG-SENSORS.md` §1 |
| Dual touch pads | 2 | `DualTouch('D2', 'D3')` | `PIDOG-SENSORS.md` §2 |
| Sound-direction sensor | 1 | SPI0 + GPIO 6 busy | `PIDOG-SENSORS.md` §3 |
| 6-axis IMU (SH3001) | 1 | I2C 0x36 | `PIDOG-SENSORS.md` §4 |
| RGB board (11 LEDs) | 1 | I2C 0x74 | `PIDOG-EXPRESSION.md` §1 |
| Speaker (on the HAT) | 1 | I2S audio, one enable pin | `PIDOG-EXPRESSION.md` §2 |
| Camera | 0–1 | `vilib` / `picamera2`, not part of `pidog` | outside this set |

`Pidog()` builds all of it in one constructor. Two of the twelve servos' worth of detail matter
more than the rest: which channel is which joint, and how far each may travel.

---

## 2. Servo channels and pins

`Pidog.__init__` passes three pin lists to three `Robot` objects. The numbers are **PWM
channels** (`P0`…`P11`), not GPIO numbers — `Servo(channel)` on the HAT's MCU owns them.

| `Robot` | Pin list (channel order) | Purpose |
|---|---|---|
| `legs` | `[2, 3, 7, 8, 0, 1, 10, 11]` | 8 leg joints, two per leg |
| `head` | `[4, 6, 5]` | yaw, roll, pitch — **in that order** |
| `tail` | `[9]` | one joint |

The ASCII map in the vendor source, reproduced because the numbers are not in reading order:

```
                     P4  (yaw)
                   P5, 'P6'        P6 = roll, P5 = pitch
                      |
              P3,P2 --[ ]-- P7,P8
                      [ ]
              P1,P0 --[ ]-- P10,P11
                      |
                   'P9'   (tail)
```

### 2.1 The eight leg angles, in order

An 8-element leg command is read positionally. Index → channel → joint:

| Index | Channel | Joint | Sign on the right side |
|---|---|---|---|
| 0 | P2 | left-front shoulder | — |
| 1 | P3 | left-front leg | — |
| 2 | P7 | right-front shoulder | mirrored |
| 3 | P8 | right-front leg | mirrored |
| 4 | P0 | left-hind shoulder | — |
| 5 | P1 | left-hind leg | — |
| 6 | P10 | right-hind shoulder | mirrored |
| 7 | P11 | right-hind leg | mirrored |

"Mirrored" is not a guess: `legs_angle_calculation` negates both angles of every odd-indexed
leg (`i % 2 != 0`), which is why a symmetric pose such as `lie` is
`[45, -45, -45, 45, 45, -45, -45, 45]` — the right legs carry the opposite sign of the left.

The vendor's own comment names both servos of a leg "left front leg". The convention in the
examples — and in `docs/PIDOG_PROGRAMMING_GUIDE.md` — is to call the first of each pair the
*shoulder* (it lifts) and the second the *leg* (it swings). Keep that naming: what a command
actually depends on is the pair order.

So a hand-written leg command looks like this, and the four pairs are front-left, front-right,
hind-left, hind-right:

```python
# lie: all four legs folded, written out with the sign pattern made explicit
dog.legs_move([[45, -45, -45, 45, 45, -45, -45, 45]], speed=60)
```

### 2.2 Head ordering is a trap

`head_move` takes `[yaw, roll, pitch]`. Many humans write pitch first because that is the axis
they think in. The vendor converts internally in `head_rpy_to_angle`, and past yaw ≈ ±45° the
roll and pitch channels start to mix by design (see `PIDOG-MOTION.md` §4.1).

---

## 3. Limits, speeds and geometry

### 3.1 Travel limits

| Joint | Min | Max | Where enforced |
|---|---|---|---|
| Head yaw | −90 | +90 | clamped per move, in the head worker thread |
| Head roll | −70 | +70 | same |
| Head pitch | −45 | +30 | same, then `+45` offset applied |
| Tail | −90 | +90 | by `Servo` only |
| Leg joints | −90 | +90 | by `Servo` only |
| Any `Servo` | −90 | +90 | `Servo.angle()` clamps silently |

Two consequences worth internalising:

1. **A head pitch of 0° is not the servo at 0°.** The worker adds `HEAD_PITCH_OFFSET = 45`
   before writing the channel, so the mechanical centre is `+45` on that servo.
2. **Nothing warns you.** Out-of-range head values are clamped, not rejected, so a pose that
   looks wrong is more often a value that was silently limited than a broken servo. The leg
   path is different: it can raise — see `PIDOG-MOTION.md` §7.

### 3.2 Speed constants (degrees per second)

| Constant | Value | Applied to |
|---|---|---|
| `HEAD_DPS` | 300 | `self.head.max_dps` |
| `LEGS_DPS` | 428 | `self.legs.max_dps` |
| `TAIL_DPS` | 500 | `self.tail.max_dps` |

`Robot.max_dps` defaults to 428 and is how a `speed` of 0–100 becomes a duration: the requested
duration is computed first, then lengthened if it would exceed the cap. The formula is in
`ROBOTHAT.md` §5.3 — read it before assuming `speed=100` is "as fast as possible".

### 3.3 Structure

| Constant | Value (mm) | Meaning |
|---|---|---|
| `LEG` | 42 | upper leg segment |
| `FOOT` | 76 | lower leg segment |
| `BODY_LENGTH` | 117 | front-to-back spacing of the shoulders |
| `BODY_WIDTH` | 98 | left-to-right spacing |
| `body_height` | 80 | default stance height, settable |

These four numbers are the whole kinematic model. `BODY_STRUCT` is the 3×4 matrix of shoulder
positions in body coordinates; `legpoint_struc` is the same matrix shifted by
`set_legs()` — and `pose2coords()` fails until `set_legs()` has been called once. See
`PIDOG-MOTION.md` §6.

---

## 4. Power

| Item | Value |
|---|---|
| HAT input | 6.0–8.4 V, XH2.54 3-pin, two power LEDs |
| ADC | 12-bit, 0–4095 counts, 3.3 V reference |
| Battery sense | `ADC('A4')` voltage × 3 (the divider on the HAT) |
| API | `dog.get_battery_voltage()` → volts, rounded to 2 dp |

```python
volts = dog.get_battery_voltage()   # e.g. 7.62
```

`utils.get_battery_voltage()` still works but is a deprecated shim that emits a
`DeprecationWarning` and forwards to the same code (`ROBOTHAT.md` §11.3).

A low battery is not a sensor reading you can trust to be steady: servos under load sag the
rail, and every one of the twelve is a current spike. If you build a battery guard, hold a
minimum and debounce it over several seconds rather than reacting to one sample.

---

## 5. Bus addresses and GPIO

### 5.1 I2C (bus 1)

| Address | Device | Object |
|---|---|---|
| 0x14 | HAT MCU (ADC, PWM, firmware version) | `ADC`, `PWM`, `Servo`, `Motor` |
| 0x15 | HAT MCU, second address | same classes, probed first-match |
| 0x16 | HAT MCU, third PWM address | `PWM` only |
| 0x36 | SH3001 IMU | `Sh3001` |
| 0x53 | ADXL345 (optional module, not on the dog) | `ADXL345` |
| 0x74 | SLED1735 LED driver, 11 pixels | `RGBStrip` |

Firmware version lives in register `0x05` of 0x14/0x15, three bytes
(`robot_hat.get_firmware_version()`).

### 5.2 Header pins used by the dog

The `PIN` table maps the silkscreen names to BCM GPIO numbers. Only these matter for a PiDog:

| Silkscreen | GPIO | Used for |
|---|---|---|
| `D0` | 17 | ultrasonic **echo** |
| `D1` | 4 | ultrasonic **trig** |
| `D2` | 27 | left touch pad |
| `D3` | 22 | right touch pad |
| 6 | 6 | sound-direction /BUSY (raw number, not a `D` name) |
| `MCURST` | 5 | MCU reset line |
| `USER` / `SW` | 25 | HAT user button |
| `LED` | 26 | HAT user LED |
| `BOARD_TYPE` | 12 | HAT revision strap |

Echo on `D0` and trig on `D1` is the reverse of the order most examples show — `Pidog` builds
`Ultrasonic(Pin('D1'), Pin('D0'), timeout=0.017)`, i.e. `trig=D1, echo=D0`.

Full table (`robot_hat/device.py`): `D0`–`D16`, plus `SW`, `USER`, `LED`, `BOARD_TYPE`, `RST`,
`BLEINT`, `BLERST`, `MCURST`, `CE`.

---

## 6. What lives on disk

Servo trim and IMU calibration are **user data written by calibration runs**. Read them; never
invent or overwrite them (`calibration/servo_calibration.py` owns the HoundMind side).

| File | Owner | Keys |
|---|---|---|
| `~/.config/pidog/pidog.conf` | `Pidog`, `Sh3001` | `legs_servo_offset_list`, `head_servo_offset_list`, `tail_servo_offset_list`, `imu_acc_offset`, `imu_gyro_offset`, `calibrate_bias_list`, `calibrate_scale_list`, `calibrate_gyro_bias_list`, `calibrate_gyro_scale_list` |
| `~/.config/robot-hat/robot-hat.conf` | `Robot` default | same `*_servo_offset_list` naming |
| `/opt/robot_hat/default_motors.config` | `Motors` | `left`, `right`, `left_reverse`, `right_reverse` |

Format is `name = value` lines, one per key, `#` comments ignored (`robot_hat/filedb.py`).

Three details that surprise people:

- The path is resolved from `SUDO_USER`/`$LOGNAME` via `getent passwd`. Run the same script as
  `pi` and as `sudo` and you read **two different calibration files**. Pick one and stay with it.
- `fileDB` applies `chmod`/`chown` through `os.popen('sudo chmod …')`, so a write under a
  non-root user only sticks if passwordless sudo is available.
- Servo offsets are clamped to ±20° when saved (`Robot.set_offset`), so a wildly wrong
  calibration cannot be stored even if the workflow computes it.

---

## 7. HAT revisions, Pi models and the GPIO chip

### 7.1 Revision detection

`robot_hat.device.Devices` reads `/proc/device-tree/hat/*` and matches the UUID against a
known list. Two revisions are described:

| Profile | UUID | Speaker enable pin | Motor drive mode |
|---|---|---|---|
| `robot_hat_v4x` | none recorded | GPIO 20 | 1 (TC1508S: PWM + direction) |
| `robot_hat_v5x` | `9daeea78-…-582369ac3e02` | GPIO 12 | 2 (TC618S: PWM + PWM) |

`Motor` and `Motors` silently select the mode from this table, which is why motor code written
for one board can spin backwards or not at all on the other. `robot_hat doctor` prints what was
detected.

### 7.2 The GPIO chip number moves

On Pi 5 the RP1 GPIO block has been `gpiochip4`, then `gpiochip0`, then something else again.
`pin.py` therefore resolves the chip by device-tree driver/label rather than a hard-coded index,
and honours `ROBOT_HAT_GPIOCHIP` (or `RPI_LGPIO_CHIP`) to force one. If GPIO access fails on a
fresh image, set that variable before rewriting any code.

### 7.3 Pi model compatibility

PiDog ships in two hardware versions. The standard version is **not** Pi 5 compatible (servo
and HAT driver differences); the V2 version covers Pi 3B+/4B/5 and Zero 2W. This matters when a
`speed` that was fine on a Pi 4 stutters on a Pi 5 because the I2C bus is shared with more
traffic — performance evidence from one model does not transfer (`pi-performance`).

---

## 8. What this file does not cover

- The camera and the `vilib`/`picamera2` stack — HoundMind wraps it in
  `src/houndmind_ai/optional/vision_pi4.py`, and it is not part of `pidog`.
- The I2S speaker wiring (`i2samp.sh`) — an install-time step, see `docs/INSTALL.md`.
- Anything you must measure rather than read: real step length, how much the body sags under
  load, whether a 20 g servo buzzes at a given angle. Those are device experiments.
