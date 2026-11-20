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
15. [`audio_check`](#15-audio_check)
16. [`schema_export`](#16-schema_export)
17. [`bench_tick`](#17-bench_tick)
18. [`map_inspect`](#18-map_inspect)
19. [`step_calibrate`](#19-step_calibrate)
20. [`place_match`](#20-place_match)
21. [`camera_record`](#21-camera_record)
22. [`slam_replay`](#22-slam_replay)

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
| Did the speaker actually make a sound? | `audio_check --verify` |
| Something is broken and I need to file a report | `collect_support_bundle` |
| Why did the dog do that at 14:03? | `replay_decisions` |
| Does every client still read the same decisions? | `replay_decisions --corpus` |
| The semantic labeler has no model | `download_opencv_models` |
| Is the RTAB-Map adapter wired up? | `validate_rtabmap_adapter` |
| Which servo joint is leaning, and what trim is saved? | `calibrate_servos` |
| Is the loop spending its tick where I think it is? | `bench_tick` |
| What is actually inside `data/home_map.json`? | `map_inspect` |
| How far does one `forward` really carry the dog? | `step_calibrate --confirm-clearance` |
| Does the dog recognise a place from a camera frame? | `place_match <views-dir> <frames-dir>` |
| What does the camera actually see, frame by frame? | `camera_record` |
| Can that clip be replayed as recorded? | `slam_replay <clip> --verify` |

## 2. Motion risk

| Tool | Can it move the dog? |
|---|---|
| `installer_verify` | no |
| `hardware_checkup` | **yes, unless `--skip-motion`** |
| `smoke_test` | **yes, only with `--include-motion`** |
| `step_calibrate` | **yes, unless `--fake`** — it walks toward a wall by design. `--confirm-clearance` is mandatory, `--stop-at` defaults to 45 cm, and every step passes the runtime's interlock |
| `camera_check`, `list_audio_devices`, `imu_calibrate`, `audio_check`, `collect_support_bundle`, `replay_decisions`, `download_opencv_models`, `validate_rtabmap_adapter`, `bench_tick`, `map_inspect`, `place_match` | no |
| `camera_record`, `slam_replay` | no — both switch every motion-capable module off. `camera_record` needs the camera, never the legs; `slam_replay --host` runs a clip through the loop, not through the servos |
| `calibrate_servos` | **yes, with `--interactive`** — every keypress re-poses as it saves. Without that flag it only reads and saves: a legs write lands on the pose the dog already holds (#263) |
| `servo_level` | **yes, only with `--apply`** — it nudges each of the eight leg joints twice per pass |

No motion-capable tool moves the dog unless asked, but read the second row twice:
**leaving `--skip-motion` off `hardware_checkup` is a motion run.**

## 3. `installer_verify`

Proves the environment can import what the runtime imports — and, on a Pi, that the HAT speaker has a
route.

```bash
python -m tools.installer_verify                 # lite preset (default)
python -m tools.installer_verify --preset full
python -m tools.installer_verify --chain         # print the three post-install checks, in order
python -m tools.installer_verify --run-chain     # run them, stopping at the first failure
```

| Flag | Meaning |
|---|---|
| `--preset {lite,full}` | which requirement set to check; `lite` by default |
| `--chain` | print the three checks with their motion-safe flags; run none of them |
| `--run-chain` | run `installer_verify`, `hardware_checkup --skip-motion`, `smoke_test` in order |

Prints one line per package, ending in `Installer check: OK` and exit 0 — or `FAILED` with the single
`MISSING` line to fix. Its Python check is the range `pyproject.toml` declares, 3.11 to 3.13, so
`Python: 3.10 -> UNSUPPORTED` is a failure rather than a note: the next `pip install` would refuse
that interpreter (#111).

Three lines are not imports, and they exist because an install used to report green while the thing it
existed to check was broken:

| Line | Verdict | Why |
|---|---|---|
| `rtabmap-py: UNSUPPORTED` | not a failure | upstream ships no installable bindings, so `slam_pi4` stays off (#181) |
| `audio: not applicable` | not a failure | no Pi boot config: this is a workstation |
| `audio: WARN - dtoverlay=hifiberry-dac is absent` | not a failure | no overlay means no HAT speaker, which a dog without the voice stack does not need |
| `audio: MISSING - ... has no pcm.!default pointing at robothat` | **failure** | the overlay is on and nothing routes to the card; every engine constructs and says nothing (#288, #254) |

`--chain`/`--run-chain` exist so the flags that keep a post-install check motion-safe are not a thing
a human has to remember: `hardware_checkup` needs `--skip-motion`, and `smoke_test` moves nothing
without `--include-motion` (#315).

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
python -m tools.replay_decisions --corpus docs/fixtures/clients
```

| Flag | Meaning |
|---|---|
| `path` | the `houndmind_decisions.jsonl` to replay (positional; omit with `--corpus`) |
| `--corpus <dir>` | run the conformance corpus in that directory instead of one log |
| `--speed <x>` | playback speed; `0` means no waiting (default `1.0`) |
| `--limit <n>` | replay only the last N records (default `0`, all) |
| `--check` | validate and summarise, serve nothing |
| `--host`, `--port` | where to serve the fake plane |
| `--token-path <path>` | token file the client must present |
| `--linger <seconds>` | keep serving this long after the last record |

`--corpus` is the client contract check, not a debugging aid: `docs/CONTROL_API.md`
[§11](CONTROL_API.md#11-conformance-corpus) defines the manifest and the six things a case may
assert, and the exit code is `0` all passed, `1` a case failed, `2` the manifest itself is refused
(wrong version, unknown expectation key, a path that leaves the corpus).


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
| `--interactive` | trim by eye, one joint at a time; **this moves the dog** |
| `--only JOINT` | restrict `--interactive` to one joint, repeatable |
| `--step DEG` | keypress step in `--interactive` (default `0.44`) |

Output is one line per joint in the vendor's group order (`legs`, `head`, `tail`), with the current
value and the proposed one; a joint the HAL could not read prints `unread` rather than `0.0`, and is
never written, because saving its group would invent the other values in that list. A value past ±20
is clamped and the clamp is what gets saved. Exit codes: `0` saved or nothing to save, `1` a written
value did not read back (check the vendor log), `2` a usage error, no readable trim, or no dog.

### `--interactive`: trimming a joint by eye

```bash
python -m tools.calibrate_servos --interactive                       # all twelve joints
python -m tools.calibrate_servos --interactive --only lf_shoulder     # one joint
python -m tools.calibrate_servos --interactive --step 0.25            # finer than 0.44
```

Walks the joints one at a time: each line shows the joint and its current offset, and you step it until
the leg (or head, or tail) looks straight.

| Key | Effect |
|---|---|
| right arrow, `+`, `d` | raise the offset by one step (0.44° by default) |
| left arrow, `-`, `a` | lower it |
| Enter or space | accept this joint and move on |
| `s` | skip it, undoing any step already taken |
| `q` | quit and restore every joint this pass changed |

**This is the one mode that moves the dog.** Each keypress is written through
`DogHAL.apply_offsets` and re-poses as it saves — that write *is* the preview, which is the whole point
of the pass. Keep clear of the dog, and put it somewhere it can be looked at from the side.

Two guards, both before anything moves: the pass refuses to start while the control plane answers on
`127.0.0.1:8420` (stop the `houndmind` service first, because two writers on twelve servos is not a
calibration), and it needs a real terminal — press keys on the dog, not through a pipe.

The earlier version of this section said there was no preview on purpose, because nudging a servo
needed a raw per-group angle write that belongs to `act/interlock.py`. That reasoning held for the
*runtime*: the primitive this uses instead, `DogHAL.nudge_joint`, is capped at 3° per call, moves one
joint at calibration speed, writes no trim of its own, and is called by nothing that ticks.

For a measurement rather than an eye, `servo_level` [§14](#14-servo_level) is the better tool: it
probes each joint and solves for the trim that squares the body up against the IMU.

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

**Both sides or nothing.** Every axis has to see gravity pointing up *and* down — not merely "a wide
span". Two poses resting on the same face give a wide span and a bias of nearly a whole g, which is
what the first saved run on the bench dog produced (X never pointed up, Y never down, and the saved
bias matched the constant that was shifting the data). The tool refuses instead, naming the axis and
the direction it never saw.

**It clears the vendor's own offset before sampling.** `Pidog` computes an offset once at boot by
assuming the dog is level with its X axis pointing down (`pidog.py:474-479`) and then adds it to every
sample (`:490-495`). A PiDog boots **lying down**, so that offset is usually wrong, and measuring
through it yields a "bias" that is really that offset. `--apply` clears both the stored calibration and
the startup offset first, so what gets measured is the sensor. A dry run says when the offset is in
force, because its numbers then mean nothing.

**Nothing animates while it samples.** The vendor's `ActionFlow` plays `waiting` and
`feet_left_right` on its own every few seconds (`action_flow.py:230-243`), moving the head and legs.
Tools open the HAL with `start(animate=False)`, which is also what makes `hardware_checkup
--skip-motion` honest.

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

## 15. `audio_check`

Answers the question `aplay` cannot: **did sound actually leave the speaker?** `aplay` exits 0
whenever ALSA accepts the samples, so a muted amplifier, a dead speaker coil and a stuck I2S clock all
look like success. This tool records with the microphone while it plays, and measures the room.

```bash
python -m tools.audio_check --list
python -m tools.audio_check --verify                      # closed loop through `default`
python -m tools.audio_check --verify --device plughw:4,0  # straight to the DAC
python -m tools.audio_check --say "hello"
python -m tools.audio_check --analyse recording.wav       # what is in a recording
```

| Flag | Meaning |
|---|---|
| `--list` | what ALSA exposes for capture and playback (`arecord -l`, `aplay -l`); exit 1 when neither tool is installed |
| `--verify` | play a tone, record it, compare the room level before and during |
| `--device NAME` | playback: `default` (through `asound.conf`), `robothat`, `plughw:4,0` |
| `--mic NAME` | capture device, default `plughw:3,0` — the USB microphone; the V4 HAT has no onboard one |
| `--tone HZ` | play a tone only |
| `--say TEXT` | render the text with `espeak`/`espeak-ng` and play the wav |
| `--play FILE` | play an existing wav |
| `--analyse FILE` | the loudest frequencies in a wav, loudest first (needs numpy) |
| `--amp on\|off` | drive the speaker-enable pin and exit — give it on its own; a run that plays switches the pin on regardless |
| `--pin PIN` | the enable GPIO. Default `20`, so a Robot HAT **V5** needs `--pin 12` |
| `--no-amp` | leave the enable pin alone. Every run that plays switches it on first without this |
| `--seconds S` | tone or clip length, default `2.0` |
| `--min-delta DB` | how much louder the room must get for `EMITTED`, default `10` |
| `--json` | machine-readable output. With `--verify` it is one object, `{"verdict": "EMITTED"}` or `{"verdict": "SILENT"}` — `UNCLEAR` also exits 1 and prints `SILENT` there |

One action per run: `--list`, then `--amp` alone, then `--analyse`, then the first of `--tone` / `--say` /
`--play` / `--verify`. None of them given prints the help and exits `2`.

`--verify` prints the room level, the level during playback, the delta and a verdict: `EMITTED` at
+10 dB or more, `SILENT` at +3 dB or less, `UNCLEAR` between. Exit codes: `0` emitted, `1` silent,
`2` usage. Nothing here constructs `Pidog`, so the servo bus is never touched.

**Check the microphone gain before believing `SILENT`.** The USB microphone ships with its capture
control at 0 of 16 (`amixer -c 3 sset 'Mic' 16` to open it, +23.8 dB). A metre at minimum gain reads
as silence on a speaker that works, which is the opposite of a useful answer.

A `SILENT` verdict from a validated microphone means the ALSA chain is not the fault: see
`docs/TROUBLESHOOTING.md` [§6](TROUBLESHOOTING.md#6-camera-audio-vision) for the order to check the
amplifier and the speaker in.

**On the bench dog this has never reached `EMITTED`.** #254 records the whole chain verified layer by
layer — overlay, card 4, `pcm.!default → robothat`, mixer at 255/255, the amplifier pin reading output
high, the I2S clock started, `hw_ptr` advancing during playback — and `--verify` still returning
`SILENT` on `default`, `plughw:4,0` and `robothat`, with `--analyse` finding 56 Hz mains hum and no
1 kHz component in a recording made during a full-scale tone. So a `SILENT` result here is that defect,
not evidence against a fresh install, and no page may claim the HAT speaker works until #254 is closed.
The microphone half is #240.

## 16. `schema_export`

Writes the settings schema as a JSON Schema draft 2020-12 document, generated from the same `Spec`
tree the loader enforces (`kernel/config_schema.py::json_schema`). An editor uses it to complete and
check `config/settings.jsonc`; the tool reads no hardware and needs no dog.

```bash
python -m tools.schema_export --out settings.schema.json
python -m tools.schema_export                  # print it instead
```

An unknown key, a wrong type and an out-of-range number are the three things the loader refuses at
start, and the document declares exactly those: `additionalProperties: false` where the section is
strict, the `minimum`/`maximum` of every numeric key, and `null` in the type wherever a key allows
it. `--indent 0` emits one line for a diff.

## 17. `bench_tick`

Ticks the runtime's own module list on a `FakeDogHAL` and prints p50/p95/max per module plus how
often each overran the loop budget. It answers "which module is eating the tick", not "how does the
dog perform": the fake returns instantly, so vendor I2C, camera and audio costs are absent.

```bash
python -m tools.bench_tick                        # 300 ticks, 30 warmup, shipped config
python -m tools.bench_tick --ticks 1000 --hz 10   # a longer window at the shipped rate
python -m tools.bench_tick --disable mapping,scanning --json
```

`api` is always switched off, because the control plane is the one module that binds a port and a
service already running would make the run fail on `address in use`. `--disable` adds names, which is
how one hot path is isolated. The overall `tick` line uses `perf_counter`; the per-module figures are
the runtime's own `time.time()` measurements, so read a sub-millisecond module as "small", not as a
precise number.

There is no `--hal` flag and no motion option: nothing this tool starts can move the dog. The
workstation figures and the empty Pi row live in `docs/ARCHITECTURE.md` section 3.2 - fill the Pi row
from a run on the dog rather than assuming a workstation number carries over.

## 18. `map_inspect`

Prints what a home map file contains, read with the same validator the runtime uses
(`mapping/home_map.py`). It exists because the file used to be written and never read, so its contents
were an assumption — it held no grid at all (#286).

```bash
python -m tools.map_inspect                        # data/home_map.json, if it is there
python -m tools.map_inspect data/home_map.json --json
python -m tools.map_inspect path/to/map.json --width 100 --wall-cm 500
```

It reports the version, when it was saved, the cell size and grid size, how many cells and samples it
holds, the nearest wall the map knows about from the origin, and a coarse picture: `#` for a strong
cell, `+` for a weak one, `@` for the dog. `ix` is centimetres to the dog's left and `iy` forward, so
the picture is nose up, the same convention as the web app's map panel.

`--json` prints the document instead, which is what another tool or a diff wants. Exit code is 0 when
the file loads and 1 when it does not — with the reason named, never a bare traceback.

Read-only, no HAL, no runtime: it cannot move the dog, and it runs on any machine.

## 19. `step_calibrate`

Measures how far one `forward` command actually carries the dog, against a wall, and prints a
`surface_step_cm` block for `config/settings.jsonc`. It exists because `step_cm` shipped as 25 cm for
a dog about 25 cm long, while the vendor reference lists the real travel of one gait cycle as unknown
(#285) — and every place anchor and map dot is scaled by that constant.

```bash
python -m tools.step_calibrate --fake                                  # simulated wall, nothing moves
python -m tools.step_calibrate --confirm-clearance --surface hardwood
python -m tools.step_calibrate --confirm-clearance --surface carpet --commands 6
python -m tools.step_calibrate --confirm-clearance --measure reverse --surface carpet
python -m tools.step_calibrate --confirm-clearance --measure head-zero
```

| Flag | Meaning |
|---|---|
| `--confirm-clearance` | Mandatory on hardware. Without it (and without `--fake`) the tool prints why and exits `2` |
| `--measure` | `distance` (forward at a wall), `reverse` (back away from one), `head-zero` (level the head, report the reading) |
| `--surface` | The floor this run is for. That name is the key in `surface_step_cm` |
| `--commands` | Gait cycles to issue (default 5). Fewer than 3 is reported as `weak`, not `measured` |
| `--stop-at` | Stop this many cm from the wall (default 45) |
| `--speed` | Servo speed; the interlock may lower it, and the lowered value is what runs |
| `--min-volts` | Refuse to walk below this pack voltage (default 7.9 V). Above the interlock's 6.4 V veto on purpose: a gait on a pack this sagging reboots the Pi (#292) |
| `--record-trace` | Write the per-cycle trace (distance, acc, gyro) as JSON — the input L3.4 would need |
| `--pause` | settle time after each step, in seconds |
| `--fake-step-cm` | the stride the simulated wall answers with, for `--fake` |
| `--config` | settings file other than `config/settings.jsonc` |
| `--apply` | Compute the value the run supports: at least five cycles, no two more than 10 % apart, clamped to ±20 % of the constant in force. Prints the `surface_step_cm` line; never edits the config (#300) |
| `--json` | Print the report and snippet as one JSON document instead of the table |

**How it decides.** Each cycle: sample the distance (retrying a missed echo up to three times), ask the
runtime's own `Interlock` about a `forward` command carrying `steps: 1`, execute the interlock's
verdict, wait, sample again. `cm/cycle` is the least-squares slope of distance against cycle, so one
bad echo tilts the line instead of setting the answer, and the residual is printed beside it. A run is
`measured` only with at least three cycles, no veto and less than 5° of integrating-gyro drift —
otherwise the verdict says exactly what disqualified it and no value is offered.

**Space it needs.** Three numbers, because they are three different things:

- **Run-up to the wall.** You get `ceil((distance − stop_at) / stride)` cycles, and you do not know the
  stride yet. With the default `stop_at` of 45 cm: 100 cm of run-up measures any stride up to
  **27.5 cm per cycle** (three cycles), and completes all five only up to ~11 cm. Below 28 cm of
  run-up there is no measurement to be had, so 100 cm is the honest minimum and 150 cm is comfortable.
- **Measure to the sensor face, not the tail.** The ultrasonic sits in the head module, roughly 20 cm
  ahead of the middle of the body: a dog placed "100 cm from the wall" with a tape behind it read
  **80.2 cm**, and the same mark taken at the nose read **101.1 cm**. The first row the tool prints is
  your check — `before_cm` must match the tape, or something is in the beam.
- **The wall itself.** A flat, perpendicular, uninterrupted surface about **1 m wide** centred on the
  heading, with nothing nearer inside the beam (skirting, a door frame, a chair leg all read short).
  The pulse timeout allows ~290 cm, but `hal.sensors.distance_max_cm` clamps readings to **200 cm**,
  which is what limits `--measure reverse`: walking away grows the distance, so start close enough to
  stay under the clamp at the end, and keep ~1.5 m of clear floor behind.

The floor ahead only has to survive **one stride more than `stop_at`**: the stop is checked before each
step, so a run can finish one stride closer than you asked — at 25 cm/cycle from 100 cm it ends 25 cm
out, and the interlock's 12 cm obstacle veto is the backstop. That is why 45 cm is the default rather
than something tighter.

**Before you walk it: the pack.** The interlock vetoes at 6.4 V, which protects the servos — it does
not protect the Pi. On 2026-11-18 two walking attempts on the bench dog at **7.78 V and 7.85 V idle
both rebooted the Pi mid-gait** (`vcgencmd get_throttled` = `0x50000`, boots 20 s apart), while
`--measure head-zero` on the same pack completed twice; #292 has the timestamps. So this tool refuses
to walk below `--min-volts` (7.9 V) and abandons a run whose pack sags under it, because a brownout
costs the steps, the pose and the trace together. Charge the pack, then run: `--measure head-zero`
prints the voltage before anything walks.


**Why it stops instead of retrying.** A veto means the envelope said no: battery under the floor, a
tilted dog, an obstacle inside 12 cm, or an expired command. Driving on through one would defeat the
interlock this tool exists to respect, so the run ends and the veto is printed with its detail.

`--fake` runs the identical path against `step_calibrate._WallDogHAL` (a `FakeDogHAL` whose distance
falls by `--fake-step-cm` per step), which is also how its tests work. Nothing writes
`config/settings.jsonc`: the config is comment-rich user data, and the tool hands you the block.


## Adding a tool

A new device CLI belongs in `src/tools/` as a module with a `main(argv: list[str] | None = None) ->
int` entry point, so `python -m tools.<name>` and a test can both call it. Anything that can move the
dog defaults to dry and requires an explicit flag — see `docs/HARDWARE_TEST.md` for why that rule is
not negotiable. A new tool needs a section on this page and a row in the table above in the same
change.


## 20. `place_match`

Scores a folder of frames against the place views a person taught, off the dog. No camera, no motion.

```bash
python -m tools.place_match ~/.houndmind/places/views ./frames
python -m tools.place_match views/ frames/ --min-score 0.6 --json
```

| Flag | Meaning |
|---|---|
| `--min-score` | match threshold, default `0.45` — the same value `settings.place_recognition.min_score` uses |
| `--json` | one JSON object per frame, with the full ranking |

One line per frame: `frame place_id score verdict`, where the verdict is `match`, `no-match` (the best
view scored below the threshold — the score is the evidence) or `featureless` (the frame had too
little texture to match anything). Exit **0** when every frame was scored, **1** when there were no
views, no frames, or a file that is not an image — a tool that silently scores nothing is the failure
it exists to prevent.

A view is a 32×24 thumbnail plus ORB keypoints and descriptors, stored in one `views.json` per
directory (`perception/place_views.py`). `navigation/place_recognition.py` reads the same file on the
dog: two frames naming the same place re-anchor odometry and promote `localization` to the `place`
tier ([`FEATURES_GUIDE.md` §Localization tiers](FEATURES_GUIDE.md#localization-tiers)).

The fixtures in `tests/fixtures/places/` are **synthetic**, drawn by the test rather than committed:
a photograph of somebody's kitchen is personal data and says nothing about the code.

## 21. `camera_record`

Records a camera clip a SLAM claim can be measured on, once, and replayed anywhere. It starts the
runtime with every motion-capable module switched off, borrows the frame `services/camera.py` already
holds rather than opening the camera a second time, and never binds the control plane. It writes
`clip.jsonl` plus `manifest.json` — resolution, cadence, IMU magnitude and gyro bias, the host and the
commit under test (`houndmind_ai/optional/slam_clip.py`). **It needs the camera, not the legs.**

```bash
python -m tools.camera_record --seconds 60 --out data/clips/room-01
python -m tools.camera_record --seconds 5 --frames 20 --out /tmp/clip   # a short check
```

| Flag | Meaning |
|---|---|
| `--out DIR` | clip directory (default `data/clips`) |
| `--seconds S` | recording length, default `60`; must be positive unless `--frames` is given, else exit `2` |
| `--frames N` | stop after N frames, whichever comes first (below `1` exits `2`) |
| `--tick-hz N` | override `loop.tick_hz` — the sampling cadence of the clip |
| `--config PATH` | settings file other than `config/settings.jsonc` |
| `--json` | print the manifest as JSON only instead of the human summary |

The summary ends with the command that reads the clip back, so the next step is never guesswork. It also
prints which modules this run `disabled` and which this config does not declare. Exit `0` recorded, `1` no
frames were published — enable a vision module (`vision_pi4` on a Pi 4) and record again — `2` a usage
error, and `3` when the servo bus is already held, because a run against the real dog takes the run lock
(`systemctl stop houndmind` first).

## 22. `slam_replay`

Replays a clip from [`camera_record`](#21-camera_record) in one of two halves, and the flags are the two
halves. `--verify` needs **no camera, no SLAM library and no OpenCV** — the dimensions come from each
frame's own JPEG header — and refuses a clip by name when the frame count is not the one the manifest
promises, a line is not a JPEG, or the cadence is too irregular to pace (`--tolerance-pct`, default
`25`). `--host pi|pi5|pc` publishes the clip into the **real** runtime with `slam_pi4` switched on, so
the number includes the loop rather than a bare benchmark: each frame goes on the context when its own
recorded timestamp comes round, every motion-capable module stays off, and `hal_sensors` stays off too
because the IMU has to come from the clip. Each run writes one JSON report beside the clip — sustained
fps, CPU per core, temperature before and after, `slam_pi4`'s tick percentiles, the overruns, and the
frames the module buffered, skipped, processed, dropped or failed — plus a verdict sentence.

```bash
python -m tools.slam_replay data/clips/room-01 --verify                  # offline, no dog, no SLAM library
python -m tools.slam_replay data/clips/room-01 --host pi --backend rtabmap
python -m tools.slam_replay data/clips/room-01 --host pc --json          # one row of a comparison table
```

| Flag | Meaning |
|---|---|
| `clip` | the clip directory `camera_record` wrote (positional, required) |
| `--verify` | check the clip alone: count, JPEG framing, cadence. No dog |
| `--host {pi,pi5,pc}` | replay it through the real loop, labelling the report with this host. It is a label, not a detection |
| `--backend NAME` | `slam_pi4` backend for this run; default is the config's |
| `--speed F` | replay speed, default `1.0`; `2` plays a 60 s clip in 30 s without speeding the loop |
| `--max-frames N` | replay only the first N frames |
| `--drain-s F` | keep ticking this long after the last frame so a buffered one is processed, default `1.0` |
| `--tick-hz N` | override `loop.tick_hz` for this run |
| `--config PATH` | settings file other than `config/settings.jsonc` |
| `--out PATH` | report path; default beside the clip |
| `--tolerance-pct F` | jitter and cadence tolerance for `--verify`, default `25` |
| `--json` | print the report as JSON only |

Give exactly one half: neither, or both, exits `2`. Exit `0` verified or replayed, `1` a clip that will
not verify (the reason is named) or a replay that delivered no frame, `2` a usage error, and `3` when the
servo bus is already held — the message says who holds it and to `systemctl stop houndmind` first, because
a run against the real dog opens the camera through the vision modules. `--verify` writes no file; the
`--host` report is written beside the clip even when it exits `1`. A host without OpenCV gets the JPEG
bytes rather than a decoded array and the report says so — a backend that cannot read them processes
nothing, which is a finding, not a crash.

**No on-dog verdict exists for either half** — #327 is the run that would produce one — so the flags are
documented and this page claims no number.


