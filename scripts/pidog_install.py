#!/usr/bin/env python3
"""
PiDog Guided Installer for Raspberry Pi

This script helps you install SunFounder vendor modules (Robot HAT, Vilib, PiDog),
configure I2S audio, run quick demos, and install HoundMind dependencies for
Pi 4/5 (full) or Pi 3B (lite). It detects the Pi model/architecture and offers
an interactive menu. Safe to run multiple times; it will skip existing steps
where possible.

Run on the Raspberry Pi terminal:
  python3 scripts/pidog_install.py

Note: It will call `sudo` for actions that require elevated privileges.
"""

import os
import sys
import shutil
import subprocess
import textwrap
from pathlib import Path


HOME = Path.home()
REPO_ROOT = Path(__file__).resolve().parents[1]


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def read_file(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def detect_pi_model() -> str:
    # Primary: /proc/device-tree/model
    dt_model = Path("/proc/device-tree/model")
    if dt_model.exists():
        data = dt_model.read_bytes().replace(b"\x00", b"")
        return data.decode(errors="ignore").strip()
    # Fallback: /proc/cpuinfo
    info = read_file(Path("/proc/cpuinfo"))
    for line in info.splitlines():
        if line.lower().startswith("model"):
            return line.split(":", 1)[-1].strip()
    return "Unknown"


def arch() -> str:
    try:
        import platform

        return platform.machine()
    except Exception:
        return "unknown"


def py_version_str() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def run(cmd: str, cwd: Path | None = None) -> int:
    print(f"\n$ {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, cwd=str(cwd) if cwd else None)
        return result.returncode
    except KeyboardInterrupt:
        return 130


def ensure_prereqs():
    print("\nChecking prerequisites (git, python3-pip, setuptools, smbus)...")
    # Attempt a quick install; harmless if already installed
    run("sudo apt update")
    run("sudo apt install -y git python3-pip python3-setuptools python3-smbus")


def git_clone_or_update(url: str, dest: Path, branch: str | None = None) -> None:
    if dest.exists():
        print(f"Repo exists: {dest}. Updating...")
        run(f"git -C {dest} fetch --all --tags")
        if branch:
            run(f"git -C {dest} checkout {branch}")
        run(f"git -C {dest} pull")
    else:
        cmd = f"git clone {url} {dest}"
        if branch:
            cmd = f"git clone -b {branch} {url} {dest}"
        run(cmd)


def install_robot_hat():
    print("\n== Install Robot HAT (2.5.x) ==")
    ensure_prereqs()
    dest = HOME / "robot-hat"
    git_clone_or_update("https://github.com/sunfounder/robot-hat.git", dest, branch="2.5.x")
    run("sudo python3 install.py", cwd=dest)


def install_vilib():
    print("\n== Install Vilib ==")
    ensure_prereqs()
    dest = HOME / "vilib"
    git_clone_or_update("https://github.com/sunfounder/vilib.git", dest, branch=None)
    run("sudo python3 install.py", cwd=dest)


def install_pidog():
    print("\n== Install PiDog ==")
    ensure_prereqs()
    dest = HOME / "pidog"
    git_clone_or_update("https://github.com/sunfounder/pidog.git", dest, branch=None)
    run("sudo python3 setup.py install", cwd=dest)


def repair_vendor_modules():
    print("\n== Repair vendor modules (remove conflicting pip installs, force reinstall) ==")
    # Remove potentially conflicting pip-installed variants first
    # Try both user and system contexts; ignore failures
    cmds = [
        "pip3 uninstall -y robot-hat robot_hat sunfounder-robot-hat || true",
        "sudo -H pip3 uninstall -y robot-hat robot_hat sunfounder-robot-hat || true",
        "pip3 uninstall -y pidog || true",
        "sudo -H pip3 uninstall -y pidog || true",
        "pip3 uninstall -y vilib || true",
        "sudo -H pip3 uninstall -y vilib || true",
    ]
    for c in cmds:
        run(c)
    # Reinstall from vendor sources
    install_robot_hat()
    install_vilib()
    install_pidog()


def setup_i2s():
    print("\n== I2S Audio Setup ==")
    dest = HOME / "robot-hat"
    if not dest.exists():
        print("robot-hat not found at ~/robot-hat; installing first...")
        install_robot_hat()
    # Ensure ALSA utilities are present for volume/test
    run("sudo apt update")
    run("sudo apt install -y alsa-utils")
    # Run vendor setup script
    rc = run("sudo bash i2samp.sh", cwd=dest)
    print("\nNotes:")
    print("- When prompted, type 'y' to continue and allow /dev/zero to run in the background.")
    print("- A reboot is usually required for I2S overlays to take effect.")
    print("- After reboot, use menu option 'Test I2S audio' to set volume and play a test sound.")
    if rc == 0:
        choice = input("Reboot now? [y/N]: ").strip().lower()
        if choice == "y":
            run("sudo reboot")
    else:
        print("i2samp.sh exited with errors. You can re-run option 2 after fixing issues, or continue and try the audio test after a reboot.")


def test_i2s_audio():
    print("\n== Test I2S audio (list devices, set volume, play test) ==")
    # List ALSA playback devices
    run("aplay -l || true")
    # Try to set volume on common controls
    controls = ["Master", "PCM", "Speaker", "Headphone", "Digital"]
    for ctl in controls:
        run(f"amixer -c 0 sset {ctl} 90% || true")
    # Prefer a known sample if available
    sample = Path("/usr/share/sounds/alsa/Front_Center.wav")
    if sample.exists():
        print("Playing Front_Center.wav …")
        run(f"aplay -q {sample}")
    else:
        print("No sample wav found; using a 440Hz sine for ~1s …")
        run("speaker-test -t sine -f 440 -l 1 || true")
    print("\nIf you still hear no sound:")
    print("- Re-run 'I2S audio setup' and choose reboot.")
    print("- Open 'alsamixer' and check the correct card/device; unmute and raise volume.")
    print("- Ensure the I2S amplifier/speaker is wired correctly and powered.")


def run_vendor_demo():
    print("\n== Vendor demo: wake up ==")
    examples = HOME / "pidog" / "examples"
    if not examples.exists():
        print("pidog repo not found; installing first...")
        install_pidog()
    run("sudo python3 1_wake_up.py", cwd=examples)


def servo_zeroing_standard():
    print("\n== Servo zeroing (Standard) ==")
    examples = HOME / "pidog" / "examples"
    if not examples.exists():
        print("pidog repo not found; installing first...")
        install_pidog()
    run("sudo python3 servo_zeroing.py", cwd=examples)


def verify_imports_and_devices():
    print("\n== Verify imports and devices ==")
    code = textwrap.dedent(
        """
        import importlib, os
        mods = ["robot_hat", "vilib", "pidog"]
        for m in mods:
            try:
                importlib.import_module(m)
                print(f"OK: import {m}")
            except Exception as e:
                print(f"FAIL: import {m}: {e}")
        # Deeper diagnostics for robot_hat
        try:
            import robot_hat as rh
            import inspect
            print("robot_hat file:", getattr(rh, "__file__", "<unknown>"))
            has_robot = hasattr(rh, "Robot")
            print("robot_hat has 'Robot':", has_robot)
            if not has_robot:
                print("Hint: A conflicting or outdated robot_hat may be installed via pip. See 'Repair vendor modules' in the installer menu.")
        except Exception as e:
            print("robot_hat diagnostics error:", e)
        print("/dev/i2c-1 exists:", os.path.exists("/dev/i2c-1"))
        """
    )
    run(f"python3 - << 'PY'\n{code}\nPY")
    run("i2cdetect -y 1")


def install_houndmind_pi45():
    print("\n== Install HoundMind deps (Pi 4/5 full) ==")
    run("sudo apt update && sudo apt install -y portaudio19-dev python3-dev cmake build-essential libopenblas-dev liblapack-dev")
    run("python3 -m pip install --upgrade pip")
    run(f"pip3 install -r {REPO_ROOT / 'requirements.txt'}")


def install_houndmind_pi3():
    print("\n== Install HoundMind deps (Pi 3B lite) ==")
    run("sudo apt update && sudo apt install -y portaudio19-dev python3-dev")
    run("python3 -m pip install --upgrade pip")
    run(f"pip3 install -r {REPO_ROOT / 'requirements-lite.txt'}")


def detect_defaults() -> tuple[str, str]:
    model = detect_pi_model()
    a = arch()
    return model, a


def print_header():
    model, a = detect_defaults()
    print("=" * 60)
    print("PiDog Guided Installer")
    print("=" * 60)
    print(f"Model : {model}")
    print(f"Arch  : {a}")
    print(f"Python: {py_version_str()}")
    print(f"Repo  : {REPO_ROOT}")
    # Friendly hints for common envs
    try:
        is_32bit = sys.maxsize < 2**32
        py_major, py_minor = sys.version_info[:2]
        if is_32bit:
            print("\nNote: 32-bit OS detected. Heavy ML packages (mediapipe/tensorflow/tflite-runtime) are not supported here—use the Pi 3B lite path (option 7).")
        if py_major >= 3 and py_minor >= 13:
            print("Note: Python 3.13 detected. Some third-party wheels (e.g., tflite-runtime/mediapipe) may be unavailable; they are optional and will be skipped.")
    except Exception:
        pass
    print("\nMenu:")
    print("  1) Install vendor modules (Robot HAT 2.5.x, Vilib, PiDog)")
    print("  2) I2S audio setup")
    print("  3) Run vendor wake-up demo")
    print("  4) Servo zeroing (Standard)\n     - PiDog V2: use the Robot HAT zeroing button")
    print("  5) Verify imports and I2C devices")
    print("  6) Install HoundMind deps: Pi 4/5 (full)")
    print("  7) Install HoundMind deps: Pi 3B (lite)")
    print("  8) Launch CanineCore (main)")
    print("  9) Launch CanineCore control menu")
    print(" 10) Launch PackMind (optionally choose preset)")
    print(" 11) Test I2S audio (volume + test sound)")
    print(" 12) Repair vendor modules (clean pip + reinstall Robot HAT/Vilib/PiDog)")
    print("  0) Exit")


def main():
    if not is_linux():
        print("This installer is intended to run on Raspberry Pi (Linux). Exiting.")
        return 1

    while True:
        print_header()
        try:
            choice = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return 0

        if choice == "1":
            install_robot_hat()
            install_vilib()
            install_pidog()
        elif choice == "2":
            setup_i2s()
        elif choice == "3":
            run_vendor_demo()
        elif choice == "4":
            servo_zeroing_standard()
        elif choice == "5":
            verify_imports_and_devices()
        elif choice == "6":
            install_houndmind_pi45()
        elif choice == "7":
            install_houndmind_pi3()
        elif choice == "8":
            # Launch CanineCore (main)
            run("python3 main.py", cwd=REPO_ROOT)
        elif choice == "9":
            # Launch CanineCore interactive control
            run("python3 canine_core/control.py", cwd=REPO_ROOT)
        elif choice == "10":
            # Launch PackMind, optional preset
            preset = input("Preset (blank=default, e.g., pi3/advanced): ").strip()
            if preset:
                run(f"PACKMIND_CONFIG={preset} python3 packmind/orchestrator.py", cwd=REPO_ROOT)
            else:
                run("python3 packmind/orchestrator.py", cwd=REPO_ROOT)
        elif choice == "11":
            test_i2s_audio()
        elif choice == "12":
            repair_vendor_modules()
        elif choice == "0":
            print("Bye.")
            return 0
        else:
            print("Unknown option.")


if __name__ == "__main__":
    sys.exit(main())
