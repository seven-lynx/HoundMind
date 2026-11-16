# Headless install and bring-up over SSH

Status: **guide** — the path from a flashed card to a reachable console, with no monitor and no
keyboard on the dog. Written against Raspberry Pi OS **Bookworm 64-bit** on a Pi 4B with a PiDog HAT,
and every timing in it was measured on that bench.
Pairs with: `INSTALL.md` (the reference), `HARDWARE_TEST.md` (what to run once it is up),
`TROUBLESHOOTING.md` (when a step says no).

This is the longer version of the eight-step path in `INSTALL.md`: the same order, plus the traps that
cost real time the first time. Read it before the first install, not after.

## Contents

- [1. What you need](#1-what-you-need)
- [2. Get on the box](#2-get-on-the-box)
- [3. Enable the two interfaces](#3-enable-the-two-interfaces)
- [4. Install](#4-install)
- [5. The service](#5-the-service)
- [6. Prove it without moving the dog](#6-prove-it-without-moving-the-dog)
- [7. Reach the console](#7-reach-the-console)
- [8. When you have to look at a log](#8-when-you-have-to-look-at-a-log)
- [9. The traps](#9-the-traps)
- [10. What done looks like](#10-what-done-looks-like)

---

## 1. What you need

- A Pi 4 or Pi 5, Raspberry Pi OS **Bookworm 64-bit** on the card. The installer refuses anything else
  with one line; that is deliberate, not a bug (Trixie ships Python 3.13 and was never validated).
- The HAT seated on the 40-pin header, the pack charged, and the camera ribbon if you fitted one.
- The dog **on blocks** with the legs hanging free. Nothing below moves it, but the first thing that
  does should happen with the legs off the ground.
- The address of the Pi on your LAN (`hostname -I` on it, or your router's client list).

## 2. Get on the box

Bookworm enables SSH with the `pi` user and a password you choose in the imager. Keys are better than
a password, and only need doing once:

```bash
ssh-keygen -t ed25519 -C houndmind-bench        # on your laptop, if you do not have one
ssh-copy-id pi@192.168.8.243                    # the Pi's address
ssh pi@192.168.8.243
```

Add an alias so you stop typing the address - and so a lease change is one line to fix:

```
Host pidog
    HostName 192.168.8.243
    User pi
    IdentityFile ~/.ssh/id_ed25519
```

**The address can change.** After a reboot the router may hand out a different lease; a full `/24`
sweep that finds nothing does not mean the dog is down (see [§9](#9-the-traps)).

## 3. Enable the two interfaces

Both are off on a fresh image, and `raspi-config`'s non-interactive numbering is **inverted**: `0`
enables, `1` disables.

```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo reboot
```

After the reboot, prove them before installing:

```bash
ls /dev/i2c-1 /dev/spidev0.0
```

Both must exist. **SPI is not optional**: the sound sensor (`dog.ears`) is an SPI device and opens the
bus in its constructor. With SPI off, the vendor swallows the exception, the dog reports
`sound_valid: false` for the whole session, and `hardware_checkup` exits 1 - which reads as a dead
sensor rather than a missing prerequisite (#204). The installer runs both commands for you, but it
cannot reboot, so do this first and reboot once.

## 4. Install

```bash
git clone https://github.com/seven-lynx/HoundMind.git ~/HoundMind
cd ~/HoundMind
bash scripts/install_houndmind.sh                     # preset auto: Pi 4 -> full, Pi 5 -> lite
```

Or pick a preset explicitly. **`lite` is the safer first install** - it pulls the HAT bindings and the
package without building `dlib`, OpenCV wheels and a voice stack:

```bash
bash scripts/install_houndmind.sh --preset lite --auto-system-deps
```

What the installer now checks before it downloads anything (it prints every one of these):

```
Free space: 49.0 GB at /home/pi/HoundMind
Preflight: OK
```

- **free space** - it refuses under 2 GB, because a full install that fills the card is worse than no
  install;
- **pack health** - `vcgencmd get_throttled` bits 16-18 record what happened *since boot*, so a pack
  that browned out earlier will do it again, and an install is a long write to the card;
- **camera node** - a warning only: `vision_pi4` ships off (see
  [§9](#9-the-traps)).

It then enables I2C/SPI, installs apt packages (including `python3-picamera2`), creates the venv with
`--system-site-packages`, installs `robot-hat`, `vilib` and `pidog` from the SunFounder repos, installs
HoundMind, installs and **enables** `houndmind.service`, and runs its own verification:

```
Installer check: OK
  pidog: OK
  houndmind_ai: OK
```

Use `--no-service` if you would rather decide about the unit yourself.

## 5. The service

The installer enables the unit but does **not** start it - starting the runtime is your decision,
because the shipped config starts `scanning`, which moves the head.

```bash
sudo systemctl start houndmind
systemctl status houndmind            # active (running)
sudo journalctl -u houndmind -n 50    # the first start, in its own words
```

**The rule: the service resumes; motion never does.** After a reboot the modules come back and the dog
stays still, because `motion_command` and the intent board are context-only and every intent expires.
A routine that was mid-run is lost rather than replayed. The next start says how the previous one
ended (`~/.houndmind/session.json`, exposed as `/state` → `session`).

Stop it the same way a supervisor would:

```bash
sudo systemctl stop houndmind
```

That is SIGTERM: the loop finishes its tick, closes the HAL, and removes its session marker. If it
logged `Runtime stopping: SIGTERM received`, that is the whole clean path working.

## 6. Prove it without moving the dog

```bash
cd ~/HoundMind && source .venv/bin/activate     # or .venv/bin/python -m ...
python -m tools.hardware_checkup --skip-motion
python -m tools.smoke_test
```

Expected, on a correct dog:

```
[checkup] valid: distance=True touch=True sound=True imu=True
[checkup] sensors: all answered
[checkup] Motion skipped.
```

and exit 0 from both. `smoke_test` prints `[smoke] PASS` and a `disabled:` line naming what it
switched off - `scanning` and `vision_pi4` are in that list, so a motionless run really is motionless
(#184, #205).

**If either tool exits 3** and says `the servo bus is owned by pid N (runtime)`, the service is still
running. That is the guard, not a fault: stop the service and re-run (#213).

## 7. Reach the console

The console is served by the dog itself, on port 8420:

```bash
hostname -I                                    # on the Pi: the address to open
curl http://<pi-address>:8420/api/v1/health    # {"status": "ok"} with no token
```

Open `http://<pi-address>:8420` in a browser on the same network and paste the device token from
`~/.houndmind/api_token` (mode 0600, written on first start). Read it on the Pi with `cat`; do not
paste it into a URL, a chat, or a support bundle.

Two optional upgrades, both in `INSTALL.md`: **TLS** so the console is installable and can send
notifications (`api.tls_enabled: true`), and **`api.discovery_enabled`** so the dog is findable by name
instead of address.

## 8. When you have to look at a log

The runtime logs JSON to `logs/houndmind.log`, events to JSONL, and the control plane serves the tail at
`GET /api/v1/logs`. For a crash, the systemd view is the one that survives a reboot *if* the journal is
persistent - and on this image it is not:

```bash
grep Storage /etc/systemd/journald.conf       # Storage=volatile
```

`volatile` keeps the journal in a tmpfs, so the previous boot's log is gone. The drop-in that fixes it,
and the caveat that a hard cut still loses the last few minutes, is in `HARDWARE_TEST.md`
[§2.1](HARDWARE_TEST.md#21-keep-the-previous-boots-log) (#209).

## 9. The traps

| Symptom | What it actually was | Fix |
|---|---|---|
| `fatal: ambiguous argument 'origin/master'`, exit 128, after `vilib` | the installer reset every cached clone to `origin/master`, and SunFounder moved `pidog` to `main` | fixed in the tree (#233); on an older checkout, `rm -rf .cache/houndmind_deps` and re-run |
| `missing module(s): pyaudio`, then the installer stops, blaming the branch | on `--preset lite` nothing installed the four modules `robot_hat` imports | fixed (#180); `--auto-system-deps` gives `pyaudio` the `portaudio19-dev` it needs |
| `import picamera2` fails inside the venv although apt installed it | the venv was created without `--system-site-packages` | the installer warns and prints the recreate command; `rm -rf .venv` and re-run (#215) |
| The runtime refuses to start: `FileNotFoundError: /tmp/....json` | `/tmp` is cleared at boot, so a bench config left there is gone | keep bench configs under `~/`, not `/tmp` |
| SSH times out for minutes after a reboot | the Pi is usually up in 40-90 seconds; the *path* lags (Wi-Fi association, the router's client table, a stale ARP entry) | wait two minutes, then check the router's client list before suspecting the Pi (#231) |
| `hardware_checkup` prints nothing for 150 s | a second process was waiting on a servo bus the runtime owned | fixed: exit 3 with the holder named (#213) |
| `vision_pi4` logs `Picamera2 unavailable` on every start | the module was enabled and the binding was not importable | it ships off now; prove `import picamera2` first (#215) |
| A script refuses to run: `bad interpreter: /bin/bash^M` | the file has CRLF line endings (edited on Windows) | `sed -i 's/\r$//' <file>`, or set `core.autocrlf input` |

## 10. What done looks like

- [ ] `ls /dev/i2c-1 /dev/spidev0.0` both exist.
- [ ] `installer_verify` (run by the installer) ends `Installer check: OK`.
- [ ] `systemctl is-enabled houndmind` is `enabled`.
- [ ] `python -m tools.hardware_checkup --skip-motion` exits 0 with four `True` flags.
- [ ] `python -m tools.smoke_test` prints `[smoke] PASS`.
- [ ] `curl http://<pi-address>:8420/api/v1/health` answers `{"status": "ok"}`.
- [ ] `http://<pi-address>:8420` renders the console after the token is pasted.
- [ ] `sudo reboot`, then the service comes back **and the dog has not moved**.



