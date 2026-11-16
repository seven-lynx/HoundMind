"""Simple installer verification for the lite preset.

Run this on the target device to validate basic Python and dependency expectations.
"""

from __future__ import annotations

import argparse
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


def check_requirements(req_path: Path):
    if not req_path.exists():
        print(f"Requirements file not found: {req_path}")
        return False
    ok = True
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = line.split("==")[0].split(">=")[0].strip()
        import_name = IMPORT_NAME_MAP.get(pkg, pkg)
        try:
            __import__(import_name)
            print(f"{pkg}: OK")
        except Exception as exc:  # noqa: BLE001
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


def main():
    parser = argparse.ArgumentParser(description="HoundMind installer verification")
    parser.add_argument("--preset", choices=["lite", "full"], default="lite")
    args = parser.parse_args()
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

    if py_ok and req_ok and pidog_ok and houndmind_ok and heavy_ok:
        print("Installer check: OK")
        return 0
    print("Installer check: FAILED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
