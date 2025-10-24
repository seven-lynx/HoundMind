#!/usr/bin/env python3
"""
CanineCore Checkup Tool — PiDog runtime verifier
===============================================

Author: seven-lynx
Version: 2025.10.24

Run this on the PiDog to quickly verify your environment and CanineCore modules after tinkering.

Scopes:
- import: Import all canine_core packages and modules (default)

Examples (on the Pi):
  python3 tools/caninecore_checkup.py --scope import
  python3 tools/caninecore_checkup.py --move  # Optional minimal head sweep

Notes:
- Intended for the PiDog. It may not work on Windows/macOS.
- Movement is disabled by default. Use --move for a tiny head sweep.
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
        return True
    except Exception as e:
        print(f"{FAIL} pidog import failed: {e}")
        traceback.print_exc(limit=1)
        return False


def import_caninecore_modules() -> bool:
    _print_header("CanineCore module imports")
    try:
        import canine_core as cc  # noqa: F401
    except Exception as e:
        print(f"{FAIL} failed to import canine_core package: {e}")
        traceback.print_exc(limit=1)
        return False

    all_ok = True
    try:
        import canine_core  # type: ignore
        if getattr(canine_core, "__path__", None) is None:
            print(f"{OK} canine_core")
            return True
        for modinfo in pkgutil.walk_packages(canine_core.__path__, canine_core.__name__ + "."):
            name = modinfo.name
            try:
                importlib.import_module(name)
                print(f"{OK} {name}")
            except Exception as e:
                print(f"{FAIL} {name}: {e}")
                all_ok = False
    except Exception as e:
        print(f"{FAIL} error during package walk: {e}")
        all_ok = False
    return all_ok


def minimal_head_sweep() -> bool:
    _print_header("Minimal head sweep (--move)")
    try:
        from pidog import Pidog  # type: ignore
    except Exception as e:
        print(f"{FAIL} pidog not available: {e}")
        return False

    dog = None
    try:
        dog = Pidog()
        # Center, small left, small right, center
        dog.head_move([[0, 0, 0]], speed=40)
        time.sleep(0.2)
        dog.head_move([[20, 0, 0]], speed=40)
        time.sleep(0.2)
        dog.head_move([[-20, 0, 0]], speed=40)
        time.sleep(0.2)
        dog.head_move([[0, 0, 0]], speed=40)
        time.sleep(0.2)
        print(f"{OK} head sweep complete")
        return True
    except Exception as e:
        print(f"{FAIL} head sweep error: {e}")
        return False
    finally:
        try:
            if dog is not None:
                dog.head_move([[0, 0, 0]], speed=40)
                time.sleep(0.2)
                dog.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CanineCore Checkup Tool (PiDog)")
    parser.add_argument(
        "--scope",
        choices=["import", "all"],
        default="import",
        help="What to verify: module imports or both (imports + optional --move)",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Allow limited head movement to test hardware (Pi only)",
    )
    args = parser.parse_args(argv)

    overall_ok = True
    check_environment()
    pidog_ok = check_pidog_import()
    if not pidog_ok and args.move:
        print("Warning: pidog not available — movement test will be skipped")

    overall_ok &= import_caninecore_modules()

    if args.move and args.scope in ("all", "import"):
        overall_ok &= minimal_head_sweep()

    print("\nSummary")
    print("-------")
    print(f"Result: {'SUCCESS' if overall_ok else 'FAILURE'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
