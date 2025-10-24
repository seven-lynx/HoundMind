#!/usr/bin/env python3
"""
PackMind Checkup Tool — PiDog runtime verifier
==============================================

Author: seven-lynx
Version: 2025.10.24

Run this on the PiDog to quickly verify your environment and PackMind modules after tinkering.

Scopes:
- import: Import all PackMind packages and modules (default)
- services: Import and basic init/teardown of key services (safe; no movement)

Examples (on the Pi):
  python3 tools/packmind_checkup.py --scope import
  python3 tools/packmind_checkup.py --scope services --preset simple

Notes:
- This tool is intended for the PiDog. It may not work on Windows/macOS.
- Movement is disabled. No head/leg/tail motion is performed.
- Optional subsystems (voice/camera/SLAM) are only imported if present.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import platform
import sys
import time
import traceback

OK = "✓"
FAIL = "✗"


def _print_header(title: str) -> None:
    print("\n" + title)
    print("=" * len(title))


def check_environment() -> bool:
    _print_header("Environment")
    os_name = platform.system()
    machine = platform.machine()
    py_ver = sys.version.split()[0]
    print(f"OS: {os_name}")
    print(f"Arch: {machine}")
    print(f"Python: {py_ver}")
    is_pi_like = os_name == "Linux" and ("arm" in machine.lower() or "aarch" in machine.lower())
    print(f"Pi-like environment: {'yes' if is_pi_like else 'no'}")
    return True


def check_pidog_import() -> bool:
    _print_header("PiDog library")
    try:
        from pidog import Pidog  # type: ignore
        print(f"{OK} pidog imported")
        # Do not instantiate or move — keep safe.
        return True
    except Exception as e:
        print(f"{FAIL} pidog import failed: {e}")
        traceback.print_exc(limit=1)
        return False


def import_packmind_modules() -> bool:
    _print_header("PackMind module imports")
    try:
        import packmind  # noqa: F401
    except Exception as e:
        print(f"{FAIL} failed to import packmind package: {e}")
        traceback.print_exc(limit=1)
        return False

    subpackages = [
        "packmind.core",
        "packmind.behaviors",
        "packmind.services",
        "packmind.runtime",
        "packmind.mapping",
        "packmind.localization",
        "packmind.nav",
    ]
    all_ok = True
    for pkg_name in subpackages:
        try:
            pkg = importlib.import_module(pkg_name)
        except Exception as e:
            print(f"{FAIL} {pkg_name}: failed to import package: {e}")
            traceback.print_exc(limit=1)
            all_ok = False
            continue

        if getattr(pkg, "__path__", None) is None:
            # Not a namespace/package; skip discovery
            print(f"{OK} {pkg_name}")
            continue

        # Walk child modules
        for modinfo in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            name = modinfo.name
            try:
                importlib.import_module(name)
                print(f"{OK} {name}")
            except Exception as e:
                print(f"{FAIL} {name}: {e}")
                all_ok = False
    return all_ok


def service_smoke_tests(preset: str, *, move: bool = False) -> bool:
    _print_header("Service smoke tests (no movement)")

    try:
        from packmind.packmind_config import load_config  # type: ignore
        cfg = load_config(preset)
        print(f"{OK} loaded config preset: {preset}")
    except Exception as e:
        print(f"{FAIL} config load failed: {e}")
        return False

    ok = True

    def _try(label: str, fn):
        nonlocal ok
        try:
            fn()
            print(f"{OK} {label}")
        except Exception as ex:
            print(f"{FAIL} {label}: {ex}")
            ok = False

    # Basic/core services
    def _energy():
        from packmind.services.energy_service import EnergyService
        _ = EnergyService()

    def _emotion():
        from packmind.services.emotion_service import EmotionService
        _ = EmotionService()

    def _log():
        from packmind.services.log_service import LogService
        _ = LogService()

    def _obstacle():
        from packmind.services.obstacle_service import ObstacleService
        _ = ObstacleService()

    _try("EnergyService", _energy)
    _try("EmotionService", _emotion)
    _try("LogService", _log)
    _try("ObstacleService", _obstacle)

    # Optional services — import and init if present
    def _maybe(label: str, importer):
        nonlocal ok
        try:
            importer()
            print(f"{OK} {label}")
        except ImportError:
            print(f"- {label} not installed (skipped)")
        except Exception as ex:
            print(f"{FAIL} {label}: {ex}")
            ok = False

    def _voice():
        from packmind.services.voice_service import VoiceService
        _ = VoiceService()

    # ScanningService: optionally perform a small head sweep when --move is enabled.
    def _scan():
        if not move:
            raise ImportError("ScanningService skipped (requires motion)")
        # Minimal motion test: small three-way scan with low speed
        try:
            from pidog import Pidog  # type: ignore
        except Exception as e:
            raise ImportError(f"pidog not available: {e}")

        from packmind.core.context import AIContext
        from packmind.services.scanning_service import ScanningService

        dog = None
        try:
            dog = Pidog()
            ctx = AIContext(dog=dog)
            svc = ScanningService(ctx, head_scan_speed=50, scan_samples=2)
            res = svc.scan_three_way(left_deg=30, right_deg=30, settle_s=0.2, samples=2)
            print(f"Distances (cm): {res}")
        finally:
            # Best-effort to center head and close
            try:
                if dog is not None:
                    dog.head_move([[0, 0, 0]], speed=50)
                    time.sleep(0.2)
                    dog.close()
            except Exception:
                pass

    def _face():
        from packmind.services.face_recognition_service import FaceRecognitionService
        _ = FaceRecognitionService(config={})

    def _balance():
        from packmind.services.dynamic_balance_service import DynamicBalanceService
        _ = DynamicBalanceService(cfg)

    def _audio():
        from packmind.services.enhanced_audio_processing_service import EnhancedAudioProcessingService
        _ = EnhancedAudioProcessingService(cfg)

    _maybe("VoiceService", _voice)
    _maybe("ScanningService", _scan)
    _maybe("FaceRecognitionService", _face)
    _maybe("DynamicBalanceService", _balance)
    _maybe("EnhancedAudioProcessingService", _audio)

    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PackMind Checkup Tool (PiDog)")
    parser.add_argument(
        "--scope",
        choices=["import", "services", "all"],
        default="import",
        help="What to verify: module imports, service smoke tests, or both",
    )
    parser.add_argument(
        "--preset",
        choices=["default", "simple", "advanced", "indoor", "explorer"],
        default="simple",
        help="Configuration preset to use for service tests",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Allow limited head movement to test ScanningService (Pi only)",
    )
    args = parser.parse_args(argv)

    overall_ok = True

    check_environment()
    pidog_ok = check_pidog_import()
    if not pidog_ok:
        # Still allow import checks; some modules do not need pidog import immediately
        print("Warning: pidog not available — hardware-dependent services may fail")

    if args.scope in ("import", "all"):
        overall_ok &= import_packmind_modules()

    if args.scope in ("services", "all"):
        overall_ok &= service_smoke_tests(args.preset, move=args.move)

    print("\nSummary")
    print("-------")
    print(f"Result: {'SUCCESS' if overall_ok else 'FAILURE'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
