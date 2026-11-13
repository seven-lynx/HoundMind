# PiDog & RobotHAT — Index

Status: **index** — the router for `docs/pidog/`. Navigation only; every fact lives in a
numbered section of the file this page sends you to.
Verified against: `sunfounder/pidog@cee4bff` and `sunfounder/robot-hat@4556bd8` (branch
`2.5.x`) — read from the source, not from the rendered docs site.
Pairs with: `docs/PIDOG_PROGRAMMING_GUIDE.md` (the beginner tutorial — start there if you have
never driven a servo), `docs/HOUNDMIND_PROGRAMMING_GUIDE.md` (writing modules instead of
scripts), `src/houndmind_ai/hal/vendor.py` (the only file in this repo that imports `pidog`)

Nine files, one job each. Find your task in the router below, open **one** file, read **one**
section. This set is a reference, not a course.

---

## Scope and evidence

Everything here was derived by **reading the vendor source at the two commits above**. That is
a claim about code, not about a dog on a bench. Where behaviour depends on hardware — how far
`legs_move` actually travels, whether the IMU auto-calibration converges, what the ultrasonic
returns on carpet — this set says so instead of guessing. Treat unmarked statements as
"the source says", and anything about a physical outcome as a hypothesis until it is observed
on the Pi.

Version warning: this documents `robot-hat` **2.5.x**. `docs/INSTALL.md` currently clones
`robot-hat` **v2.0**, whose `robot_hat` package exposes a different, smaller surface. If
`from robot_hat import Servo` fails or a signature here does not match the installed file, check
`pip show robot-hat` before trusting this set — and see `ROBOTHAT.md` §1.3.

---

## Task router

| I want to… | Read |
|---|---|
| Know which PWM channel / pin drives which joint | `HARDWARE.md` §2 |
| Know the travel limits of the head, tail or a leg | `HARDWARE.md` §3 |
| Understand how a `speed` value becomes degrees per second | `ROBOTHAT.md` §5.3 |
| Stop a servo from resetting because of a shared timer | `ROBOTHAT.md` §4.4 |
| Use a GPIO, read an ADC channel, or scan the I2C bus | `ROBOTHAT.md` §2, §3, §6 |
| Drive the two wheel motors rather than the legs | `ROBOTHAT.md` §7 |
| Read the battery voltage or toggle the speaker output | `ROBOTHAT.md` §8 |
| Play a sound effect, a tune, or queue speech | `PIDOG-EXPRESSION.md` §2–§4 |
| Set an LED colour or an LED animation style | `PIDOG-EXPRESSION.md` §1 |
| Move the legs, head or tail from my own code | `PIDOG-MOTION.md` §4 |
| Move the body (stand height, pitch, roll, yaw) | `PIDOG-MOTION.md` §6 |
| Understand why `immediately=False` queues instead of moving | `PIDOG-MOTION.md` §4.2 |
| Wait for a movement to finish, or cancel one | `PIDOG-MOTION.md` §5 |
| Run a named action like `sit` or `wag_tail` | `PIDOG-ACTIONS.md` §2 |
| See every built-in action and what part it moves | `PIDOG-ACTIONS.md` §3 |
| Use `ActionFlow` to run actions on a background thread | `PIDOG-ACTIONS.md` §4 |
| Write my own multi-step routine | `PIDOG-ACTIONS.md` §5 |
| Read distance, touch, sound direction | `PIDOG-SENSORS.md` §1–§3 |
| Read the IMU raw, or in g and deg/s | `PIDOG-SENSORS.md` §4 |
| Decide whether a sensor reading is usable | `PIDOG-SENSORS.md` §6 |
| Structure a script that will not wedge the bus | `PATTERNS.md` §1 |
| Know which vendor quirks will bite me | `PATTERNS.md` §5 |
| Port vendor code into `hal/vendor.py` correctly | `PATTERNS.md` §7 |
| Look up an exact signature | `API-REFERENCE.md` |
| Clean up on exit without leaving the dog lying oddly | `PIDOG-MOTION.md` §3.3 |
| Calibrate servos or the IMU (destructive — needs clearance) | `HARDWARE.md` §6, `PIDOG-SENSORS.md` §4.5 |

---

## File map

| File | One job | Sections |
|---|---|---|
| `INDEX.md` | Routing and conventions | — |
| `HARDWARE.md` | Physical layout: servo indices, pins, geometry, limits, power, HAT revisions | 1–8 |
| `ROBOTHAT.md` | The `robot_hat` primitives: Pin, ADC, PWM, Servo, I2C, Robot, motors, devices, audio | 1–11 |
| `PIDOG-MOTION.md` | The `Pidog` object: lifecycle, leg/head/tail movement, kinematics | 1–8 |
| `PIDOG-ACTIONS.md` | The action catalogue and the `ActionFlow` state machine | 1–6 |
| `PIDOG-SENSORS.md` | Ultrasonic, dual touch, sound direction, IMU | 1–6 |
| `PIDOG-EXPRESSION.md` | LED strip, sound effects, music, TTS | 1–5 |
| `PATTERNS.md` | Safe structure, concurrency rules, quirks, migration to `DogHAL` | 1–8 |
| `API-REFERENCE.md` | Signature tables and upstream provenance | 1–4 |

---

## Units, ranges and sentinels

Vendor code mixes conventions freely. This is the table to check before passing a number.

| Quantity | Unit / range | Where |
|---|---|---|
| `Servo.angle()` | degrees, −90…+90, clamped silently | `ROBOTHAT.md` §4 |
| `speed` argument | 0–100, integer-ish, clamped | `ROBOTHAT.md` §5 |
| `*_DPS` constants | degrees per second (300 / 428 / 500) | `HARDWARE.md` §3 |
| `head_move` target | `[yaw, roll, pitch]` degrees, **not** `[pitch, roll, yaw]` | `PIDOG-MOTION.md` §4.1 |
| leg target angles | 8 values: two per leg, alternating sign on the right | `HARDWARE.md` §2 |
| body pose | millimetres, body frame, `body_height` default 80 | `PIDOG-MOTION.md` §6 |
| `read_distance()` | centimetres, **−1.0 means "no sample yet"** | `PIDOG-SENSORS.md` §1 |
| `Ultrasonic.read()` | centimetres, −1 timeout, −2 no pulse | `PIDOG-SENSORS.md` §1 |
| touch | `'N' 'L' 'R' 'LS' 'RS'` | `PIDOG-SENSORS.md` §2 |
| sound direction | degrees 0–359 in 20° steps, −1 none | `PIDOG-SENSORS.md` §3 |
| IMU raw | int16 LSB, 16384/g, 16.4/(deg/s) | `PIDOG-SENSORS.md` §4 |
| `Pidog.pitch` / `.roll` | degrees, computed in the IMU thread | `PIDOG-SENSORS.md` §4.4 |
| battery | volts, ADC ×3 divider | `ROBOTHAT.md` §8.1 |
| LED brightness | 0–1 float | `PIDOG-EXPRESSION.md` §1 |
| volume | 0–100 int | `PIDOG-EXPRESSION.md` §2 |

---

## The servo map in one block

```
                     P4  (head yaw)
                   P5, 'P6'          P6 = head roll, P5 = head pitch
                      |
              P3,P2 --[ ]-- P7,P8
                      [ ]
              P1,P0 --[ ]-- P10,P11
                      |
                   'P9'   (tail)
```

Eight leg channels in `DEFAULT_LEGS_PINS` order, which is also the order of the 8 angles a leg
command takes: `[P2, P3, P7, P8, P0, P1, P10, P11]`
= left-front shoulder, left-front leg, right-front shoulder, right-front leg,
left-hind shoulder, left-hind leg, right-hind shoulder, right-hind leg. Head is
`[P4 (yaw), P6 (roll), P5 (pitch)]`, tail is `[P9]`. Details in `HARDWARE.md` §2.

---

## Maintaining this set

- A claim that cannot be pointed at a vendor line or a HoundMind file does not belong here.
  Cite the upstream file and the section, not a line number that rots silently.
- When the pinned commits move, re-read the changed files and update the
  "Verified against" header on every file in the same change.
- A behaviour discovered on the device is worth a sentence here — mark it as observed, with
  the Pi model. That is the only way this set gets better than the source.
- `docs/README.md` lists this directory as one entry; a new file here needs a row in the file map
  above, not a second row there.
