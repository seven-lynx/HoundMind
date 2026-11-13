# HoundMind Hardware Test Guide (PiDog)

Status: **guide** — the bench procedure from "it installed" to "the dog works". Every command here
runs on the dog, in order, and each step says what a pass looks like before you run it.
Pairs with: `docs/INSTALL.md` (install first — this guide assumes it is done), `docs/LOGGING.md`
(when a step fails), `docs/CONTROL_API.md` §4 (the snapshot read in step 4)

Six steps. Steps 1–5 are read-only and cannot move the dog. **Step 6 is the only one that can**,
and it requires an explicit go-ahead (see §9).

If a step fails, do not skip to the next one: the later steps use the sensor the earlier one
proved, and a failure skipped once is a failure that comes back as a mystery later.

## Contents

1. [What this run proves — and what it does not](#1-what-this-run-proves--and-what-it-does-not)
2. [Before you start](#2-before-you-start) — the checklist that makes the rest safe
3. [The ladder at a glance](#3-the-ladder-at-a-glance) — all six steps in one table
4. [Step 1 — Install sanity](#4-step-1--install-sanity)
5. [Step 2 — Sensors, read-only](#5-step-2--sensors-read-only)
6. [Step 3 — Loop and modules, still no motion](#6-step-3--loop-and-modules-still-no-motion)
7. [Step 4 — The control plane, live](#7-step-4--the-control-plane-live)
8. [Step 5 — Peripherals, only if you fitted them](#8-step-5--peripherals-only-if-you-fitted-them)
9. [Step 6 — Motion, and only motion](#9-step-6--motion-and-only-motion)
10. [When something fails](#10-when-something-fails)
11. [Recording the run](#11-recording-the-run)
12. [What this guide does not cover](#12-what-this-guide-does-not-cover)

---

## 1. What this run proves — and what it does not

| Step | Proves | Does **not** prove |
|---|---|---|
| 1. Install sanity | the venv can import what the runtime imports | that any sensor answers |
| 2. Sensors | each of the five sensors answers over its bus | that the readings are accurate |
| 3. Loop | the runtime starts its modules and produces a scan and a map | that anything moves |
| 4. Control plane | the API is reachable, the token works, the live snapshot is truthful | anything about gait |
| 5. Peripherals | a fitted camera / audio / SLAM stack is visible to the OS | that a feature built on it behaves |
| 6. Motion | the servos hold a gait under load, in the clear | endurance, calibration, or thermal headroom |

A green run through step 5 is a "the electronics and the loop are healthy" result. It is not a
"the dog walks well" result — that is step 6 and a pair of eyes.

## 2. Before you start

**Physical setup.** Nothing below needs the dog to stand until step 6.

- [ ] Block the dog up so the legs hang free and cannot drive it off the bench, or put it on a
      clear floor if it is already standing.
- [ ] Nothing breakable within one body length.
- [ ] Battery charged, not "nearly". A sagging battery under load is how a servo cooks.
- [ ] Camera lens covered until step 5.
- [ ] Know the stop path before you start: `Ctrl+C` in the terminal, or lift the dog.

**Software setup.**

```bash
cd ~/HoundMind            # the repo root; `logs/` and `config/` are relative to it
source .venv/bin/activate
```

- [ ] A Raspberry Pi 4 or 5 on Raspberry Pi OS Bookworm 64-bit. Pi 3 is not supported
      (`docs/INSTALL.md:11-16`).
- [ ] HoundMind installed into that venv (`python -m pip install -e .`), so `python -m tools.<name>`
      resolves. From a bare checkout the form is `PYTHONPATH=src python -m tools.<name>`.

**Two things that will bite you.**

1. **A tool exiting 0 is not a pass.** `tools.hardware_checkup` returns 0 even when every sensor
   failed — the failure shows up as a printed `None`, not an exit code (#109). Read the output;
   do not trust `echo $?`.
2. **The first distance reading can be `-1.0` on a healthy dog.** The vendor caches the ultrasonic
   sample and the cache starts at `-1.0` until the sensor thread has taken one
   (`docs/pidog/PIDOG-SENSORS.md:46-49`, #108). If you see `-1.0`, re-run the step before
   concluding the sensor is dead.

## 3. The ladder at a glance

| # | Step | Command | Motion? | Time | Pass looks like |
|---|---|---|---|---|---|
| 1 | Install sanity | `python -m tools.installer_verify` | no | ~10 s | `Installer check: OK` |
| 2 | Sensors | `python -m tools.hardware_checkup --skip-motion` | no | ~5 s | five lines, no `None` |
| 3 | Loop | `python -m tools.smoke_test` | no | ~5 s | `[smoke] PASS` |
| 4 | Control plane | `python -m houndmind_ai`, then `GET /state` | no | ~2 min | `*_valid: true` |
| 5 | Peripherals | `tools.camera_check`, `tools.list_audio_devices` | no | ~1 min | index found, frame saved |
| 6 | Motion | §9 — **only with clearance and a yes** | **yes** | ~1 min | a gait you watched |

## 4. Step 1 — Install sanity

```bash
python -m tools.installer_verify
```

Expected, roughly in this shape (the package lines follow `requirements-lite.txt`, so the list is
longer than this):

```
HoundMind installer verification
Python: 3.11 -> OK
json5: OK
aiohttp: OK
...
pidog: OK
houndmind_ai: OK
Installer check: OK
```

`Installer check: OK` and exit 0 is the pass.

| What you see | Means | Do |
|---|---|---|
| `pidog: MISSING` | the SunFounder libraries are not in this venv | `docs/INSTALL.md` §3 — they are cloned, not on PyPI |
| `houndmind_ai: MISSING` | this venv does not have the package | `python -m pip install -e .` |
| `Requirements file not found` | you are not in the repo root | `cd` to the repo and re-run |
| `Installer check: FAILED` | exactly one line above is `MISSING` | fix that line, not the others |
| `Python: 3.14 -> OK` | the verifier's floor is 3.10 (#111); the package needs 3.11–3.13 | rebuild the venv on 3.11 |

## 5. Step 2 — Sensors, read-only

```bash
python -m tools.hardware_checkup --skip-motion
```

`--skip-motion` is not optional here: without it the tool stands the dog, turns it both ways and
sweeps its head (`src/tools/hardware_checkup.py:95-107`). Step 6 is where that belongs.

Expected on a healthy dog:

```
[checkup] Reading sensors...
[checkup] distance_cm: 41.7
[checkup] touch: N
[checkup] sound: detected=False dir=-1
[checkup] acc: (412.0, -180.0, 16310.0)
[checkup] gyro: (18.0, -7.0, 11.0)
[checkup] Motion skipped.
```

Five lines of numbers. **A `None` on any line is the failure**, whatever the exit code says (#109).

| Line | What the number is | Healthy | Not healthy |
|---|---|---|---|
| `distance_cm` | centimetres in front of the **head**, cached | a steady value once the dog is still; re-run if it jumps | `None` (read failed), `-1.0` (no sample yet — re-run, #108), `-2` (no echo: soft, angled or absent surface) |
| `touch` | `N` none · `L` left pad · `R` right pad · `LS`/`RS` a stroke | `N` at rest, and the letter of whichever pad you hold down while it runs | `None`, or a letter with nothing touching it |
| `sound: detected` / `dir` | busy line, then a bearing in 20° steps | `False dir=-1` in a quiet room; clap once and re-run for `True` with `0`–`359` | `None None` — the SPI module did not answer |
| `acc` | **raw counts**, 16384 per g | roughly ±16384 on the axis pointing at the floor, near 0 on the other two | all zeros, or `None` |
| `gyro` | **raw counts**, 16.4 per °/s | near 0 at rest; thousands when you move the dog | all zeros, or `None` |

Two traps in that table:

- **`acc` and `gyro` are counts, not g and °/s.** `16384` reads as "1 g" and `16.4` as "1 °/s"
  (`docs/pidog/PIDOG-SENSORS.md:140-143`). Do not read a `16310` as an absurd acceleration.
- **The touch pads are polled, not interrupt-driven**, and `read()` is a single sample
  (`docs/pidog/PIDOG-SENSORS.md:86-89`). To prove a pad works you must be holding it while the
  command runs — a tap between runs is simply not seen.

A missed ultrasonic echo on carpet or a soft surface is normal and is **not** a fault
(`docs/pidog/PIDOG-SENSORS.md:57-62`). Test the distance against something hard.

## 6. Step 3 — Loop and modules, still no motion

```bash
python -m tools.smoke_test
```

This runs the real runtime for 20 cycles at 5 Hz and then reports whether three things came out of
it. It disables `hal_motors`, `navigation`, `behavior`, `watchdog`, `safety`, `vision` and `voice`
(`src/tools/smoke_test.py:39-51`), so **nothing can move** — and nothing in the safety stack runs
either, which is the reason step 3 says nothing about safety. Steps 2 and 6 own that.

Expected:

```
[smoke] sensor_reading: OK
[smoke] scan_latest: OK
[smoke] mapping_openings: OK
[smoke] PASS
```

| Flag | Default | Use it when |
|---|---|---|
| `--cycles N` | 20 | a slow Pi 4 needs fewer; a stutter needs more |
| `--tick-hz N` | 5 | you want to see the loop at its configured rate |
| `--config path` | `config/settings.jsonc` | you are testing a different profile |
| `--include-motion` | **off** | step 6 only, with clearance and a yes |

| `MISSING` on | The key never appeared, so look at | Most likely |
|---|---|---|
| `sensor_reading` | `hal_sensors` and the `hal` module under it | the HAL did not construct — `logs/houndmind.log` has the reason |
| `scan_latest` | `scanning` | the head servo or the scan interval; step 2 already proved the sensor |
| `mapping_openings` | `mapping` | the module is disabled in `config/settings.jsonc`, or the scan never produced a reading |

`[smoke] FAIL` and exit 1 means at least one of the three was missing — read the three lines
above it, not the last one.

## 7. Step 4 — The control plane, live

Start the runtime and leave it running:

```bash
python -m houndmind_ai
```

Then, from an SSH session or another machine on the same network:

```bash
# no token needed — is the process alive?
curl -s http://<pi-ip>:8420/meta
curl -s http://<pi-ip>:8420/health

# state:read — the token is read from the file, never pasted
curl -s -H "Authorization: Bearer $(cat ~/.houndmind/api_token)" \
     http://<pi-ip>:8420/api/v1/state
curl -s -H "Authorization: Bearer $(cat ~/.houndmind/api_token)" \
     http://<pi-ip>:8420/api/v1/modules
```

The token is written 0600 to `~/.houndmind/api_token` on the device. **Never paste it into an
issue, a chat or a screenshot**, and never quote it in a report. A `401` means the header is
missing or the token is not this device's — it does not mean the API is down.

The snapshot is the one shape `/state` and the WS `state` frame share
(`docs/CONTROL_API.md:281-320`). Read these keys, in this order:

| Key | Pass | If it is not |
|---|---|---|
| `sensors.distance_valid`, `touch_valid`, `sound_valid`, `imu_valid` | `true` for each sensor you proved in step 2 | the sensor answered the tool but not the HAL — a different path, so re-run step 2 and compare |
| `sensors.battery_v` + `battery_valid` | a believable voltage for your pack | `null` = no battery sense on this HAT |
| `health.status` / `cpu_pct` / `temp_c` | `ok`, CPU well under 100, temperature in the 40s–60s | `degraded` with a reason in `health.reasons`; a Pi 4 idling near 80 °C is a cooling problem, not a HoundMind one |
| `modules` (`loaded` / `disabled` / `failed`) | `failed: 0` | a non-zero `failed` count is the module named in `/api/v1/modules` with its reason |
| `supervisor.holding` | `false` while nothing moves | `true` with a `reason` is the watchdog doing its job |
| per-module `tick_ms` on `/api/v1/modules` | steady, well under one tick period | a rising `tick_ms` is the `pi-performance` question, not a hardware fault |

Two reading rules that catch people out:

- **`ts` is monotonic, not wall-clock** (`docs/CONTROL_API.md:322-323`). Compare it to other
  timestamps in the same stream; never to `date`.
- **`/state` does not carry loop-performance counters.** `runtime_performance` is written into the
  runtime context (`src/houndmind_ai/core/runtime.py`) but is not part of the snapshot; per-module
  timing comes from `/api/v1/modules` as `tick_ms`.

## 8. Step 5 — Peripherals, only if you fitted them

Skip any line here whose hardware you do not have. A missing camera is not a failed test.

```bash
python -m tools.camera_check --list-devices --max-index 5
python -m tools.camera_check --index 0 --save frame.jpg
python -m tools.list_audio_devices
python -m tools.validate_rtabmap_adapter      # Pi 4/5 SLAM only
```

| Command | Pass | If it is not |
|---|---|---|
| `--list-devices` | `Available indexes: [0]` (or `[0, 2]` for two cameras) | empty list — the camera is not enumerated; check the ribbon and the port before changing `vision.camera_index` |
| `--index N --save` | `Saved frame to frame.jpg`, and the file is a picture | `Failed to capture frame` — try the next index from the list; a black frame means the lens is covered or the sensor is not streaming |
| `list_audio_devices` | a device list, or `arecord -l` output | `Unable to list devices` and exit 1 — no audio stack; `voice` needs `pyaudio` and `i2samp.sh` |
| `validate_rtabmap_adapter` | its own report | needs the `full` extra and the rtabmap install in `scripts/install_rtabmap_pi4.md` |

The camera index and port come from config (`vision.camera_index`), so record the index this step
found rather than hardcoding `/dev/video0` anywhere.

## 9. Step 6 — Motion, and only motion

This is the only step that can damage the dog. Say all four of these out loud and get a yes before
you run either command:

1. **What will move** — stand, both turns, then the head sweep. About three seconds of walking,
   with 0.6 s between steps.
2. **The stop path** — `Ctrl+C`, or lift the dog off its feet.
3. **Clearance** — open floor, no table legs, nothing breakable within one body length, and the dog
   **off the blocks**.
4. **Battery and servo state** — charged, nothing warm, no servo buzzing at rest.

Then, either the checkup without the flag:

```bash
python -m tools.hardware_checkup --pause 1.5
```

…which runs stand → turn left → turn right → head −30° → head +30° → head centre
(`src/tools/hardware_checkup.py:95-107`); `--pause` slows it down, and 1.5 s is a better first run
than the 0.6 s default. Or the whole loop with motion allowed:

```bash
python -m tools.smoke_test --include-motion
```

Watch the first seconds with your hand near the power, and be ready to stop. What you are looking
for:

- [ ] All four legs take weight; none drags, skips or grinds.
- [ ] The two turns are mirrored, not one fast and one slow.
- [ ] The head sweep travels the same distance left and right, and returns to centre.
- [ ] No servo chatters at rest afterwards, and nothing is warm that was not warm before.

Then re-run step 2 (`--skip-motion`) — a motion run moves the head, and the distance reading
belongs to wherever the head was pointing when it was taken
(`docs/pidog/PIDOG-SENSORS.md:64-66`).

## 10. When something fails

Find the symptom, take the next step — not a different one.

| Symptom | Most likely | Do this first |
|---|---|---|
| Every line in step 2 is `None` | the vendor layer did not load, so nothing reached the bus | `python -c "import pidog"`, then check `logs/houndmind.log`; a Pi with I2C disabled fails exactly like this (`sudo raspi-config` → Interface → I2C) |
| `distance_cm: -1.0` | no sample had been taken yet | re-run step 2 (#108); if it stays `-1`, the transducer or its wiring is the suspect |
| `distance_cm: -2` | no echo came back | test against a hard flat surface at arm's length before suspecting the sensor |
| Step 2 passes, `sensor_reading: MISSING` in step 3 | the tool and the HAL read through different paths | the `hal`/`hal_sensors` module is `disabled` with a reason — `/api/v1/modules` or the log names it |
| `[smoke] FAIL` only on `scan_latest` | `scanning` produced no reading | `/api/v1/modules` names a disabled reason; step 6 tells you whether the head moves at all |
| `[smoke] FAIL` only on `mapping_openings` | `mapping` disabled or no scan to consume | `config/settings.jsonc` → `modules.mapping.enabled` |
| `401` on `/api/v1/state` | missing or foreign bearer token | `cat ~/.houndmind/api_token` **stays on the device** — send it in the header, never into a report |
| `Connection refused` on `:8420` | the API module is off, or on another host/port | `/meta` from the Pi itself first; then `api.host` / `api.port`, and `https://` if `api.tls_enabled` is on |
| `Address already in use` | an earlier runtime is still running | `pkill -f houndmind_ai`, then start once |
| Step 2 or 3 hangs on a live dog | the runtime already owns the servo bus | never run these two while `python -m houndmind_ai` is up — stop it first (#11: the checkup constructs its own `Pidog`) |
| `temp_c` climbing past ~75 under step 3 | cooling, not HoundMind | the `pi-performance` question; a bare Pi 5 on a HAT V4 is also a power problem (`docs/INSTALL.md:18-23`) |

## 11. Recording the run

A run nobody can read twice did not happen. Keep it to three lines plus the evidence:

```markdown
- Verified: <step number> — <the exact command>
- Not verified: <what still needs the dog, and why>
- Evidence: <the output lines that mattered / the snapshot keys / the frame or log excerpt>
```

For anything that failed:

```bash
export HOUNDMIND_TRACE_ID=trace-bench-1     # correlate the log before you reproduce
python -m tools.collect_support_bundle /tmp/support.zip
```

The bundle carries `metadata.json` (timestamp, commit, trace id), everything in `logs/`, and
`config/settings.jsonc`. The files it should contain — all three are separate on purpose, and
`docs/LOGGING.md` documents the paths and which module writes each:

| File | Written by | Holds |
|---|---|---|
| `logs/houndmind.log` | `logging` | the runtime's own JSON lines, every level |
| `logs/houndmind_events.jsonl` | `event_log` | the event snapshot, 5 MB cap then rotate to `.1` |
| `logs/houndmind_decisions.jsonl` | `decision_log` | one record per tick: intent, source, vetoes, inputs |

## 12. What this guide does not cover

- **It is a procedure, not a gate.** Step 2's exit code is always 0 (#109), so the verdict is read
  by a human from the output. Do not script a green/red from it yet.
- **One run, one board.** Nothing here is endurance, thermal headroom, or servo calibration. The
  calibration workflow is separate, and it moves the dog on purpose — see
  `calibration/servo_calibration.py` and do not run it as part of a bench test.
- **`houndmind doctor` does not exist** (#23). If a document elsewhere points you at it, the
  commands above are what it meant.
- **Motion quality is a judgement**, not a measurement. §9's checklist is the closest thing to
  a pass criterion this project has, and it needs you watching.
- **Run one thing at a time.** `tools.hardware_checkup` builds its own `Pidog()` (#11), so it and
  `python -m houndmind_ai` must never be up at the same time.

