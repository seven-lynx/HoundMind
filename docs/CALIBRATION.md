# Calibration — making the dog's body match its idea of itself

Status: **guide** — what each calibration measures, which command runs it, and what is never automated.
Pairs with: [`TOOLS.md`](TOOLS.md) (every flag), [`HARDWARE_TEST.md`](HARDWARE_TEST.md) (where in the
device ladder it happens), the `calibration` section of [`FEATURES_GUIDE.md`](FEATURES_GUIDE.md)

Calibration used to be a paragraph in three different files and a page of its own nowhere. There are
four measurements, four commands, and one rule that covers all of them:

> **Calibration moves servos and writes user data. It is never run for you** — not by an install
> script, not by a test, not by an agent. The runtime reads the saved values; only a person at the
> keyboard changes them.

## The four measurements

| What is wrong | Command | What it writes | Notes |
|---|---|---|---|
| The legs do not stand square | `python -m tools.calibrate_servos` | `calibration.servo_zero_offsets` in `settings.jsonc` (per-joint trim) | Read-only without `--interactive`: it prints the twelve joints and the saved trim. Each keypress in `--interactive` re-poses the dog (#263) |
| One joint is a few degrees out | `python -m tools.servo_level --apply` | the same offsets, nudged | Each pass nudges all eight leg joints twice. Without `--apply` it only reads |
| "Which way is down" is wrong | `python -m tools.imu_calibrate --apply` | the IMU offsets the orientation module reads | The accelerometer magnitude must read ~1.00 g at rest afterward; `tools.hardware_checkup --skip-motion` prints the line |
| The stride is not 25 cm | `python -m tools.step_calibrate` | `navigation.step_cm` (clamped, ±20 % per apply) | It walks toward a wall **by design**: `--confirm-clearance` is mandatory, `--stop-at` defaults to 45 cm, and every step passes the runtime's interlock |

A second stride measurement exists for a room the dog has already been shown:
`mapping/room_scale.py` ranges a wall, walks, ranges it again, and differences the two — no wall to
walk into. It is a library, not a command; the run that uses it is a plan segment, not a tool.

## Where the values live

- **Per-joint trim:** `calibration.servo_zero_offsets` in `config/settings.jsonc`, applied at start
  when `calibration.auto_apply_servo_offsets` is true. The vendor clamps a saved trim to ±20°
  (`hal/iface.py::SERVO_OFFSET_LIMIT_DEG`), and the HAL clamps first so the workflow never hands the
  vendor a value it will reject.
- **IMU offsets:** written by `imu_calibrate --apply`; the orientation module applies them as
  `orientation_bias_z` and reports `orientation_calibration_ok`.
- **Step length:** `navigation.step_cm` with `step_cm_source` — `assumed` until a measurement passes
  the gates (five samples within 10 % of each other), so a wrong measurement cannot silently become
  the map's scale.

Treat every one of these as **user data**: read it, never overwrite it, never invent a default. A
fresh install has none, and the dog stands where the hardware put it.

## The ladder

1. `python -m tools.calibrate_servos` — read-only pass first. Compare it with what you see.
2. `python -m tools.calibrate_servos --interactive` — only with the dog on a stand, clear of edges.
3. `python -m tools.imu_calibrate --apply`, then `python -m tools.hardware_checkup --skip-motion` and
   read the `imu_gravity` line.
4. `python -m tools.step_calibrate --confirm-clearance` — a corridor with a wall and 2 m of floor in
   front of the dog.
5. `python -m tools.smoke_test` — the loop and the sensors, still no gait.

Every step is a person watching a dog. Nothing here is a CI job, and nothing here runs because a
config said so.
