# HoundMind Quickstart

Status: **guide** — from a flashed SD card to a dog that answers, without moving it. Ten minutes if
the install goes well.
Pairs with: `docs/INSTALL.md` (the long version, and every failure path), `docs/HARDWARE_TEST.md`
(the full six-step bench ladder this page abbreviates), `docs/LOGGING.md` (when something fails)

Everything here is read-only: **no command on this page moves the dog.** The first motion run is
`docs/HARDWARE_TEST.md` §9, and it is deliberately not on this page.

## Contents

1. [What you need](#1-what-you-need)
2. [The six commands](#2-the-six-commands)
3. [What a pass looks like](#3-what-a-pass-looks-like)
4. [Three things that will bite you](#4-three-things-that-will-bite-you)
5. [Where to go next](#5-where-to-go-next)

---

## 1. What you need

- A **Raspberry Pi 4 or 5** running **Raspberry Pi OS Bookworm (64-bit)**. Pi 3 and older are refused
  by the installer and by the runtime.
- A **Robot HAT** seated on the 40-pin header. On a **Pi 4 a HAT V4 is fine**; on a Pi 5 only a
  **V5** is supported, because the V4 supplies 5V/3A where the Pi 5 wants 5A.
- **I2C enabled** (`sudo raspi-config` → Interface Options → I2C). The camera is optional.
- The PiDog assembled, **blocked up so the legs hang free**, with nothing breakable within one body
  length. Nothing here moves it, but the next guide does.

## 2. The six commands

Run these in order, on the Pi, from the repo root.

```bash
# 1. Install. Reads the board, refuses a Pi 3, installs the vendor libraries too.
bash scripts/install_houndmind.sh

# 2. Prove the environment can import what the runtime imports.
source .venv/bin/activate
python -m tools.installer_verify

# 3. Read every sensor once. --skip-motion is what makes this safe to run anywhere.
python -m tools.hardware_checkup --skip-motion

# 4. Run the loop for a few seconds with motors disabled: sensors, scan, mapping.
python -m tools.smoke_test

# 5. Start the runtime.
python -m houndmind_ai

# 6. In a second shell, read the live snapshot (the token is read from the file, never pasted).
TOKEN=$(cat ~/.houndmind/api_token)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8420/api/v1/state | head -c 400
```

Step 5 keeps running until `Ctrl+C`. Let it exit on its own terms — the module `stop()` hooks run and
the servo bus closes. Do not kill a moving dog with `kill -9`.

## 3. What a pass looks like

| Step | Pass |
|---|---|
| 1 | ends with `Install complete` and the interpreter it used |
| 2 | `Installer check: OK`, exit 0 |
| 3 | five sensor lines with real numbers, and `Motion skipped.` |
| 4 | `[smoke] PASS` |
| 5 | `Board pi4 (…), profile pi4` and one log line per module as it starts |
| 6 | JSON with `"tick"`, `"modules"`, and `distance_valid` / `imu_valid` flags |

## 4. Three things that will bite you

1. **A tool exiting 0 is not a pass.** `tools.hardware_checkup` returns 0 even when every sensor
   failed — the failure shows up as a printed `None`. Read the output; do not trust `echo $?`
   ([#109](https://github.com/seven-lynx/HoundMind/issues/109)).
2. **The first distance reading can be `-1.0` on a healthy dog.** The vendor caches the ultrasonic
   sample and the cache starts at `-1.0` until the sensor thread has taken one
   ([#108](https://github.com/seven-lynx/HoundMind/issues/108)). Re-run step 3 before concluding the
   sensor is dead.
3. **The installer wrapper is stricter than the docs.** `scripts/install_houndmind.sh` currently
   accepts only `python3.10` and `python3.11` and prefers the 3.10 it should refuse, while
   `installer_core.py` and `docs/INSTALL.md` support 3.11–3.13. On Trixie (3.13) step 1 stops with
   "Python 3.10 or 3.11 is required"
   ([#113](https://github.com/seven-lynx/HoundMind/issues/113)). Workaround: name the interpreter —
   `PYTHON=python3.11 bash scripts/install_houndmind.sh` — or use Bookworm, which ships 3.11. The
   wrapper is the defect, not your Pi.

## 5. Where to go next

| Next step | Read |
|---|---|
| Move the dog for the first time, safely and in order | [`HARDWARE_TEST.md`](HARDWARE_TEST.md) |
| Know what each feature does, and how to turn it off | [`FEATURES_GUIDE.md`](FEATURES_GUIDE.md) — start at §29 |
| Open the web app, pair a phone | [`CONTROL_API.md`](CONTROL_API.md) §1 |
| Teach the dog a routine | [`ROUTINES.md`](ROUTINES.md) |
| Write a module | [`HOUNDMIND_PROGRAMMING_GUIDE.md`](HOUNDMIND_PROGRAMMING_GUIDE.md) §2, §14 |
| Something is broken | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
| A term you do not recognise | [`GLOSSARY.md`](GLOSSARY.md) |
