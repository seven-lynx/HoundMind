#!/usr/bin/env python3
"""Internal installer core for HoundMind.

Do not call directly; use scripts/install_houndmind.sh.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

# Named so a Pi 3 owner has somewhere to go. Kept in step with the last tag that shipped Pi 3.
LAST_PI3_RELEASE = "v2026.01.18"

# Every page in `docs/pidog/` is verified against `robot-hat` 2.5.x, and 2.5.x is what `pidog` was
# written for: the v2.0 tree lacks `robot_hat.device` and most of the classes the reference set
# documents, so that default installed an environment this project does not describe (#114).
ROBOT_HAT_BRANCH = "2.5.x"

# What `pidog/pidog.py` imports from `robot_hat`. Installing the tree is not the same as having a
# usable one - `robot_hat/__init__.py` exposes these only when its own sub-dependencies are
# importable - so the installer probes the surface the first action needs (#114).
ROBOT_HAT_PROBE = "from robot_hat import Robot, Pin, Ultrasonic, utils, Music, I2C"

# What `robot_hat/__init__.py` gates its exports on. Three of these are pulled in by nothing else
# the installer installs, and a missing `lgpio` or `pygame` made the probe above fail with an
# ImportError naming `robot_hat` rather than the real culprit - with the probe failing, `pidog` was
# never installed at all (#180). `pyaudio` arrives from `requirements.txt` on the full preset.
ROBOT_HAT_DEPS = ("smbus2", "lgpio", "pyaudio", "pygame")



def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd)


def is_windows() -> bool:
    return os.name == "nt"


_BOARD_RULES: ModuleType | None = None


def board_rules() -> ModuleType:
    """The runtime's own board rule, loaded by path (#31).

    `scripts/` is not a package and this runs before `houndmind_ai` is installed, so the shared
    file cannot be imported the normal way. Loading it is the point: the installer used to keep a
    second copy of the pattern table, the copies answered differently - a Pi 5 went in as a Pi 4 -
    and nothing compared them.
    """
    global _BOARD_RULES
    if _BOARD_RULES is None:
        path = Path(__file__).resolve().parents[1] / "src" / "houndmind_ai" / "board" / "rules.py"
        if not path.is_file():
            raise RuntimeError(
                f"installer is incomplete: {path} is missing, so the board cannot be identified"
            )
        spec = importlib.util.spec_from_file_location("_houndmind_board_rules", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load the board rule from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _BOARD_RULES = module
    return _BOARD_RULES


# What this release was validated against. Trixie ships Python 3.13, which the declared range
# allows, so the interpreter check cannot catch it: the kernel, the camera stack and the vendor
# bindings are what differ, and a half-installed Trixie is worse than a refusal (#2).
SUPPORTED_CODENAMES = ("bookworm",)


def os_codename() -> str | None:
    """`VERSION_CODENAME` from `/etc/os-release`, or None off a Debian-family system."""
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VERSION_CODENAME="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'").lower()
            return value or None
    return None


def ensure_supported_os(allow_unsupported: bool = False) -> int:
    """Refuse an unsupported distribution release with one line, before anything is downloaded.

    The answer to "can I use Trixie?" is a sentence, not a stack trace halfway through an install.
    A workstation or a container has no `/etc/os-release` codename, and that is not a failure - the
    check only speaks when it recognises a release this project does not support.
    """
    codename = os_codename()
    if codename is None or codename in SUPPORTED_CODENAMES:
        return 0
    if allow_unsupported:
        print(
            f"Warning: {codename} is not a supported release "
            f"({', '.join(SUPPORTED_CODENAMES)} only); continuing because you asked."
        )
        return 0
    print(
        f"Unsupported OS: {codename}. This release supports Raspberry Pi OS "
        f"{', '.join(SUPPORTED_CODENAMES)} 64-bit only - see docs/INSTALL.md. "
        "Re-run with --allow-unsupported-os to try anyway."
    )
    return 2


def detect_pi_class(model: str | None = None) -> str:
    """Return 'pi4', 'pi5', 'unsupported' or 'unknown' from the device-tree model.

    The rule itself is `src/houndmind_ai/board/rules.py`, shared with the runtime and loaded by
    path. The word boundaries that file carries are load-bearing: the model string also carries a
    revision, so "Raspberry Pi 4 Model B Rev 1.5" is a Pi 4 and matching a bare digit invents a
    Pi 5.

    ``model`` exists for tests; production passes nothing and the device tree answers.
    """
    if model is None:
        try:
            raw = Path("/proc/device-tree/model").read_bytes()
            model = raw.decode("utf-8", errors="replace")
        except OSError:
            model = ""

    kind = str(board_rules().classify_text(model))
    if kind != "unknown":
        return kind
    if model:
        # A readable device tree means a Raspberry Pi; if the generation is not one we ship for
        # it is a board we dropped (Pi 3 and older) or a new one nobody has tested.
        return "unsupported"

    machine = platform.machine().lower()
    if "armv7" in machine or "armv6" in machine:
        # 32-bit ARM without a readable device tree is a Pi 3 in practice.
        return "unsupported"
    if "aarch64" in machine or "armv8" in machine:
        # Unknown 64-bit ARM: assume the older of the two supported boards. Under-selecting the
        # profile is the safe direction.
        return "pi4"
    return "unknown"


def resolve_preset(pi_class: str, requested: str) -> str:
    """Which preset to install. An explicit `--preset` means the same thing on every board (#29).

    `auto` keeps the documented defaults: `full` on a Pi 4, `lite` everywhere else, because nothing
    has been measured on a Pi 5 yet. This branch used to force `full` on a Pi 4 whatever the flag
    said, so `--preset lite` attempted dlib, opencv and rtabmap that the user had asked to skip.
    """
    if requested != "auto":
        return requested
    return "full" if pi_class == "pi4" else "lite"


def venv_paths(venv_path: Path) -> tuple[Path, Path]:
    if is_windows():
        return venv_path / "Scripts" / "python.exe", venv_path / "Scripts" / "pip.exe"
    return venv_path / "bin" / "python", venv_path / "bin" / "pip"


def python_can_import(python: Path, module: str) -> bool:
    code = run([str(python), "-c", f"import {module}"])
    return code == 0


def missing_modules(python: Path, names: tuple[str, ...]) -> list[str]:
    """Which of `names` this interpreter cannot import.

    The probe answers "`robot_hat` did not import"; this answers "because these are absent". An
    interpreter that cannot run the probe reports every name, because not-checked is not present.
    """
    snippet = (
        "import importlib.util as u\n"
        "missing = []\n"
        "for name in %r:\n"
        "    try:\n"
        "        if u.find_spec(name) is None:\n"
        "            missing.append(name)\n"
        "    except Exception:\n"
        "        missing.append(name)\n"
        "print(','.join(missing))\n"
    ) % (list(names),)
    try:
        out = subprocess.check_output(
            [str(python), "-c", snippet], stderr=subprocess.STDOUT
        )
    except Exception:  # noqa: BLE001 - a probe that cannot run names nothing for certain
        return list(names)
    lines = out.decode("utf-8", "replace").strip().splitlines()
    return [item for item in (lines[-1].split(",") if lines else []) if item]


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
    """The range `pyproject.toml` declares: 3.11 is Bookworm, 3.13 is Trixie.

    This used to accept 3.10 and refuse 3.12+, which was wrong in both directions: pip would
    refuse to install the package on 3.10, and the installer would refuse the interpreter the
    package declares support for.
    """
    return version[0] == 3 and 11 <= version[1] < 14


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
        "libopencv-dev",
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
        # The Pi 4/5 camera binding. It is a Debian package, not a wheel, and it is why the venv is
        # created with `--system-site-packages`: `vision_pi4` imports it, and without it every start
        # logged `Picamera2 unavailable` while the module stayed enabled (#215).
        "python3-picamera2",
        "pkg-config",
    ]
    return run(["sudo", "apt-get", "install", "-y"] + pkgs)


def ensure_interfaces_linux() -> int:
    """Enable I2C and SPI, which the HAT and the sound sensor need (#204).

    `raspi-config nonint` is the supported way to flip these on Bookworm, and its numbering is
    inverted: `0` enables. The change lands in `/boot/firmware/config.txt` and only exists as a
    `/dev` node after a reboot, which an installer must not do on its own - so this prints the
    reminder and carries on.

    The sound sensor is an SPI device: with the interface off, `SoundDirection()` raises and
    `Pidog.__init__` swallows it, so the dog boots, reports `sound_valid: false` forever, and looks
    like a dead sensor rather than a missing prerequisite.
    """
    if shutil.which("raspi-config") is None:
        print("raspi-config not found; enable I2C and SPI by hand (docs/INSTALL.md, Prerequisites)")
        return 0
    for interface in ("i2c", "spi"):
        code = run(["sudo", "raspi-config", "nonint", f"do_{interface}", "0"])
        if code != 0:
            print(f"Could not enable {interface}; enable it by hand (docs/INSTALL.md)")
            return code
    print("I2C and SPI enabled; reboot before they exist as /dev nodes")
    return 0


def ensure_rtabmap_deps_linux() -> int:
    """Attempt to install PCL/VTK packages needed by RTAB-Map. Return apt exit code.

    This is separate from the general system deps install so failures here
    can be handled gracefully by the caller (installer can continue without
    building RTAB-Map).
    """
    if shutil.which("apt-get") is None:
        print("apt-get not found; cannot attempt RTAB-Map system deps install")
        return 1
    # Try installing the essential PCL package and a few VTK candidate packages.
    # Some Debian/Raspberry Pi repos provide different VTK package names across
    # releases, so attempt several alternatives and treat the install as
    # successful if `libpcl-dev` is installed.
    candidates = {
        "pcl": ["libpcl-dev", "libpcl-tools"],
        "vtk": ["libvtk-dev", "libvtk7-dev", "libvtk6-dev", "libvtk9-dev"],
    }
    installed_pcl = False
    # Install PCL-related packages first
    for pkg in candidates["pcl"]:
        print(f"Attempting to install {pkg}...")
        code = run(["sudo", "apt-get", "install", "-y", pkg])
        if code == 0:
            installed_pcl = installed_pcl or (pkg == "libpcl-dev")
    # Try VTK candidates (ignore failures)
    for pkg in candidates["vtk"]:
        print(f"Attempting to install {pkg} (VTK candidate)...")
        _ = run(["sudo", "apt-get", "install", "-y", pkg])

    if installed_pcl:
        print("libpcl-dev installed — RTAB-Map CMake should be able to find PCL.")
        return 0
    print("libpcl-dev not installed; RTAB-Map will not be buildable on this host.")
    return 1


def ensure_pybind11_deps_linux(python: Path, pip: Path) -> int:
    """Ensure pybind11 is available for RTAB-Map CMake (try apt then pip).

    Returns 0 on success, non-zero on failure. Installing `pybind11-dev`
    via apt is preferred because it provides the CMake config files; if
    that fails, attempt to install `pybind11` into the venv via pip as a
    fallback (may not provide CMake integration on all platforms).
    """
    if shutil.which("apt-get") is not None:
        print("Attempting to install pybind11-dev via apt...")
        code = run(["sudo", "apt-get", "install", "-y", "pybind11-dev"])
        if code == 0:
            print("pybind11-dev installed via apt")
            return 0
        print("pybind11-dev apt install failed; attempting pip fallback...")
    else:
        print("apt-get not available; attempting pip install for pybind11")

    # Pip fallback: install into the active venv
    code = run([str(pip), "install", "pybind11"]) if pip.exists() else run([str(python), "-m", "pip", "install", "pybind11"])  # type: ignore[assignment]
    if code == 0:
        print("pybind11 installed via pip (pip fallback).")
        return 0
    print("Failed to install pybind11 via apt or pip.")
    return 1


def venv_sees_system_packages(venv_path: Path) -> bool:
    """Whether this venv was created with `--system-site-packages` (#215)."""
    try:
        text = (venv_path / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        if line.lower().replace(" ", "").startswith("include-system-site-packages="):
            return line.split("=", 1)[1].strip().lower() == "true"
    return False


def install_service_unit(repo_root: Path, python: Path) -> int:
    """Install and enable `houndmind.service` from `packaging/systemd/` (#211).

    The template carries placeholders rather than a hardcoded account, because the checkout path and
    the interpreter are things only the installer knows. It is `enable`, not `enable --now`: an
    install is not the moment to open the servo bus, and the operator decides when the dog comes
    back on its own.

    A machine without systemd is told and skipped - the runtime still starts by hand, and failing an
    install over a supervision layer would be the wrong trade.
    """
    if shutil.which("systemctl") is None:
        print("systemctl not found; skipping the service unit")
        return 0
    template = repo_root / "packaging" / "systemd" / "houndmind.service"
    if not template.exists():
        print(f"Service template not found at {template}; skipping the service unit")
        return 0

    text = template.read_text(encoding="utf-8")
    text = text.replace("@HOUNDMIND_USER@", getpass.getuser())
    text = text.replace("@HOUNDMIND_ROOT@", str(repo_root))
    text = text.replace("@HOUNDMIND_PYTHON@", str(python))

    staged = Path(tempfile.mkstemp(suffix=".service")[1])
    try:
        staged.write_text(text, encoding="utf-8")
        code = run(
            [
                "sudo",
                "install",
                "-m",
                "0644",
                str(staged),
                "/etc/systemd/system/houndmind.service",
            ]
        )
    finally:
        with contextlib.suppress(OSError):
            staged.unlink()
    if code != 0:
        return code
    code = run(["sudo", "systemctl", "daemon-reload"])
    if code != 0:
        return code
    code = run(["sudo", "systemctl", "enable", "houndmind.service"])
    if code == 0:
        print("Service installed and enabled; start it with: sudo systemctl start houndmind")
    return code


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
    # Configure with Python bindings enabled. Run CMake and make inside the
    # build directory so relative paths like ".." resolve to the source dir.
    old_cwd = Path.cwd()
    try:
        os.chdir(build_dir)
        # Ensure pybind11 CMake integration is available. Prefer an installed
        # pybind11 that exposes CMake config files; try to detect the cmake
        # dir via `python -m pybind11 --cmakedir`. If missing, attempt to
        # install pybind11 into the active venv and re-check.
        pybind11_dir = None
        try:
            out = subprocess.check_output([str(python), "-m", "pybind11", "--cmakedir"], stderr=subprocess.STDOUT)
            pybind11_dir = out.decode("utf-8").strip()
            print(f"Detected pybind11 cmake dir: {pybind11_dir}")
        except Exception:
            print("pybind11 not detected via python -m pybind11; attempting pip install pybind11 into venv...")
            try:
                run([str(pip), "install", "pybind11"])  # best-effort
                out = subprocess.check_output([str(python), "-m", "pybind11", "--cmakedir"], stderr=subprocess.STDOUT)
                pybind11_dir = out.decode("utf-8").strip()
                print(f"Detected pybind11 cmake dir after pip install: {pybind11_dir}")
            except Exception:
                print("pybind11 CMake integration not found; continuing without pybind11_DIR (CMake may still find it system-wide)")
        cmake_cmd = [
            "cmake",
            "..",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DWITH_PYTHON=ON",
            f"-DPYTHON_EXECUTABLE={str(python)}",
        ]
        if pybind11_dir:
            cmake_cmd.append(f"-Dpybind11_DIR={pybind11_dir}")
        code = run(cmake_cmd)
        if code != 0:
            return code
        code = run(["make", "-j", str(os.cpu_count() or 1)])
        if code != 0:
            return code
        code = run(["sudo", "make", "install"])
        if code != 0:
            return code
    finally:
        try:
            os.chdir(old_cwd)
        except Exception:
            pass

    # Install the Python bindings. Upstream `introlab/rtabmap` no longer ships the `python/` source
    # directory this used to `pip install` from, and the old fallback re-checked that same path, so
    # the build returned 0 having installed nothing and `installer_verify` was the first place an
    # operator learned `rtabmap-py` was missing (#181). Say it here, and fail.
    rtabmap_python = rtabmap_path / "python"
    if not rtabmap_python.exists():
        print(
            "RTAB-Map built, but this tree ships no `python/` bindings source (upstream removed "
            "it): `rtabmap-py` cannot be installed, so `slam_pi4` stays unavailable. See "
            "scripts/install_rtabmap_pi4.md."
        )
        return 1
    return run([str(pip), "install", str(rtabmap_python)])


def main() -> int:
    parser = argparse.ArgumentParser(description="HoundMind installer (internal core)")
    parser.add_argument("--venv", default=".venv", help="Path to virtualenv")
    parser.add_argument("--skip-venv", action="store_true", help="Skip venv creation")
    parser.add_argument(
        "--no-service",
        action="store_true",
        help="Do not install or enable houndmind.service",
    )
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
        help="Build and install RTAB-Map (rtabmap) from source (Pi 4/5 only)",
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
    parser.add_argument("--robot-hat-branch", default=ROBOT_HAT_BRANCH)
    parser.add_argument(
        "--vilib-repo", default="https://github.com/sunfounder/vilib.git"
    )
    parser.add_argument("--vilib-branch", default="picamera2")
    parser.add_argument(
        "--run-i2samp", action="store_true", help="Run i2samp.sh after installing pidog"
    )
    parser.add_argument(
        "--allow-unsupported-os",
        action="store_true",
        help="Continue on a release other than Bookworm (not supported; for maintainers)",
    )
    args = parser.parse_args()

    # The OS gate comes first: a refusal costs one line, and finding out after the venv and the apt
    # packages have been written is a mess to undo (#2).
    code = ensure_supported_os(args.allow_unsupported_os)
    if code != 0:
        return code

    if sys.version_info < (3, 11) or sys.version_info >= (3, 14):
        print(
            "Unsupported Python version: "
            f"{sys.version_info.major}.{sys.version_info.minor}. "
            "Use Python 3.11-3.13 (Bookworm ships 3.11; set PYTHON=python3.11)."
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
            # `--system-site-packages` so the venv can see Debian-provided bindings - `picamera2`
            # above all, which has no wheel on Bookworm (#215). Without it the camera module can
            # never import, whatever apt installed, and `vision_pi4` logs that on every start.
            code = run([sys.executable, "-m", "venv", "--system-site-packages", str(venv_path)])
            if code != 0:
                return code
        elif not venv_sees_system_packages(venv_path):
            print(
                "This venv was created without --system-site-packages, so `import picamera2` will "
                "fail even when python3-picamera2 is installed (docs/INSTALL.md). Recreate it with: "
                f"rm -rf {venv_path.name} && bash scripts/install_houndmind.sh"
            )
        python, pip = venv_paths(venv_path)
    else:
        python = Path(sys.executable)
        pip = Path(sys.executable).with_name("pip")

    if not pip.exists():
        print("pip not found; activate your environment first")
        return 2

    try:
        pi_class = detect_pi_class()
    except RuntimeError as exc:
        # An incomplete checkout is a stop, not a guess: the wrong board decides the dependencies.
        print(exc)
        return 2
    if pi_class == "unsupported":
        print(
            "This board is not supported: HoundMind runs on a Raspberry Pi 4 or Pi 5.\n"
            f"The last release that supported Pi 3 and older is {LAST_PI3_RELEASE}."
        )
        return 2
    if pi_class == "unknown":
        # A container, a CI runner and a workstation all land here, and the dependency
        # selection still has to work on them.
        print("Warning: no Raspberry Pi detected; assuming a Pi 4 for dependency selection.")

    preset = resolve_preset(pi_class, args.preset)

    req = repo_root / "requirements-lite.txt"
    # Auto-build RTAB-Map for a Pi 4/5 full preset, or when explicitly requested.
    should_build_rtabmap = args.build_rtabmap or (
        pi_class in ("pi4", "pi5") and preset == "full"
    )
    # Allow explicit opt-out
    if args.no_rtabmap:
        should_build_rtabmap = False
    if preset == "full":
        full_req = repo_root / "requirements.txt"
        if not full_req.exists():
            print("requirements.txt not found; full preset is unavailable.")
            return 2
        req = full_req
    # Interfaces first: the HAT needs I2C and the sound sensor needs SPI, and neither is on by
    # default on a fresh Bookworm image (#204). Before the apt step, so a reboot the operator does
    # next covers both.
    if not is_windows():
        code = ensure_interfaces_linux()
        if code != 0:
            return code

    # Install system deps early when requested or needed for full installs.
    if not is_windows() and (args.auto_system_deps or preset == "full" or should_build_rtabmap):
        code = ensure_system_deps_linux()
        if code != 0:
            return code
        # If we intended to build RTAB-Map, attempt to install PCL/VTK packages.
        # Failure to install these packages should not abort the entire
        # installer; instead disable the RTAB-Map build and continue.
        if should_build_rtabmap:
            code = ensure_rtabmap_deps_linux()
            if code != 0:
                print(
                    "Warning: failed to install RTAB-Map system packages (PCL/VTK)."
                )
                print(
                    "Disabling RTAB-Map build; SLAM support will be unavailable."
                )
                should_build_rtabmap = False
        # Ensure pip requirements do not try to install `rtabmap-py` if
        # the RTAB-Map build has been disabled by the above step. It's
        # possible the initial selection of requirements happened before
        # we learned PCL wasn't available, so adjust here.
        try:
            # `req` and `req_to_install` are set below this code path; if
            # they aren't present yet, this will be a no-op.
            content = req.read_text(encoding="utf-8")
            if not should_build_rtabmap and "rtabmap-py" in content:
                tmp_req = cache_root / "requirements-noslam.txt"
                lines = [l for l in content.splitlines() if "rtabmap-py" not in l]
                tmp_req.write_text("\n".join(lines), encoding="utf-8")
                req = tmp_req
        except Exception:
            pass

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
    # Run the model downloader for Pi4/5. Nothing installs flask here any more: it was a
    # dependency of the four per-feature HTTP servers, which the control plane replaced (#30).
    if pi_class in ("pi4", "pi5"):
        # The downloader lives beside the package. This pointed at a repo-root `tools/`
        # directory, which was deleted with the legacy servers, so the branch had silently done
        # nothing since; `src/tools/` is where the script actually is.
        model_dl = repo_root / "src" / "tools" / "download_opencv_models.py"
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
                # Ensure PiDog runtime helpers and hardware bindings are present.
                # Add `readchar` which `pidog` expects for keyboard input handling.
                # `lgpio` and `pygame` are here for the probe below, not for `pidog`'s own code:
                # `robot_hat` refuses to export anything without them, so a clean image failed the
                # probe and skipped the PiDog install entirely (#180).
                code = run([
                    str(pip), "install",
                    "gpiozero", "RPi.GPIO", "smbus2", "spidev", "readchar", "lgpio", "pygame",
                ])
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

                # The probe imports `robot_hat/__init__.py`, which gates its exports on these four,
                # so they have to be importable *before* it runs. On the lite preset nothing else
                # installs them - `pyaudio` only ever arrived with `requirements.txt`, the full
                # mirror - so a `--preset lite` run of this installer died here with "missing
                # module(s): pyaudio" and never installed pidog, vilib, the package or the service.
                # `pip install` is what makes the probe a test of the vendor tree rather than of the
                # preset (#180).
                absent = missing_modules(python, ROBOT_HAT_DEPS)
                if absent:
                    print(f"Installing the modules `robot_hat` needs to import: {', '.join(absent)}")
                    code = run([str(pip), "install", *absent])
                    if code != 0:
                        print(
                            "Could not install "
                            + ", ".join(absent)
                            + ". On Bookworm `pyaudio` needs `portaudio19-dev`; install the system "
                            "dependencies (`--auto-system-deps`) and re-run."
                        )
                        return code
                    absent = missing_modules(python, ROBOT_HAT_DEPS)

                # Installed is not the same as usable: `robot_hat/__init__.py` exposes the classes
                # `pidog` imports only when smbus2, lgpio, pyaudio and pygame are importable, and a
                # pre-2.5 tree never exposes `robot_hat.device`. Failing here names the missing
                # piece, instead of leaving a dog that cannot stand until the first action fails
                # (#114).
                code = run([str(python), "-c", ROBOT_HAT_PROBE])
                if code != 0:
                    reason = (
                        f"missing module(s): {', '.join(absent)}. "
                        if absent
                        else "`robot_hat` imports its parts but not the classes `pidog` needs. "
                    )
                    print(
                        "robot-hat installed, but `pidog` would not be able to import it: "
                        + reason
                        + f"Check that the cloned branch is {ROBOT_HAT_BRANCH} rather than v2.0."
                    )
                    return 2

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
        # Ensure pybind11 exists before attempting the RTAB-Map build; if
        # pybind11 cannot be installed, disable the build and continue.
        pybind_code = ensure_pybind11_deps_linux(python, pip)
        if pybind_code != 0:
            print(
                "Warning: pybind11 not available; disabling RTAB-Map build."
            )
            should_build_rtabmap = False

    if should_build_rtabmap:
        print("Building RTAB-Map from source (this may take a long time)...")
        code = build_rtabmap(cache_root, pip, python)
        if code != 0:
            print("RTAB-Map build/install failed; SLAM support may be unavailable.")

    # Supervision: the unit is what makes "the dog comes back after a reboot" true (#211).
    if not args.no_service and not is_windows():
        code = install_service_unit(repo_root, python)
        if code != 0:
            return code

    # The verifier lives beside the other device CLIs in `src/tools/`; the root `tools/` package
    # it used to sit in was removed, so that candidate was a path nothing could ever create.
    verifier = repo_root / "src" / "tools" / "installer_verify.py"
    if not verifier.exists():
        print("Installer verifier not found; skipping verification step.")
        return 0
    return run([str(python), str(verifier), "--preset", preset])


if __name__ == "__main__":
    raise SystemExit(main())
