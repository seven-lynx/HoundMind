"""Simple installer verification for the lite preset.

Run this on the target device to validate basic Python and dependency expectations.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The range `pyproject.toml` declares: 3.11 is Bookworm, 3.13 is Trixie, and 3.10 is
# end-of-life. Mirrored from `scripts/installer_core.py::is_supported_python` rather than
# imported - `scripts/` is not a package and the installer runs before HoundMind is installed -
# and `tests/test_python_support.py` holds the copies equal. A verifier that accepts an
# interpreter the package refuses certifies an environment its next `pip install` rejects (#111).
PYTHON_FLOOR: tuple[int, int] = (3, 11)
PYTHON_CEILING_EXCLUSIVE: tuple[int, int] = (3, 14)


def is_supported_python(version: tuple[int, int]) -> bool:
    """The declared range, as an answer instead of a floor."""
    major, minor = version
    return major == PYTHON_FLOOR[0] and PYTHON_FLOOR[1] <= minor < PYTHON_CEILING_EXCLUSIVE[1]


def check_python() -> bool:
    major, minor = sys.version_info.major, sys.version_info.minor
    ok = is_supported_python((major, minor))
    print(
        f"Python: {major}.{minor} -> {'OK' if ok else 'UNSUPPORTED'} "
        f"(supported: {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]}-{PYTHON_CEILING_EXCLUSIVE[0]}.{PYTHON_CEILING_EXCLUSIVE[1] - 1})"
    )
    return ok


IMPORT_NAME_MAP = {
    "opencv-python": "cv2",
    "opencv-contrib-python": "cv2",
    "SpeechRecognition": "speech_recognition",
    "rtabmap-py": "rtabmap",
}

# Requirements that cannot be satisfied by installing anything, so failing them would report a
# broken environment that is in fact the documented state. The RTAB-Map bindings are the case:
# upstream `introlab/rtabmap` has no `python/` directory to `pip install`, which is why the
# installer only builds the library behind `--build-rtabmap` and why `slam_pi4` must stay off
# (#181). Naming it UNSUPPORTED keeps an honest red away from a check that cannot go green.
UNSUPPORTED_REQUIREMENTS = {
    "rtabmap-py": "upstream has no installable Python bindings; `slam_pi4` must stay disabled (#181)",
}


def package_name(line: str) -> str:
    """The distribution name of a requirement line, without its version specifier.

    Splitting on `==` and `>=` alone left every other operator glued to the name, so the verifier
    tried to import `numpy<2` and reported a package that was installed as MISSING - after the
    mirror started pinning `numpy<2` and `opencv-contrib-python<4.12` for the picamera2 ABI (#242).
    """
    return re.split(r"[<>=!~]", line, maxsplit=1)[0].strip()


def check_requirements(req_path: Path):
    if not req_path.exists():
        print(f"Requirements file not found: {req_path}")
        return False
    ok = True
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = package_name(line)
        import_name = IMPORT_NAME_MAP.get(pkg, pkg)
        try:
            __import__(import_name)
            print(f"{pkg}: OK")
        except Exception as exc:  # noqa: BLE001
            reason = UNSUPPORTED_REQUIREMENTS.get(pkg)
            if reason is not None:
                print(f"{pkg}: UNSUPPORTED - {reason} ({exc})")
                continue
            print(f"{pkg}: MISSING ({exc})")
            ok = False
    return ok


def check_import(module: str) -> bool:
    try:
        __import__(module)
        print(f"{module}: OK")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"{module}: MISSING ({exc})")
        return False


# The two boot-config paths: Bookworm puts it under /boot/firmware, older images under /boot.
BOOT_CONFIG_CANDIDATES = (Path("/boot/firmware/config.txt"), Path("/boot/config.txt"))
OVERLAY_LINE = "dtoverlay=hifiberry-dac"


def _first_existing(paths: tuple[Path, ...]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def check_audio_chain(
    boot_config: Path | None = None,
    asound: Path | None = None,
) -> bool:
    """The three things that make the HAT speaker work, none of which an import can see (#288).

    #254 presented as a hardware question with every Python layer verified: the overlay line, the
    `/etc/asound.conf` default and the PulseAudio sink are all outside importland, and nothing at
    install time looked at any of them. This does look, and it is careful about what "missing"
    means:

    - no Pi boot config at all -> not applicable, this is a workstation;
    - overlay absent -> a warning, because a dog without the voice stack does not need a speaker;
    - overlay present but the routing absent or wrong -> a failure. That is the half-configured HAT
      #254 measured, and the state in which every engine constructs and says nothing.
    """
    if boot_config is None:
        boot_config = _first_existing(BOOT_CONFIG_CANDIDATES)
    if boot_config is None or not boot_config.exists():
        print("audio: not applicable (no Pi boot config on this machine)")
        return True
    try:
        boot_text = boot_config.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        print(f"audio: UNCHECKED ({exc})")
        return True
    if OVERLAY_LINE not in boot_text:
        print(
            f"audio: WARN - {OVERLAY_LINE} is absent from {boot_config}; the HAT speaker is not "
            "enabled and the voice stack cannot be heard (docs/INSTALL.md)"
        )
        return True

    asound_path = asound or Path("/etc/asound.conf")
    try:
        asound_text = asound_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        print(f"audio: MISSING - {asound_path} cannot be read ({exc}) - the HAT is enabled in")
        print("       the boot config, so the speaker has an amplifier and no route to it")
        return False
    routing = re.sub(r"\s+", " ", asound_text)
    if "pcm.!default" not in routing or "robothat" not in routing:
        print(f"audio: MISSING - {asound_path} has no `pcm.!default` pointing at `robothat`")
        return False

    print(f"audio: OK - {OVERLAY_LINE}, {asound_path} routes pcm.!default to robothat")
    return True


def dry_chain(python: str | None = None) -> list[list[str]]:
    """The three post-install checks, in order, carrying the flags that keep them motion-safe.

    They were a habit rather than a chain (#315): the flags that matter are the ones easiest to
    forget, and a fresh install is exactly when forgetting them is worst. `smoke_test` moves
    nothing without `--include-motion`, and `hardware_checkup` needs `--skip-motion`.
    """
    exe = python or sys.executable
    return [
        [exe, "-m", "tools.installer_verify"],
        [exe, "-m", "tools.hardware_checkup", "--skip-motion"],
        [exe, "-m", "tools.smoke_test"],
    ]


def run_chain(python: str | None = None) -> int:
    """Run `dry_chain` in order, stopping at the first non-zero. Returns that code, or 0."""
    for command in dry_chain(python):
        print("+ " + " ".join(command))
        try:
            code = subprocess.run(command).returncode
        except OSError as exc:
            print(f"cannot run {command[0]}: {exc}")
            return 1
        if code != 0:
            return code
    return 0


def main():
    parser = argparse.ArgumentParser(description="HoundMind installer verification")
    parser.add_argument("--preset", choices=["lite", "full"], default="lite")
    parser.add_argument(
        "--chain",
        action="store_true",
        help="print the three post-install checks in order, with their motion-safe flags",
    )
    parser.add_argument(
        "--run-chain",
        action="store_true",
        help="run the three checks in order and stop at the first failure",
    )
    args = parser.parse_args()
    if args.chain:
        for command in dry_chain():
            print(" ".join(command))
        return 0
    if args.run_chain:
        return run_chain()
    # The verifier file lives in src/tools/. The repository root is two levels up.
    repo_root = Path(__file__).resolve().parents[2]
    req = repo_root / ("requirements.txt" if args.preset == "full" else "requirements-lite.txt")
    print("HoundMind installer verification")
    py_ok = check_python()
    req_ok = check_requirements(req)
    pidog_ok = check_import("pidog")
    houndmind_ok = check_import("houndmind_ai")

    heavy_ok = True
    if args.preset == "full":
        heavy_ok = all(
            [
                check_import("numpy"),
                check_import("scipy"),
                check_import("cv2"),
                check_import("face_recognition"),
                check_import("sounddevice"),
            ]
        )
        # The camera binding is a Debian package and only exists on a Pi (#215). On a workstation a
        # `full` install cannot have it, so it is reported and only counts on a machine with a Pi
        # boot config - otherwise every dev box would verify as broken.
        picamera_ok = check_import("picamera2")
        if picamera_ok:
            print("picamera2: camera stack available (`vision_pi4` may be enabled)")
        elif Path("/boot/firmware/config.txt").exists():
            print("picamera2: MISSING - `vision_pi4` must stay disabled (docs/INSTALL.md)")
            heavy_ok = False
        else:
            print("picamera2: not applicable (no Pi boot config on this machine)")

    audio_ok = check_audio_chain()

    if py_ok and req_ok and pidog_ok and houndmind_ok and heavy_ok and audio_ok:
        print("Installer check: OK")
        return 0
    print("Installer check: FAILED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
