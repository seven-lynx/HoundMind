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


def python_version_tuple(python: Path) -> tuple[int, int] | None:
    try:
        out = subprocess.check_output(
            [str(python), "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"]
        )
        parts = out.decode("utf-8").strip().split()
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        return None
    return None


def is_supported_python(version: tuple[int, int]) -> bool:
    return (version[0] == 3 and version[1] in (10, 11))


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
        "python3-spidev",
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
        "--force-recreate-venv",
        action="store_true",
        help="Delete and recreate the venv even if it already exists",
    )
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

    if sys.version_info < (3, 10) or sys.version_info >= (3, 12):
        print(
            "Unsupported Python version: "
            f"{sys.version_info.major}.{sys.version_info.minor}. "
            "Use Python 3.10 or 3.11 (set PYTHON=python3.10 or PYTHON=python3.11)."
        )
        return 2

    repo_root = Path(__file__).resolve().parents[1]
    venv_path = repo_root / args.venv

    # Create cache root early so temporary files and cloned repos can be stored
    cache_root = repo_root / ".cache" / "houndmind_deps"
    cache_root.mkdir(parents=True, exist_ok=True)

    if not args.skip_venv:
        python, pip = venv_paths(venv_path)
        if venv_path.exists():
            if args.force_recreate_venv:
                print("Forcing venv recreation...")
                shutil.rmtree(venv_path, ignore_errors=True)
            venv_version = python_version_tuple(python)
            current_version = (sys.version_info.major, sys.version_info.minor)
            if venv_version is None:
                print("Existing venv is invalid or missing Python; recreating...")
                shutil.rmtree(venv_path, ignore_errors=True)
            elif not is_supported_python(venv_version):
                print(
                    "Existing venv uses unsupported Python "
                    f"{venv_version[0]}.{venv_version[1]}; recreating with "
                    f"{current_version[0]}.{current_version[1]}..."
                )
                shutil.rmtree(venv_path, ignore_errors=True)
            elif venv_version != current_version:
                print(
                    "Existing venv uses Python "
                    f"{venv_version[0]}.{venv_version[1]} but installer is "
                    f"running on {current_version[0]}.{current_version[1]}; recreating..."
                )
                shutil.rmtree(venv_path, ignore_errors=True)

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
    # Install system deps early when requested or needed for full installs.
    if not is_windows() and (args.auto_system_deps or preset == "full" or should_build_rtabmap):
        code = ensure_system_deps_linux()
        if code != 0:
            return code

    code = run([str(pip), "install", "--upgrade", "pip"])
    if code != 0:
        return code
    print(f"Detected platform: {pi_class}. Using preset: {preset}.")
    # Avoid pip failing on 'rtabmap-py' when we will build it or when user
    # explicitly opts out of RTAB-Map.
    req_to_install = req
    if (should_build_rtabmap or args.no_rtabmap) and req.exists():
        content = req.read_text(encoding="utf-8")
        if "rtabmap-py" in content:
            tmp_req = cache_root / "requirements-noslam.txt"
            lines = [l for l in content.splitlines() if "rtabmap-py" not in l]
            tmp_req.write_text("\n".join(lines), encoding="utf-8")
            req_to_install = tmp_req

    code = run([str(pip), "install", "-r", str(req_to_install)])
    if code != 0:
        if preset == "full":
            print(
                "Warning: full preset dependencies failed to install. "
                "Continuing with lite dependencies; optional modules may be unavailable."
            )
            fallback_req = repo_root / "requirements-lite.txt"
            code = run([str(pip), "install", "-r", str(fallback_req)])
            if code != 0:
                return code
        else:
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
            if not python_can_import(python, "pidog"):
                print("Installing SunFounder PiDog dependencies...")

                # Some vendor packages (robot_hat/pidog) rely on `gpiozero` and
                # SMBus Python bindings. Ensure these packages are available
                # inside the project's venv so imports succeed during verification.
                code = run([str(pip), "install", "gpiozero", "RPi.GPIO", "smbus2", "spidev"])
                if code != 0:
                    print("Warning: failed to install gpiozero/RPi.GPIO; continuing and attempting vendor installs.")
                # Ensure a `smbus` import is available. Some vendor code
                # imports `smbus` (not `smbus2`). Try installing a PyPI
                # package named `smbus` first; if unavailable, create a
                # lightweight shim in the venv that re-exports `smbus2`.
                if not python_can_import(python, "smbus"):
                    code = run([str(pip), "install", "smbus"])
                    if code != 0 or not python_can_import(python, "smbus"):
                        try:
                            out = subprocess.check_output([
                                str(python), "-c",
                                "import site,sys; print(site.getsitepackages()[0])",
                            ])
                            site_packages = Path(out.decode("utf-8").strip())
                            shim = site_packages / "smbus.py"
                            shim_text = "from smbus2 import *\nfrom smbus2 import SMBus\n"
                            shim.write_text(shim_text, encoding="utf-8")
                            print(f"Wrote smbus shim to {shim}")
                        except Exception as exc:  # noqa: BLE001
                            print("Warning: unable to create smbus shim:", exc)

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

    # The verifier script historically lived in `tools/`, but in the current
    # layout it may be under `src/tools/`. Search known locations and run
    # the verifier if present; otherwise skip verification gracefully.
    verifier_candidates = [
        repo_root / "tools" / "installer_verify.py",
        repo_root / "src" / "tools" / "installer_verify.py",
    ]
    verifier = None
    for p in verifier_candidates:
        if p.exists():
            verifier = p
            break
    if verifier is None:
        print("Installer verifier not found; skipping verification step.")
        return 0
    return run([str(python), str(verifier), "--preset", preset])


if __name__ == "__main__":
    raise SystemExit(main())
