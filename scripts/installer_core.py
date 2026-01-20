#!/usr/bin/env python3
"""Internal installer core for HoundMind.

Do not call directly; use scripts/install_houndmind.sh.
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
    # For full/preset installs we include additional build tools and libs
    # commonly required to build OpenCV, dlib, and RTAB-Map from source.
    pkgs = [
        "git",
        "python3-pip",
        "python3-setuptools",
        "python3-smbus",
        "build-essential",
        "cmake",
        "g++",
        "python3-dev",
        "libatlas-base-dev",
        "libopenblas-dev",
        "liblapack-dev",
        "libjpeg-dev",
        "libtiff-dev",
        "libavcodec-dev",
        "libavformat-dev",
        "libswscale-dev",
        "libv4l-dev",
        "libxvidcore-dev",
        "libx264-dev",
        "libgtk-3-dev",
        "libasound2-dev",
        "libportaudio2",
        "portaudio19-dev",
        "libboost-all-dev",
        "libeigen3-dev",
        "libusb-1.0-0-dev",
        "libsqlite3-dev",
        "libopenni2-dev",
        "libproj-dev",
        "pkg-config",
    ]
    return run(["sudo", "apt-get", "install", "-y"] + pkgs)


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


def build_rtabmap(cache_root: Path, pip: Path, python: Path) -> int:
    """Clone, build, and install RTAB-Map and its Python bindings into the active env.

    Returns 0 on success, non-zero on failure.
    """
    rtabmap_path = cache_root / "rtabmap"
    code = clone_or_update("https://github.com/introlab/rtabmap.git", rtabmap_path)
    if code != 0:
        return code

    build_dir = rtabmap_path / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    # Configure with Python bindings enabled
    code = run(
        [
            "cmake",
            "..",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DWITH_PYTHON=ON",
            f"-DPYTHON_EXECUTABLE={str(python)}",
        ]
    )
    if code != 0:
        return code
    code = run(["make", "-j", str(os.cpu_count() or 1)])
    if code != 0:
        return code
    code = run(["sudo", "make", "install"])
    if code != 0:
        return code

    # Install Python bindings (use pip from the active environment)
    rtabmap_python = rtabmap_path / "python"
    if rtabmap_python.exists():
        code = run([str(pip), "install", str(rtabmap_python)])
        if code != 0:
            return code
    else:
        # Fallback: try setup.py install
        py_dir = rtabmap_path / "python"
        if py_dir.exists():
            code = run([str(python), str(py_dir / "setup.py"), "build"])
            if code != 0:
                return code
            code = run(["sudo", str(python), str(py_dir / "setup.py"), "install"])
            if code != 0:
                return code

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="HoundMind installer (internal core)")
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
        "--build-rtabmap",
        action="store_true",
        help="Build and install RTAB-Map (rtabmap) from source (Pi4 only)",
    )
    parser.add_argument(
        "--no-rtabmap",
        action="store_true",
        help="Do not build or install RTAB-Map during this install",
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

    # Create cache root early so temporary files and cloned repos can be stored
    cache_root = repo_root / ".cache" / "houndmind_deps"
    cache_root.mkdir(parents=True, exist_ok=True)

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

    if preset == "full" and sys.version_info >= (3, 12):
        print(
            "Warning: Python 3.12+ may lack Pi wheels for heavy packages "
            "(face_recognition/dlib, pyaudio, rtabmap-py). "
            "If installs fail, use Raspberry Pi OS Bookworm (Python 3.11) "
            "or run with --preset lite."
        )

    req = repo_root / "requirements-lite.txt"
    # Auto-build RTAB-Map for Pi4 full preset, or when explicitly requested.
    should_build_rtabmap = args.build_rtabmap or (pi_class == "pi4" and preset == "full")
    # Allow explicit opt-out
    if args.no_rtabmap:
        should_build_rtabmap = False
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
    # If we're going to build RTAB-Map, avoid pip failing on 'rtabmap-py'
    # by excluding it from the automatic requirements installation.
    req_to_install = req
    if should_build_rtabmap and req.exists():
        content = req.read_text(encoding="utf-8")
        if "rtabmap-py" in content:
            tmp_req = cache_root / "requirements-noslam.txt"
            lines = [l for l in content.splitlines() if "rtabmap-py" not in l]
            tmp_req.write_text("\n".join(lines), encoding="utf-8")
            req_to_install = tmp_req

    code = run([str(pip), "install", "-r", str(req_to_install)])
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
            # Install system deps if requested or required for RTAB-Map build
            if args.auto_system_deps or should_build_rtabmap:
                code = ensure_system_deps_linux()
                if code != 0:
                    return code

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

    # If we intended to build RTAB-Map, perform the build now.
    if should_build_rtabmap:
        print("Building RTAB-Map from source (this may take a long time)...")
        code = build_rtabmap(cache_root, pip, python)
        if code != 0:
            print("RTAB-Map build/install failed; SLAM support may be unavailable.")

    verifier = repo_root / "tools" / "installer_verify.py"
    return run([str(python), str(verifier), "--preset", preset])


if __name__ == "__main__":
    raise SystemExit(main())
