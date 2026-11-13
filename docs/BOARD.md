# Board and Profile

Status: **reference** — which Raspberry Pi this runs on, which HAT it needs, and what the profile
actually changes.
Pairs with: `src/houndmind_ai/board/detect.py` (the detector), `config/settings.jsonc` §profiles (the
overrides), `docs/INSTALL.md` §Supported boards (the installation rules)

Two different things share the word "board" here: the **Raspberry Pi** (detected in software) and the
**Robot HAT** seated on it (not visible to the runtime at all). They have separate rules.

## Contents

1. [Which Pi](#1-which-pi)
2. [Which HAT](#2-which-hat)
3. [How the profile is resolved](#3-how-the-profile-is-resolved)
4. [What each profile changes](#4-what-each-profile-changes)
5. [Overriding it](#5-overriding-it)
6. [Where to see the answer](#6-where-to-see-the-answer)

---

## 1. Which Pi

| Board | Supported | Notes |
|---|---|---|
| Pi 5 | yes | Software-compatible with the PiDog code; needs a HAT V5 (§2). |
| Pi 4 | yes | The reference board for every measurement in this repo. |
| Pi 3 and older | **no** | Refused by the installer and at config load. `v2026.01.18` is the last release that ran on one. |
| No device tree (CI, workstation, container) | n/a | Classified `unknown`; the runtime proceeds as if it were a `pi4`. |

`board/detect.py` reads the model string from the device tree once at boot and classifies it into
`pi4`, `pi5`, `unsupported` or `unknown`. It holds no policy — it answers one question. `classify_model`
is a pure function, so every branch is reachable on a workstation (`tests/test_board_detect.py`).

## 2. Which HAT

The runtime **cannot** see which Robot HAT is fitted, so this is not a config key — it is a power fact.

- **Robot HAT V4** supplies 5V/3A. Fine on a Pi 4.
- **Robot HAT V5** supplies 5V/5A, which is what a Pi 5 requires.

A Pi 5 on a V4 can shut down mid-run, and some V4 owners report WiFi trouble; treat that combination
as a bench test, not an edition. `docs/INSTALL.md` §"A Pi 5 edition is a board *and* a HAT" is the full
statement.

## 3. How the profile is resolved

`profile` ships as `auto` (`config/settings.jsonc:9`), which means "use what the device tree says".
Resolution order:

1. `HOUNDMIND_PROFILE` in the environment, if set.
2. `profile` in `config/settings.jsonc`, if it is not `auto`.
3. The detected board: `pi4` or `pi5`; `unsupported` is a load-time error.
4. `unknown` resolves to `pi4` — the conservative profile, because a machine with no device tree is
   most likely CI or a workstation.

An explicit name that does not exist is a load-time error with a did-you-mean. Setting
`HOUNDMIND_PROFILE` to a name that disagrees with the hardware is allowed — `/meta` then reports both
the real board and the chosen profile, so the disagreement is visible rather than hidden
(`main.py::publish_identity`).

The installer carries a mirror of this logic (`scripts/installer_core.py::detect_pi_class`) because it
runs before the package exists; `tests/test_board_detect.py` asserts that the two agree.

## 4. What each profile changes

| Setting | `pi4` | `pi5` | Base file |
|---|---|---|---|
| `loop.tick_hz` | `10` | `10` | `5` |
| `loop.max_cycles` | `null` | `null` | `null` |
| `modules.vision_pi4.enabled` | `true` | `true` | `false` |
| `modules.face_recognition`, `semantic_labeler`, `slam_pi4` | `false` | `false` | `false` |
| `settings.navigation.scan_interval_s` | `0.3` | `0.3` | as shipped |
| `settings.vision_pi4.frame_interval_s` | `0.1` | `0.1` | `0.2` |
| `settings.performance.health_temp_warn_c` | as shipped | `78.0` | `70.0` |
| `settings.performance.health_gpu_temp_warn_c` | as shipped | `80.0` | as shipped |

Two things worth noticing, because they surprise people:

- **The Pi 5 is not faster.** It carries the same cadence as the Pi 4 on purpose: a faster loop is a
  claim that needs a measurement, and nothing has been measured on a Pi 5 yet. That comment is in
  `config/settings.jsonc` next to the values.
- **The profile enables `vision_pi4` and nothing else.** Everything optional stays off until you turn
  it on and validate it on the bench. A Pi 5 on the `pi5` profile still has no face recognition, no
  labeler and no SLAM.

The thermal thresholds are the one genuinely board-specific number: a Pi 5 idles near 65 °C with no
cooler and throttles at 80 °C, so the generic 70 °C warning marks a healthy board as degraded and
pulls the `throttle_scans` lever for no reason.

## 5. Overriding it

```bash
HOUNDMIND_PROFILE=pi4 python -m houndmind_ai      # pretend, for a bench test
```

Or set `"profile": "pi4"` in `config/settings.jsonc`. Do not pin a profile to work around a detection
bug — report the bug, because the cached profile then follows the machine rather than the board, and
the next person to clone the repo inherits the lie.

## 6. Where to see the answer

`GET /api/v1/meta` is unauthenticated and reports both:

```json
{ "board": "pi4", "profile": "pi4", "device_id": "...", "capabilities": { } }
```

`board` is the hardware fact; `profile` is the decision. The runtime logs the pair once at start
(`Board … (…), profile …`), which is the first line to read when a feature behaves as if it were
on another machine.
