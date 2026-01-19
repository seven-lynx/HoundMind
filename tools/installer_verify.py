"""Simple installer verification for the Pi3 lightweight preset.

Run this on the target device to validate basic Python and dependency expectations.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def check_python(min_major=3, min_minor=9):
    maj, mino = sys.version_info.major, sys.version_info.minor
    ok = (maj > min_major) or (maj == min_major and mino >= min_minor)
    print(f"Python: {maj}.{mino} -> {'OK' if ok else 'TOO OLD'}")
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
    repo_root = Path(__file__).resolve().parents[1]
    req = repo_root / ("requirements.txt" if args.preset == "full" else "requirements-lite.txt")
    print("HoundMind installer verification")
    py_ok = check_python(3, 9)
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

    if py_ok and req_ok and pidog_ok and houndmind_ok and heavy_ok:
        print("Installer check: OK")
        return 0
    print("Installer check: FAILED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
