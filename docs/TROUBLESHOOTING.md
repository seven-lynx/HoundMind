# Troubleshooting

Status: **runbook** — symptom to cause to command. Start here when something is wrong and you do not
yet know which document owns it.
Pairs with: `docs/LOGGING.md` (logs and support bundles), `docs/INSTALL.md` §Troubleshooting (install
failures), `docs/HARDWARE_TEST.md` §10 (a step failed mid-ladder)

Each row gives three things: what you saw, what it usually means, and what to run next. If the command
does not answer it, the last column names the document that will.

## Contents

1. [Install and import](#1-install-and-import)
2. [Start-up](#2-start-up)
3. [Sensors](#3-sensors)
4. [Motion](#4-motion)
5. [Control plane](#5-control-plane)
6. [Camera, audio, vision](#6-camera-audio-vision)
7. [When you need help](#7-when-you-need-help)

---

## 1. Install and import

| What you see | Means | Do |
|---|---|---|
| `ModuleNotFoundError: No module named 'pidog'` | the SunFounder libraries are not in this venv | install them into the **same** environment (`docs/INSTALL.md` §3) — they are not on PyPI |
| `ModuleNotFoundError: No module named 'tools'` | the package is not installed, so `-m tools.x` cannot resolve | `python -m pip install -e .`, or prefix with `PYTHONPATH=src` |
| `ERROR: Could not find a version that satisfies the requirement pidog` | same cause as the first row | never `pip install pidog`; it does not exist on PyPI |
| `Python 3.10 or 3.11 is required` from the installer | the wrapper's own gate is stricter than the supported range ([#113](https://github.com/seven-lynx/HoundMind/issues/113)) | `PYTHON=python3.11 bash scripts/install_houndmind.sh`, or use Bookworm (3.11) |
| `pip` refuses the package on 3.10, or a `wheel`/`gcc`/`dlib` build fails | interpreter too old, or no wheel for this OS | Bookworm 64-bit (3.11), or `--preset lite` if you do not need the heavy stack |

## 2. Start-up

| What you see | Means | Do |
|---|---|---|
| the process exits 2 immediately with a list of problems | a config error, caught before any hardware is touched | fix the named key — an unknown key is an error, not a hint (`docs/FEATURES_GUIDE.md` §29) |
| a `ConfigError` naming a module or section you deleted | leftover key from an older config | delete the block; the did-you-mean names the replacement |
| `unsupported` profile, or a refusal naming a release | the board is a Pi 3 or older | not supported; `v2026.01.18` is the last release that ran on one |
| the process starts, then exits after a couple of seconds | something set `loop.max_cycles` | set it to `null` |
| a module shows `disabled` with a reason | it could not start and said why — not a crash | read the reason; usually a missing optional dependency |
| a module shows `failed` | a bug, not a config choice | file it with the `detail` from `GET /api/v1/modules` |

## 3. Sensors

| What you see | Means | Do |
|---|---|---|
| `distance_cm: None` in a checkup | the read failed | check the HAT is seated and I2C is on (`sudo raspi-config`), then `python -m tools.hardware_checkup --skip-motion` |
| `distance_cm: -1.0` on a healthy dog | the vendor's ultrasonic cache has no sample yet | re-run the step; the first read after boot is always `-1.0` ([#108](https://github.com/seven-lynx/HoundMind/issues/108)) |
| a checkup exits 0 but every sensor printed `None` | the exit code is not a pass for this tool | read the output ([#109](https://github.com/seven-lynx/HoundMind/issues/109)) |
| `*_valid: false` in `GET /state` | validity flags are published regardless of the badge module | branch on the flag before the value — a number with `valid: false` is not a measurement |
| readings that stop updating | the sensor thread stalled, or the watchdog is holding motion | `GET /state` → `watchdog_hold`; see `docs/FEATURES_GUIDE.md` §10 |

## 4. Motion

| What you see | Means | Do |
|---|---|---|
| `409` with `veto: "obstacle"` on every forward | something is inside `navigation.min_distance_cm` (15 cm) | move the dog, or read `perception.occupancy` from `GET /state` |
| `409` with `veto: "tilt"` | the dog is not level — it was picked up, or is on a slope | right it; `tilt_latched` clears once it is level again |
| `409` with `veto: "mode"` | the runtime is in `rest`, which refuses client motion | `POST /api/v1/mode` with `{"mode": "idle"}` |
| `409` with `veto: "expired"` | the deadman ran out before the command was refreshed | send it again; a held command must be refreshed |
| `409` with `veto: "low_voltage"` | the battery is below the floor | charge it — a sagging battery under load is how a servo cooks |
| commands accepted, nothing moves | `hal_motors` or `motion_gateway` is disabled | check both under `modules` in `config/settings.jsonc` |
| servos jitter or buzz | speed too high for the load, or offsets were overwritten | lower `speed`, reduce `steps`, verify the offsets (`docs/HOUNDMIND_PROGRAMMING_GUIDE.md` §9) |
| a routine stops halfway with `state: refused` | a step was vetoed and the run ended rather than skipping it | `veto` names the reason (`docs/ROUTINES.md` §"How it plays") |

## 5. Control plane

| What you see | Means | Do |
|---|---|---|
| `401` on everything except `/meta` and `/health` | no token, or the wrong one | the token is in `~/.houndmind/api_token`; send `Authorization: Bearer <token>` |
| `401` on `/camera/stream?token=…` | a token in a URL is refused by design | mint a ticket with `POST /api/v1/camera/ticket`, then use `?ticket=` |
| `403` on `POST /api/v1/pair/open` | a client token cannot open a pairing window | use the device token, which holds `admin` |
| connection refused on port 8420 | the plane is off, or bound elsewhere | `modules.api.enabled`, `settings.api.host` and `.port` |
| `503` from `/routines`, `/places`, `/decisions` or `/logs` | the module that answers it is disabled | the `error` body names it; enable that module |
| the WebSocket closes immediately | the first frame was not a valid `hello` | `docs/CONTROL_API.md` §5 |

## 6. Camera, audio, vision

| What you see | Means | Do |
|---|---|---|
| `tools.camera_check --list-devices` finds nothing | camera not enabled, or not fitted | `sudo raspi-config` → Interface Options → Camera |
| frames open but are black | lens cap, or the wrong index | try `--index 1`, and check the lens |
| the feed starts but no frames arrive | `picamera2` failed and the fallback was not used | set `settings.vision_pi4.backend` to `"opencv"` |
| `vision_inference_status: unconfigured` | the scheduler is on with no model | pass an `inference_fn`, or turn `inference_scheduler_enabled` off (`docs/FEATURES_GUIDE.md` §21a) |
| the semantic labeler reports no labels | model files are missing | `python -m tools.download_opencv_models` |
| `tools.list_audio_devices` is empty | the I2S overlay is not installed | `sudo bash i2samp.sh` from the `pidog` directory, or re-run the installer with `--run-i2samp` |
| face recognition disables itself at start | `dlib`/`face_recognition` is not importable | optional install; the module degrades to `disabled` with that reason |

## 7. When you need help

1. Collect a bundle: `python -m tools.collect_support_bundle` (`docs/LOGGING.md` lists its contents).
2. Note the exact command, the interpreter (`python -V`), and the commit (`git rev-parse --short HEAD`).
3. Open the issue with all three. A report without a bundle usually costs a round trip.

Nothing here asks you to move the dog. If a fix needs motion, it belongs to `docs/HARDWARE_TEST.md`,
and it needs a human watching.

