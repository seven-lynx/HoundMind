# HoundMind Hardware Test Guide (PiDog)

Status: **guide** — the bench procedure from "it installed" to "the dog works". Every command here
runs on the dog, in order, and each step says what a pass looks like before you run it.
Pairs with: `docs/INSTALL.md` (install first — this guide assumes it is done), `docs/LOGGING.md`
(when a step fails), `docs/CONTROL_API.md` [§4](CONTROL_API.md#4-state-snapshot) (the snapshot read in step 4),
`docs/CALIBRATION.md` (the four calibration measurements, and the order to run them)

Six steps. Steps 1–5 are read-only and cannot move the dog. **Step 6 is the only one that can**,
and it requires an explicit go-ahead (see [§9](#9-step-6--motion-and-only-motion)).

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
| 5. Peripherals | a fitted camera / audio / SLAM stack is visible to the OS, and a clip the camera recorded can be replayed | that a feature built on it behaves, or that the speaker makes a sound |
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

**Power, before anything else.** A brown-out is the one failure that reads like a software fault: the
process vanishes, the Pi boots clean, and the previous boot's log is gone unless journald is
persistent. `vcgencmd get_throttled` answers it, and bits 16-18 are **sticky for the life of the
boot** - which is what makes a reading taken straight after a reboot meaningful.

```bash
vcgencmd get_throttled     # 0x0 is clean; anything else is a supply problem, not a code problem
```

**On a charger you are not measuring what you think.** The USB-C port carries the Pi at idle and
not the servo bus, and with no pack fitted `sensors.battery_v` reads the input rail rather than a
cell. Servo motion needs the pack, so a motion step "on mains" is expected to drop the board — see
[`pidog/HARDWARE.md` §4.1](pidog/HARDWARE.md#41-what-the-usb-c-port-powers).

| Bit | Mask | Means |
|---|---|---|
| 0 | `0x1` | under-voltage right now |
| 1 | `0x2` | ARM frequency capped right now |
| 2 | `0x4` | currently throttled |
| 16 | `0x10000` | under-voltage has occurred since boot |
| 17 | `0x20000` | ARM frequency capping has occurred since boot |
| 18 | `0x40000` | throttling has occurred since boot |

`0x50000` (bits 16 and 18) immediately after a boot means the pack has already sagged: charge or
replace it, and do not start step 6. A Pi 4 under the PiDog pack's regulator draws more than a
partly discharged pack can supply through the HAT, and a brown-out costs the SD card as well as the
run (#185).

### 2.1 Keep the previous boot's log

A brown-out is diagnosed from the log of the boot that died, and on this image that log is gone
before you can read it: `/etc/systemd/journald.conf` ships `Storage=volatile`, which keeps the
journal in `/run/log/journal` — a tmpfs. `sudo mkdir -p /var/log/journal` does **not** change that,
and `journalctl` then reports a plausible 8 MB of disk usage that only ever lived in RAM.

The recipe that survives a power cut is a drop-in:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d /var/log/journal
printf "[Journal]\nStorage=persistent\n" | sudo tee /etc/systemd/journald.conf.d/99-houndmind-persistent.conf
sudo systemctl restart systemd-journald
sudo journalctl --flush
ls /var/log/journal          # a machine-id directory appears
journalctl --list-boots      # two entries after the next reboot
```

`systemd-analyze cat-config systemd/journald.conf` then shows `Storage=volatile` from the shipped
file followed by `Storage=persistent` from the drop-in, and the later one wins (#209).

**Persistent is not instantaneous.** journald flushes every `SyncIntervalSec` (5 minutes by
default), so the final seconds of a hard cut can still be missing — on the bench dog the last
flushed entry was eight minutes before a reset. Keep `vcgencmd get_throttled` and a fixed-rate
sampler CSV on disk as the primary instruments for a power test, and use the journal as
corroboration.

**Software setup.**

```bash
cd ~/HoundMind            # the repo root; `logs/` and `config/` are relative to it
source .venv/bin/activate
```

- [ ] A Raspberry Pi 4 or 5 on Raspberry Pi OS Bookworm 64-bit. Pi 3 is not supported
      (`docs/INSTALL.md:11-16`).
- [ ] HoundMind installed into that venv (`python -m pip install -e .`), so `python -m tools.<name>`
      resolves. From a bare checkout the form is `PYTHONPATH=src python -m tools.<name>`.

**One thing that will bite you.**

1. **The first distance reading can be `None` on a healthy dog.** The vendor caches the ultrasonic
   sample and the cache holds a `-1.0` placeholder until the sensor thread has taken one
   (`docs/pidog/PIDOG-SENSORS.md:46-49`). The HAL rejects anything outside
   `sensors.distance_min_cm`..`distance_max_cm`, so the placeholder reaches the checkup as `None`
   (#108). Re-run the step before concluding the sensor is dead.

## 3. The ladder at a glance

| # | Step | Command | Motion? | Time | Pass looks like |
|---|---|---|---|---|---|
| 1 | Install sanity | `python -m tools.installer_verify` | no | ~10 s | `Installer check: OK` |
| 2 | Sensors | `python -m tools.hardware_checkup --skip-motion` | no | ~5 s | five readings, no `None`, `valid:` all `True`, exit 0 |
| 3 | Loop | `python -m tools.smoke_test` | no | ~5 s | `[smoke] PASS` |
| 4 | Control plane | `python -m houndmind_ai`, then `GET /state` | no | ~2 min | `*_valid: true` |
| 5 | Peripherals | `tools.camera_check`, `tools.list_audio_devices`, `tools.audio_check --verify` | no | ~1 min | index found, frame saved, an audio `verdict:` recorded — `SILENT` is #254, not a failed step |
| 6 | Motion | [§9](#9-step-6--motion-and-only-motion) — **only with clearance and a yes** | **yes** | ~1 min | a gait you watched |

## 4. Step 1 — Install sanity

```bash
python -m tools.installer_verify
```

Expected, roughly in this shape (the package lines follow `requirements-lite.txt`, so the list is
longer than this):

```
HoundMind installer verification
Python: 3.11 -> OK (supported: 3.11-3.13)
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
| `pidog: MISSING` | the SunFounder libraries are not in this venv | `docs/INSTALL.md` [§3](INSTALL.md#3-install-sunfounder-pidog-libraries-into-the-same-python-environment) — they are cloned, not on PyPI |
| `houndmind_ai: MISSING` | this venv does not have the package | `python -m pip install -e .` |
| `Requirements file not found` | you are not in the repo root | `cd` to the repo and re-run |
| `Installer check: FAILED` | exactly one line above is `MISSING` | fix that line, not the others |
| `Python: 3.10 -> UNSUPPORTED` | the interpreter is outside the range `pyproject.toml` declares | rebuild the venv on 3.11–3.13 |

## 5. Step 2 — Sensors, read-only

```bash
python -m tools.hardware_checkup --skip-motion
```

`--skip-motion` is not optional here: without it the tool stands the dog, turns it both ways and
sweeps its head (`src/tools/hardware_checkup.py:24-31`). Step 6 is where that belongs.

Expected on a healthy dog:

```
[checkup] Reading sensors...
[checkup] distance_cm: 41.7
[checkup] touch: N
[checkup] sound: detected=False dir=None
[checkup] acc: (412.0, -180.0, 16310.0)
[checkup] gyro: (18.0, -7.0, 11.0)
[checkup] battery: 7.42 V
[checkup] valid: distance=True touch=True sound=True imu=True
[checkup] Motion skipped.
```

Five readings and a verdict. **A `None` on `distance_cm`, `touch`, `acc` or `gyro`, or a `False` on
the `valid:` line, is the failure**, whatever the exit code says (#109). `sound` is the exception: a
quiet room is `detected=False dir=None` with `sound=True` on the verdict line.

`battery` is a readout, not a gate: a dog without the sense line prints `None` and is still healthy,
and it never appears in `no reading from`. The power question is answered by `vcgencmd get_throttled`
above, not by this line.

| Line | What the number is | Healthy | Not healthy |
|---|---|---|---|
| `distance_cm` | centimetres in front of the **head**, conditioned by the HAL | a steady value once the dog is still; re-run if it jumps | `None` — read failed, no sample yet (re-run, #108), or no echo (soft, angled or absent surface); the vendor's `-1`/`-2` placeholders never reach this line |
| `touch` | `N` none · `L` left pad · `R` right pad · `LS`/`RS` a stroke | `N` at rest, and the letter of whichever pad you hold down while it runs | `None`, or a letter with nothing touching it |
| `sound: detected` / `dir` | busy line, then a bearing | `False dir=None` in a quiet room, with `sound=True` on the `valid:` line; clap once and re-run for `True` with a bearing | `detected=None dir=None` and `sound=False` — the SPI module did not answer; the `[checkup] hint:` line that follows names the log warning carrying the reason (#183) |
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

This runs the real runtime for 20 cycles at 5 Hz and then reports what came out of it. It disables
every module that can move the dog and **prints the list it used**, so the run states its own
guarantee instead of asking you to trust a sentence:

`behavior, hal_motors, navigation, safety, scanning, vision, voice, watchdog`

`scanning` is in that set because it drives the head straight through the HAL rather than through
`hal_motors` (`navigation/scanning.py:178-182`) - with it left enabled this step swept the head while
this page said nothing could move (#184). `safety` and `watchdog` are off here too, and that is the
reason step 3 says nothing about either: steps 2 and 6 own them, and step 2 proved the readings this
step only re-checks.

Watch the dog anyway. `tests/test_smoke_test.py` is what makes the claim testable - it builds this
tool's module list on the fake HAL and fails if any action reaches it - but a run you did not watch is
still a run you did not watch.

Expected:

```
[smoke] sensor_reading: OK
[smoke] scan_latest: SKIPPED (scanning is disabled in the motionless run)
[smoke] mapping_openings: SKIPPED (nothing to consume without a scan)
[smoke] disabled: behavior, hal_motors, navigation, safety, scanning, vision, voice, watchdog
[smoke] PASS
```

Two of the three keys read `SKIPPED`, and that is a pass in this mode rather than a shrug: a scan
needs the head, and `mapping` publishes from a scan, so neither can exist in a run with no motion.
`--include-motion` is where the sensor-to-scan-to-mapping chain is actually exercised.

| Flag | Default | Use it when |
|---|---|---|
| `--cycles N` | 20 | a slow Pi 4 needs fewer; a stutter needs more |
| `--tick-hz N` | 5 | you want to see the loop at its configured rate |
| `--config path` | `config/settings.jsonc` | you are testing a different profile |
| `--include-motion` | **off** | step 6 only, with clearance and a yes - it is the only mode that moves the head |

| `MISSING` on | The key never appeared, so look at | Most likely |
|---|---|---|
| `sensor_reading` | `hal_sensors` and the `hal` module under it | the HAL did not construct — `logs/houndmind.log` has the reason |
| `scan_latest` | `scanning`, under `--include-motion` only | no scan ran at all, or the head move raised — `logs/houndmind.log` carries the vendor error (#184) |
| `mapping_openings` | `mapping`, under `--include-motion` only | the module is disabled in `config/settings.jsonc`, or the scan never produced a reading |

`[smoke] FAIL` and exit 1 means `sensor_reading` was missing in the motionless mode, or that one of
the three was missing under `--include-motion` — read the lines above it, not the last one.

## 7. Step 4 — The control plane, live

Start the runtime and leave it running:

```bash
python -m houndmind_ai
```

Then, from an SSH session or another machine on the same network:

```bash
# no token needed — is the process alive?
curl -s http://<pi-ip>:8420/api/v1/meta
curl -s http://<pi-ip>:8420/api/v1/health

# state:read — the token is read from the file, never pasted
curl -s -H "Authorization: Bearer $(cat ~/.houndmind/api_token)" \
     http://<pi-ip>:8420/api/v1/state
curl -s -H "Authorization: Bearer $(cat ~/.houndmind/api_token)" \
     http://<pi-ip>:8420/api/v1/modules
```

The token is written 0600 to `~/.houndmind/api_token` on the device's first start, so it does not
exist until `python -m houndmind_ai` has run once. **Never paste it into an
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
python -m tools.audio_check --list                          # what ALSA exposes for playback and capture
python -m tools.audio_check --verify                        # closed loop: play, record, measure
python -m tools.audio_check --verify --device plughw:4,0    # straight to the DAC
python -m tools.validate_rtabmap_adapter                    # Pi 4/5 SLAM only
python -m tools.camera_record --seconds 5 --frames 20 --out /tmp/clip   # a clip `slam_replay` can read
python -m tools.slam_replay /tmp/clip --verify                          # offline; no camera, no SLAM library
```

`camera_record` builds the runtime and takes the run lock, so stop the process from step 4 first
(`Ctrl+C`, or `sudo systemctl stop houndmind`) — with it running, the tool exits `3` and names the
holder. `slam_replay --verify` reads a file and needs nothing stopped; `slam_replay --host` takes the
same lock.

| Command | Pass | If it is not |
|---|---|---|
| `--list-devices` | `Available indexes: [0]` (or `[0, 2]` for two cameras) | empty list — the camera is not enumerated; check the ribbon and the port before changing `vision.camera_index` |
| `--index N --save` | `Saved frame to frame.jpg`, and the file is a picture | `Failed to capture frame` — try the next index from the list; a black frame means the lens is covered or the sensor is not streaming |
| `list_audio_devices` | a device list, or `arecord -l` output | `Unable to list devices` and exit 1 — no audio stack; `voice` needs `pyaudio` and `i2samp.sh` |
| `audio_check --list` | the same cards from ALSA's own side — `arecord -l`, then `aplay -l` | `not found` — `alsa-utils` is missing: `sudo apt install alsa-utils` |
| `audio_check --verify` | a printed `delta` and **a verdict of any kind recorded**. The tool proves whether sound left the speaker, not that it sounds good | `SILENT` with the microphone gain open (`amixer -c 3 sset 'Mic' 16`) is #254, the known HAT speaker defect — record it rather than debugging it here. `UNCLEAR` is the gain or the distance, not the chain |
| `validate_rtabmap_adapter` | its own report | needs the `full` extra and the rtabmap install in `scripts/install_rtabmap_pi4.md` |
| `camera_record` + `slam_replay --verify` | a `[clip]` summary with a frame count, then the replay's verdict and no refusal | `no frames were published` — enable a vision module (`vision_pi4` on a Pi 4) and record again; a verify failure names its reason (frame count, a line that is not a JPEG, irregular cadence) |

The camera index and port come from config (`vision.camera_index`), so record the index this step
found rather than hardcoding `/dev/video0` anywhere.

Two flags decide whether an audio run means anything. `--verify` switches the speaker-enable pin on
before it plays, and `--pin` defaults to **20** — a Robot HAT **V5** needs `--pin 12`, or the run
measures a pin nothing is listening on. `--no-amp` is what leaves the pin alone. Write down the verdict
with the rest of the run: `SILENT` here is a recorded result, and the `--host` half of `slam_replay`
(the loop cost, not just the clip) belongs to #327, not to this step.

## 9. Step 6 — Motion, and only motion

This is the only step that can damage the dog. Say all four of these out loud and get a yes before
you run either command:

1. **What will move** — stand, both turns, then the head sweep. About three seconds of walking, at
   the vendor's own rates (`speed: 65` for the stand, `98` for the turns), with 0.6 s between steps.
   Those are deliberately below the kit's maximum: at 180 the leg steps pull enough inrush to brown
   out the stock pack's 5 V rail, which measures the supply instead of the servos the run is here
   to check (#207).
2. **The stop path** — `Ctrl+C`, or lift the dog off its feet.
3. **Clearance** — open floor, no table legs, nothing breakable within one body length, and the dog
   **off the blocks**.
4. **Battery and servo state** — charged, nothing warm, no servo buzzing at rest.

Then, either the checkup without the flag:

```bash
python -m tools.hardware_checkup --pause 1.5
```

…which runs stand → turn left → turn right → head −30° → head +30° → head centre
(`src/tools/hardware_checkup.py:29-36`); `--pause` slows it down, and 1.5 s is a better first run
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
| Every line in step 2 is `None` and every flag on `valid:` is `False` | the vendor layer did not load, so nothing reached the bus | `python -c "import pidog"`, then check `logs/houndmind.log`; a Pi with I2C disabled fails exactly like this (`sudo raspi-config` → Interface → I2C) |
| `[checkup] pidog unavailable` and exit code 2 | the vendor package is not in this venv | `docs/INSTALL.md` [§3](INSTALL.md#3-install-sunfounder-pidog-libraries-into-the-same-python-environment) — `pidog` is cloned, not on PyPI |
| `[checkup] the servo bus is owned by ...` and exit code 3 | another process has the bus open — usually the runtime | `sudo systemctl stop houndmind`, then re-run. The message names the holder (`pid 1234 (runtime)`); nothing is broken, the second process simply did not try to take a bus it could not have (#213) |
| the installer stops at `fatal: ambiguous argument 'origin/master'`, exit 128 | a cached clone in `.cache/houndmind_deps` was reset to a branch the remote no longer has | fixed in this tree (#233). On an older checkout: `rm -rf .cache/houndmind_deps` and re-run |
| the installer stops at `missing module(s): pyaudio` and blames the branch | `--preset lite` installed none of the four modules `robot_hat/__init__.py` imports | fixed in this tree (#180). `--auto-system-deps` also installs `portaudio19-dev`, which `pyaudio` needs to build |
| `This venv was created without --system-site-packages` | an existing venv cannot see Debian-provided bindings, so `import picamera2` will fail | `rm -rf .venv` and re-run the installer; new venvs are created with the flag (#215) |
| `distance_cm: None`, everything else green | no sample yet (re-run, #108) or no echo from a soft or angled surface | re-run step 2 against a hard flat surface at arm's length before suspecting the transducer |
| Step 2 passes, `sensor_reading: MISSING` in step 3 | the tool and the HAL read through different paths | the `hal`/`hal_sensors` module is `disabled` with a reason — `/api/v1/modules` or the log names it |
| `[smoke] FAIL` only on `scan_latest` (with `--include-motion`) | `scanning` produced no reading | `/api/v1/modules` names a disabled reason; `logs/houndmind.log` carries the vendor error from the head move (#184) |
| `[smoke] FAIL` only on `mapping_openings` (with `--include-motion`) | `mapping` disabled or no scan to consume | `config/settings.jsonc` → `modules.mapping.enabled` |
| `401` on `/api/v1/state` | missing or foreign bearer token | `cat ~/.houndmind/api_token` **stays on the device** — send it in the header, never into a report |
| `Connection refused` on `:8420` | the API module is off, or on another host/port | `/api/v1/meta` from the Pi itself first; then `api.host` / `api.port`, and `https://` if `api.tls_enabled` is on |
| `Address already in use` | an earlier runtime is still running | `pkill -f houndmind_ai`, then start once |
| Step 2 or 3 hangs on a live dog | the runtime already owns the servo bus | never run these two while `python -m houndmind_ai` is up — stop it first (#11: the checkup opens its own `PidogHAL` in a second process) |
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
  calibration workflow is separate, and the vendor's own calibration script moves the dog on
  purpose — see `hal/iface.py` (`read_offsets` / `apply_offsets`) and do not run a calibration as
  part of a bench test.
- **`houndmind doctor` does not exist** (#23). If a document elsewhere points you at it, the
  commands above are what it meant.
- **Motion quality is a judgement**, not a measurement. [§9](#9-step-6--motion-and-only-motion)'s checklist is the closest thing to
  a pass criterion this project has, and it needs you watching.
- **Run one thing at a time.** `tools.hardware_checkup` opens its own `PidogHAL`, which is a
  `Pidog()` in a second process (#11), so it and `python -m houndmind_ai` must never be up at the
  same time.

