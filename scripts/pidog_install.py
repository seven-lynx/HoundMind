#!/usr/bin/env python3
"""PiDog + HoundMind installer (Pi3 focused).

This script installs the official SunFounder PiDog dependencies if missing,
then installs HoundMind in the same Python environment. It favors a local
virtual environment by default to reduce risk to the system Python.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd)


def is_windows() -> bool:
    return os.name == "nt"


def detect_pi_class() -> str:
    """Return 'pi3', 'pi4', or 'unknown' based on platform hints."""
    try:
        model = Path("/proc/device-tree/model").read_text(encoding="utf-8").lower()
        if "raspberry pi 3" in model:
            return "pi3"
        if "raspberry pi 4" in model or "raspberry pi 5" in model:
            return "pi4"
    except Exception:
        pass
    machine = platform.machine().lower()
    if "armv7" in machine or "armv6" in machine:
        return "pi3"
    if "aarch64" in machine or "armv8" in machine:
        return "pi4"
    return "unknown"


def venv_paths(venv_path: Path) -> tuple[Path, Path]:
    if is_windows():
        return venv_path / "Scripts" / "python.exe", venv_path / "Scripts" / "pip.exe"
    return venv_path / "bin" / "python", venv_path / "bin" / "pip"


def python_can_import(python: Path, module: str) -> bool:
    code = run([str(python), "-c", f"import {module}"])
    return code == 0


def ensure_system_deps_linux() -> int:
    if shutil.which("apt-get") is None:
        print("apt-get not found; skipping system dependency install")
        return 0
    code = run(["sudo", "apt-get", "update"])
    if code != 0:
        return code
    return run(
        [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "git",
            "python3-pip",
            "python3-setuptools",
            "python3-smbus",
        ]
    )


def clone_or_update(repo_url: str, dest: Path, branch: str | None = None) -> int:
    if dest.exists():
        code = run(["git", "-C", str(dest), "fetch", "--all", "--prune"])
        if code != 0:
            return code
        target = f"origin/{branch}" if branch else "origin/master"
        return run(["git", "-C", str(dest), "reset", "--hard", target])
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["-b", branch]
    cmd += [repo_url, str(dest)]
    return run(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="PiDog + HoundMind installer")
    parser.add_argument("--venv", default=".venv", help="Path to virtualenv")
    parser.add_argument("--skip-venv", action="store_true", help="Skip venv creation")
    parser.add_argument(
        "--preset",
        choices=["auto", "lite", "full"],
        default="auto",
        help="Install preset (auto detects Pi model)",
    )
    parser.add_argument(
        "--skip-pidog", action="store_true", help="Skip PiDog dependency install"
    )
    parser.add_argument(
        "--auto-system-deps",
        action="store_true",
        help="Auto-install system deps (Linux)",
    )
    parser.add_argument(
        "--pidog-repo", default="https://github.com/sunfounder/pidog.git"
    )
    parser.add_argument(
        "--robot-hat-repo", default="https://github.com/sunfounder/robot-hat.git"
    )
    parser.add_argument("--robot-hat-branch", default="v2.0")
    parser.add_argument(
        "--vilib-repo", default="https://github.com/sunfounder/vilib.git"
    )
    parser.add_argument("--vilib-branch", default="picamera2")
    parser.add_argument(
        "--run-i2samp", action="store_true", help="Run i2samp.sh after installing pidog"
    )
    args = parser.parse_args()

    if sys.version_info < (3, 9):
        print("Python 3.9+ required")
        return 2

    repo_root = Path(__file__).resolve().parents[1]
    venv_path = repo_root / args.venv

    if not args.skip_venv:
        if not venv_path.exists():
            code = run([sys.executable, "-m", "venv", str(venv_path)])
            if code != 0:
                return code
        python, pip = venv_paths(venv_path)
    else:
        python = Path(sys.executable)
        pip = Path(sys.executable).with_name("pip")

    if not pip.exists():
        print("pip not found; activate your environment first")
        return 2

    pi_class = detect_pi_class()
    # Force full preset for Pi4/5, always install all dependencies for all modules that can run
    if pi_class == "pi4":
        preset = "full"
    elif pi_class == "pi3":
        preset = "lite"
    else:
        preset = args.preset if args.preset != "auto" else "lite"
    if preset == "full" and pi_class == "pi3":
        print("Pi 3 detected: full preset is not supported. Use --preset lite.")
        return 2

    req = repo_root / "requirements-lite.txt"
    if preset == "full":
        full_req = repo_root / "requirements.txt"
        if not full_req.exists():
            print("requirements.txt not found; full preset is unavailable.")
            return 2
        req = full_req
    code = run([str(pip), "install", "--upgrade", "pip"])
    if code != 0:
        return code
    print(f"Detected platform: {pi_class}. Using preset: {preset}.")
    code = run([str(pip), "install", "-r", str(req)])
    if code != 0:
        return code
    # Always install Flask and run model downloader for Pi4/5
    if pi_class == "pi4":
        code = run([str(pip), "install", "flask"])
        if code != 0:
            return code
        model_dl = repo_root / "tools" / "download_opencv_models.py"
        if model_dl.exists():
            code = run([str(python), str(model_dl)])
            if code != 0:
                print("Warning: Model downloader failed, but continuing.")

    if not args.skip_pidog:
        if is_windows():
            print(
                "PiDog hardware dependencies are not supported on Windows. Skipping PiDog install."
            )
        else:
            if args.auto_system_deps:
                code = ensure_system_deps_linux()
                if code != 0:
                    return code

            cache_root = repo_root / ".cache" / "houndmind_deps"
            cache_root.mkdir(parents=True, exist_ok=True)

            if not python_can_import(python, "pidog"):
                print("Installing SunFounder PiDog dependencies...")

                robot_hat_path = cache_root / "robot-hat"
                code = clone_or_update(
                    args.robot_hat_repo, robot_hat_path, args.robot_hat_branch
                )
                if code != 0:
                    return code
                code = run([str(pip), "install", str(robot_hat_path)])
                if code != 0:
                    return code

                vilib_path = cache_root / "vilib"
                code = clone_or_update(args.vilib_repo, vilib_path, args.vilib_branch)
                if code != 0:
                    return code
                code = run([str(pip), "install", str(vilib_path)])
                if code != 0:
                    return code

                pidog_path = cache_root / "pidog"
                code = clone_or_update(args.pidog_repo, pidog_path)
                if code != 0:
                    return code
                code = run([str(pip), "install", str(pidog_path)])
                if code != 0:
                    return code

                i2samp = pidog_path / "i2samp.sh"
                if args.run_i2samp and i2samp.exists():
                    code = run(["sudo", "bash", str(i2samp)])
                    if code != 0:
                        return code
            else:
                print("PiDog library detected; skipping PiDog install.")

    code = run([str(pip), "install", "-e", str(repo_root)])
    if code != 0:
        return code

    verifier = repo_root / "tools" / "installer_verify.py"
    return run([str(python), str(verifier), "--preset", preset])


if __name__ == "__main__":
    raise SystemExit(main())
