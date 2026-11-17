# HoundMind Tools

Status: **reference** — every device CLI in `src/tools/`, its flags, and whether it can move the dog.
Pairs with: `docs/HARDWARE_TEST.md` (the order to run them in), `docs/LOGGING.md` (bundles),
`docs/QUICKSTART.md` (the four that matter on day one)

All of these run as `python -m tools.<name>` from the repo root after `pip install -e .`; from a bare
checkout use `PYTHONPATH=src python -m tools.<name>`.

## Contents

1. [Which tool, when](#1-which-tool-when)
2. [Motion risk](#2-motion-risk)
3. [`installer_verify`](#3-installer_verify)
4. [`hardware_checkup`](#4-hardware_checkup)
5. [`smoke_test`](#5-smoke_test)
6. [`camera_check`](#6-camera_check)
7. [`list_audio_devices`](#7-list_audio_devices)
8. [`collect_support_bundle`](#8-collect_support_bundle)
9. [`replay_decisions`](#9-replay_decisions)
10. [`download_opencv_models`](#10-download_opencv_models)
11. [`validate_rtabmap_adapter`](#11-validate_rtabmap_adapter)
12. [`calibrate_servos`](#12-calibrate_servos)
13. [`imu_calibrate`](#13-imu_calibrate)
14. [`servo_level`](#14-servo_level)

---

## 1. Which tool, when

| Question | Tool |
|---|---|
| Is this venv installed correctly? | `installer_verify` |
| Do the sensors answer? | `hardware_checkup --skip-motion` |
| Does the loop start and produce a scan and a map? | `smoke_test` |
| Is there a camera, and can it capture? | `camera_check` |
| Is there a microphone / speaker? | `list_audio_devices` |
| Does the dog know which way is down? | `imu_calibrate` |
| The dog sits crooked | `servo_level` |
| Something is broken and I need to file a report | `collect_support_bundle` |
| Why did the dog do that at 14:03? | `replay_decisions` |
| The semantic labeler has no model | `download_opencv_models` |
| Is the RTAB-Map adapter wired up? | `validate_rtabmap_adapter` |
| Which servo joint is leaning, and what trim is saved? | `calibrate_servos` |

## 2. Motion risk

| Tool | Can it move the dog? |
|---|---|
| `installer_verify` | no |
| `hardware_checkup` | **yes, unless `--skip-motion`** |
| `smoke_test` | **yes, only with `--include-motion`** |
| `camera_check`, `list_audio_devices`, `imu_calibrate`, `collect_support_bundle`, `replay_decisions`, `download_opencv_models`, `validate_rtabmap_adapter` | no |
| `calibrate_servos` | no — it reads and saves the trim. A legs write lands on the pose the dog already holds; the vendor's head and tail setters do re-pose as they save (#263) |
| `servo_level` | **yes, only with `--apply`** — it nudges each of the eight leg joints twice per pass |

No motion-capable tool moves the dog unless asked, but read the second row twice:
**leaving `--skip-motion` off `hardware_checkup` is a motion run.**

## 3. `installer_verify`

Proves the environment can import what the runtime imports.

```bash
python -m tools.installer_verify                 # lite preset (default)
python -m tools.installer_verify --preset full
```

| Flag | Meaning |
|---|---|
| `--preset {lite,full}` | which requirement set to check; `lite` by default |

Prints one line per package, ending in `Installer check: OK` and exit 0 — or `FAILED` with the single
`MISSING` line to fix. Its Python check is the range `pyproject.toml` declares, 3.11 to 3.13, so
`Python: 3.10 -> UNSUPPORTED` is a failure rather than a note: the next `pip install` would refuse
that interpreter (#111).

## 4. `hardware_checkup`

Reads each sensor once through the same `DogHAL` adapter the runtime uses (`PidogHAL`), then — unless
told not to — stands the dog, turns it both ways and sweeps its head.

```bash
python -m tools.hardware_checkup --skip-motion   # the only form that is safe by default
```

| Flag | Meaning |
|---|---|
| `--skip-motion` | read sensors only; no servo is commanded |
| `--pause <seconds>` | pause between steps (default `0.6`) |
| `--config <path>` | settings file other than `config/settings.jsonc`; its `sensors` block is what the HAL conditions readings with |

The reading lines end in `[checkup] valid:` (`distance=… touch=… sound=… imu=…`) and one verdict line:
`sensors: all answered`, or `no reading from: <names>`. A sensor that did not answer prints `None` for
its value and `False` in `valid:`, while a quiet room legitimately prints
`sound: detected=False dir=None`. When `sound=False`, a `[checkup] hint:` line follows: the vendor
swallows its own init exception, so the tool cannot name the cause and points at the one
`Sound sensor unavailable: …` warning in the log instead, which names the missing attribute and the
`pidog` revision it found (#183).

| Exit | Meaning |
|---|---|
| `0` | every sensor answered |
| `1` | at least one sensor did not answer — the `no reading from:` line names it ([#109](https://github.com/seven-lynx/HoundMind/issues/109)) |
| `2` | no dog could be opened: the vendor package is missing, or the HAL failed to start |

A motion step that fails is printed to stderr and does not change the code: the sensors are what this
exit status answers for.

## 5. `smoke_test`

Runs the real runtime for a fixed number of cycles with every module that can move the dog switched
off, and reports whether the HAL published a reading. A scan needs the head and `mapping` publishes
from a scan, so `scan_latest` and `mapping_openings` report `SKIPPED` in that mode; `--include-motion`
is where the sensor-to-scan-to-mapping chain is exercised, and it moves the dog.

```bash
python -m tools.smoke_test
python -m tools.smoke_test --cycles 20 --tick-hz 5
```

| Flag | Meaning |
|---|---|
| `--config <path>` | settings file other than `config/settings.jsonc` |
| `--cycles <n>` | runtime cycles to execute (default `20`) |
| `--tick-hz <n>` | tick rate for the run (default `5`) |
| `--include-motion` | allow navigation and motor actions — **moves the dog** |

A pass looks like `[smoke] PASS` - in the motionless mode that is a reading plus two `SKIPPED` lines,
by design.

## 6. `camera_check`

```bash
python -m tools.camera_check --list-devices --max-index 5
python -m tools.camera_check --index 0 --save frame.jpg
```

| Flag | Meaning |
|---|---|
| `--list-devices` | probe indices and report which ones open |
| `--max-index <n>` | highest index to probe (default `5`) |
| `--index <n>` | index to capture from (default `0`) |
| `--save <path>` | write one frame to this file |

The usual cause of "no frames" is a camera that is not enabled in `raspi-config`, or a backend
mismatch — `settings.vision_pi4.backend` ships `picamera2` with `opencv` as the fallback.

## 7. `list_audio_devices`

Lists the audio devices the sound stack can see. No flags.

```bash
python -m tools.list_audio_devices
```

If the list is empty, the I2S overlay is missing: run `sudo bash i2samp.sh` from the `pidog`
directory (`docs/INSTALL.md` [§3](INSTALL.md#3-install-sunfounder-pidog-libraries-into-the-same-python-environment)), or let the installer do it with `--run-i2samp`.

## 8. `collect_support_bundle`

```bash
python -m tools.collect_support_bundle                     # logs/support_bundle_<timestamp>.zip
python -m tools.collect_support_bundle /tmp/support.zip
```

Writes a zip holding `metadata.json` (timestamp, git commit, trace id), every file in `logs/` (long
ones as `.tail.txt`) and `config/settings.jsonc`. This is the shell-side bundle; the network-side one
is `GET /api/v1/support-bundle`, which carries live state instead of log files
(`docs/LOGGING.md` [§"Support bundle contents"](LOGGING.md#support-bundle-contents)).

## 9. `replay_decisions`

Replays a recorded decision log through a fake control plane — no dog, no motion. The way to answer
"why did it do that" without reproducing it.

```bash
python -m tools.replay_decisions logs/houndmind_decisions.jsonl --check
python -m tools.replay_decisions logs/houndmind_decisions.jsonl --speed 4
```

| Flag | Meaning |
|---|---|
| `path` | the `houndmind_decisions.jsonl` to replay (positional) |
| `--speed <x>` | playback speed; `0` means no waiting (default `1.0`) |
| `--limit <n>` | replay only the last N records (default `0`, all) |
| `--check` | validate and summarise, serve nothing |
| `--host`, `--port` | where to serve the fake plane |
| `--token-path <path>` | token file the client must present |
| `--linger <seconds>` | keep serving this long after the last record |

The decision JSONL is **off by default** (`decision_log_file_enabled: false`) — turn it on in
`config/settings.jsonc` before you need it, not after.

## 10. `download_opencv_models`

Fetches the SSD-MobileNet COCO model and labels the semantic labeler reads.

```bash
python -m tools.download_opencv_models
python -m tools.download_opencv_models --dest models
```

| Flag | Meaning |
|---|---|
| `--dest <dir>` | destination folder, relative to the repository root (default `models`) |

Writes `ssd_mobilenet_v1_coco.pb` (the TensorFlow frozen graph, taken out of the 77 MB
`ssd_mobilenet_v1_coco_2017_11_17` model-zoo tarball), `ssd_mobilenet_v1_coco.pbtxt` and
`coco_labels.txt` (the 90 COCO class names). Both raw URLs are pinned to OpenCV `4.10.0`, so a
rerun fetches the same files.

## 11. `validate_rtabmap_adapter`

Sends frames to the RTAB-Map adapter and reports whether it answers, without the rest of the runtime.

```bash
python -m tools.validate_rtabmap_adapter --image frame.jpg --count 5
python -m tools.validate_rtabmap_adapter --camera 0
```

| Flag | Meaning |
|---|---|
| `--camera <index>` | capture frames from this camera index |
| `--image <path>` | use one image file as the frame source |
| `--count <n>` | how many frames to send (default `5`) |

Requires RTAB-Map to be installed — see `scripts/install_rtabmap_pi4.md`. It does not move the dog.

## 12. `calibrate_servos`

Reads the servo trim the dog has loaded, shows the twelve joints, and — with an explicit flag — saves
a new one. This is the step every install needs before the dog stands straight, and it did not exist
in HoundMind; it used to be the vendor's interactive curses script (#142).

```bash
python -m tools.calibrate_servos                                  # read-only
python -m tools.calibrate_servos --set lf_shoulder=6 --set tail=-3  # dry run: prints, saves nothing
python -m tools.calibrate_servos --set lf_shoulder=6 --apply       # writes through DogHAL
```

| Flag | Meaning |
|---|---|
| `--set JOINT=DEG` | offset for one joint, repeatable; clamped to ±20 |
| `--apply` | save the result; **without it nothing is written** |

Output is one line per joint in the vendor's group order (`legs`, `head`, `tail`), with the current
value and the proposed one; a joint the HAL could not read prints `unread` rather than `0.0`, and is
never written, because saving its group would invent the other values in that list. A value past ±20
is clamped and the clamp is what gets saved. Exit codes: `0` saved or nothing to save, `1` a written
value did not read back (check the vendor log), `2` a usage error, no readable trim, or no dog.

There is no interactive preview on purpose: nudging a servo live needs a raw per-group angle write,
and that primitive belongs to `act/interlock.py` alone. Trim with `--set`, look at the numbers, then
`--apply`. The vendor's own script (`examples/0_calibration.py`) still exists and is documented in
`docs/pidog/HARDWARE.md` [§6](pidog/HARDWARE.md#6-what-lives-on-disk) for anyone who prefers it.

## 13. `imu_calibrate`

Measures the IMU's bias and scale by resting the dog on its six faces, then saves them through the
vendor's own setters. **It does not move the dog** — you rotate it, the tool samples.

```bash
python -m tools.imu_calibrate            # measure and print, save nothing
python -m tools.imu_calibrate --apply    # measure and save
python -m tools.imu_calibrate --reset    # drop the stored calibration
```

| Flag | Meaning |
|---|---|
| `--apply` | write what was measured; without it nothing is saved |
| `--reset` | clear the stored calibration back to the datasheet nominal |
| `--seconds`, `--samples` | sampling window per pose (default `2.0` s, `20` samples) |

**Why it matters.** An uncalibrated accelerometer reads `|acc| = 1.50 g` at rest where gravity is
1.00 g, and every angle derived from it — pitch, roll, the 45° tilt latch — carries the same offset.
The tool prints `|acc|` per pose and again after saving, and
`python -m tools.hardware_checkup --skip-motion` reports the same number as `imu_gravity` (#258).
On the bench dog `~/.config/pidog/pidog.conf` held **no** calibration at all, which is why this
exists (#259).

**The gyro gets a bias only.** A rate scale needs a known angular rate, which hand rotation cannot
supply; writing one anyway would be an unmeasured value of exactly the kind #258 was about.

Exit codes: `0` measured or reset, `1` the six poses did not cover all three axes, the IMU did not
answer, or the HAL refused the write, `2` a usage error.

## 14. `servo_level`

Finds the leg trim that makes the dog sit level, by measuring what each joint actually does to the
body. For every leg joint it nudges the joint by 2°, reads how far the body tipped on the IMU, nudges
it back, and solves the resulting 2×8 system for the trim that shoulders the tilt.

```bash
python -m tools.servo_level            # check the prerequisites, print the plan, move nothing
python -m tools.servo_level --apply    # probe the joints and save the trim
```

| Flag | Meaning |
|---|---|
| `--apply` | probe and save; **this is what makes it move** |
| `--iterations` | measure-and-trim passes (default `3`), stops early once level |
| `--probe-deg` | probe step per joint (default `2.0`) |
| `--target` | level enough, in degrees (default `1.0`) |
| `--max-trim` | refuse a solve bigger than this per joint (default `20.0` = the vendor limit) |

**Put the dog on a flat hard surface first**, in its resting pose, and keep clear of it: `--apply`
is a motion run of up to 48 nudges at speed 30.

Two prerequisites, both refused with a message rather than a guess:

- **A calibrated IMU** (`python -m tools.imu_calibrate --apply`). The tool trims servos to cancel a
  *body* tilt; against an uncalibrated accelerometer it would cancel the sensor's own offset and call
  it level. `|acc|` must read within 0.15 g of 1.00.
- **An existing trim** (`python -m tools.calibrate_servos`). A joint with no baseline cannot be merged
  into, and inventing the other seven would be user data nobody measured.

The solve is the minimum-norm solution, so a tilt is spread across the four shoulders and the four
knees instead of being dumped on one servo. A solve that wants more than 20° at any joint is refused:
that is a bent bracket or a stripped horn, not a calibration.

Exit codes: `0` done or dry, `1` a prerequisite failed, the IMU stopped answering, or the solve was
refused, `2` a usage error.

## Adding a tool

A new device CLI belongs in `src/tools/` as a module with a `main(argv: list[str] | None = None) ->
int` entry point, so `python -m tools.<name>` and a test can both call it. Anything that can move the
dog defaults to dry and requires an explicit flag — see `docs/HARDWARE_TEST.md` for why that rule is
not negotiable. A new tool needs a section on this page and a row in the table above in the same
change.

