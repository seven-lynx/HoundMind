#!/usr/bin/env python3
"""
CanineCore Checkup Tool — PiDog runtime verifier
===============================================

Author: 7Lynx
Version: 2025.10.24

Run this on the PiDog to quickly verify your environment and CanineCore modules after tinkering.

Scopes:
- import: Import all canine_core packages and modules (default)
- services: Instantiate core services (hardware, sensors, motion, emotions, voice)
- all: Do both; combine with --move for limited hardware motion tests

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
from types import SimpleNamespace

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


def services_smoke_tests(allow_move: bool) -> bool:
    _print_header("Services smoke tests")
    ok = True
    dog = None
    hw = None
    try:
        # Lazy imports to avoid errors if package missing
        from canine_core.core.services.hardware import HardwareService
        from canine_core.core.services.sensors import SensorService
        from canine_core.core.services.motion import MotionService
        from canine_core.core.services.emotions import EmotionService
        from canine_core.core.services.voice import VoiceService
        from canine_core.core.services.imu import IMUService
        from canine_core.core.services.safety import SafetyService
        from canine_core.core.services.battery import BatteryService
        from canine_core.core.services.telemetry import TelemetryService
        from canine_core.core.services.sensors_facade import SensorsFacade
        # New optional services
        from canine_core.core.services.energy import EnergyService
        from canine_core.core.services.balance import BalanceService
        from canine_core.core.services.audio_processing import AudioProcessingService
        from canine_core.core.services.scanning_coordinator import ScanningCoordinator
        from canine_core.core.services.learning import LearningService
        # Config (for defaults used by EnergyService)
        try:
            from canine_core.config.canine_config import CanineConfig  # type: ignore
        except Exception:
            CanineConfig = type("TmpCfg", (), {})  # fallback minimal cfg

        # Hardware init (may fail on non-Pi or without peripherals)
        try:
            hw = HardwareService()
            hw.init()
            dog = getattr(hw, "dog", None)
            print(f"{OK} HardwareService.init()")
        except Exception as e:
            print(f"{FAIL} HardwareService.init(): {e} — continuing with dummy hardware")
            hw = SimpleNamespace(dog=None, rgb=None)

        # Instantiate services
        sensors = SensorService(hw)
        motion = MotionService(hw)
        emotions = EmotionService(hw, enabled=True)
        voice = VoiceService()
        imu = IMUService(hw)
        safety = SafetyService(hw, imu, publish=lambda *_: None)
        battery = BatteryService(hw, publish=lambda *_: None)
        telemetry = TelemetryService(hw, logger=SimpleNamespace(info=lambda *_: None))
        sensors_facade = SensorsFacade(hw)
        # Optional services (sim-safe)
        energy = EnergyService(CanineConfig, logger=SimpleNamespace(info=lambda *_: None))
        balance = BalanceService(imu, publish=lambda *_: None, max_tilt_deg=45.0)
        audio_proc = AudioProcessingService()
        scanning = ScanningCoordinator(hw, sensors, publish=lambda *_: None)
        learning = LearningService(config=CanineConfig, logger=SimpleNamespace(info=lambda *_: None))
        print(f"{OK} Sensor/Motion/Emotions/Voice/IMU/Safety/Battery/Telemetry/SensorsFacade/Energy/Balance/AudioProc/ScanningCoord/Learning instantiated")

        # Non-moving checks
        emotions.update((0, 128, 255))
        print(f"{OK} EmotionService.update()")

        # Energy ticks
        try:
            lvl_before = energy.level
            energy.tick_active()
            energy.tick_rest()
            lvl_after = energy.level
            print(f"{OK} EnergyService.tick_*() level {lvl_before:.2f}→{lvl_after:.2f}")
        except Exception as e:
            print(f"{FAIL} EnergyService.tick_*(): {e}")
            ok = False

        # Learning counters
        try:
            learning.record_interaction("checkup_touch")
            snap = learning.snapshot()
            # print only top keys to keep output brief
            cats = ", ".join(k for k in snap.keys())
            print(f"{OK} LearningService.snapshot() categories: {cats}")
        except Exception as e:
            print(f"{FAIL} LearningService: {e}")
            ok = False

        # Balance assess (IMU required; sim-safe if not present)
        try:
            state = balance.assess()
            if state is None:
                print(f"{OK} BalanceService.assess(): unavailable (no IMU)")
            else:
                print(f"{OK} BalanceService.assess() = {state}")
        except Exception as e:
            print(f"{FAIL} BalanceService.assess(): {e}")
            ok = False

        # Audio processing VAD availability
        try:
            vad = audio_proc.has_vad()
            print(f"{OK} AudioProcessingService.has_vad() = {vad}")
        except Exception as e:
            print(f"{FAIL} AudioProcessingService.has_vad(): {e}")
            ok = False

        # Optional limited motion/head sweep via sensors
        if allow_move:
            try:
                dists = awaitable_read_distances(sensors, head_range=15, head_speed=50)
                print(f"{OK} SensorService.read_distances(): fwd={dists[0]:.0f}cm left={dists[1]:.0f}cm right={dists[2]:.0f}cm")
            except Exception as e:
                print(f"{FAIL} SensorService.read_distances() move test: {e}")
                ok = False

        # Try a lightweight motion action only if movement allowed
        if allow_move and dog is not None:
            try:
                motion.act("stand", speed=80)
                motion.wait()
                print(f"{OK} MotionService.act('stand') + wait")
            except Exception as e:
                print(f"{FAIL} MotionService.act('stand'): {e}")
                ok = False

        # ScanningCoordinator minimal sweep (movement only when allowed)
        if allow_move:
            try:
                samples = scanning.sweep_samples(yaw_max_deg=15, step_deg=15, head_speed=50)
                print(f"{OK} ScanningCoordinator.sweep_samples(): {len(samples)} points")
            except Exception as e:
                print(f"{FAIL} ScanningCoordinator.sweep_samples(): {e}")
                ok = False

        # Quick safety/battery/telemetry checks
        try:
            safety.periodic_check()
            print(f"{OK} SafetyService.periodic_check()")
        except Exception as e:
            print(f"{FAIL} SafetyService.periodic_check(): {e}")
            ok = False

        try:
            _ = battery.check_and_publish()
            print(f"{OK} BatteryService.check_and_publish()")
        except Exception as e:
            print(f"{FAIL} BatteryService.check_and_publish(): {e}")
            ok = False

        try:
            telemetry.maybe_log()
            print(f"{OK} TelemetryService.maybe_log()")
        except Exception as e:
            print(f"{FAIL} TelemetryService.maybe_log(): {e}")
            ok = False

        # SensorsFacade checks
        try:
            sd = sensors_facade.sound_detected()
            if sd is None:
                print(f"{OK} SensorsFacade.sound_detected(): unavailable on this host")
            else:
                print(f"{OK} SensorsFacade.sound_detected() = {sd}")
        except Exception as e:
            print(f"{FAIL} SensorsFacade.sound_detected(): {e}")
            ok = False

        try:
            deg = sensors_facade.sound_direction_deg()
            if deg is None:
                print(f"{OK} SensorsFacade.sound_direction_deg(): unavailable or no detection")
            else:
                print(f"{OK} SensorsFacade.sound_direction_deg() = {deg}°")
        except Exception as e:
            print(f"{FAIL} SensorsFacade.sound_direction_deg(): {e}")
            ok = False

        try:
            tv = sensors_facade.touch_read()
            if tv is None:
                print(f"{OK} SensorsFacade.touch_read(): unavailable on this host")
            else:
                print(f"{OK} SensorsFacade.touch_read() = {tv}")
        except Exception as e:
            print(f"{FAIL} SensorsFacade.touch_read(): {e}")
            ok = False

        # Stop voice cleanly
        try:
            voice.stop()
        except Exception:
            pass
    except Exception as e:
        print(f"{FAIL} services test failed: {e}")
        traceback.print_exc(limit=1)
        ok = False
    finally:
        try:
            if hw and hasattr(hw, "close"):
                hw.close()
        except Exception:
            pass
    return ok


def awaitable_read_distances(sensors, head_range: int, head_speed: int):
    """Helper to call possibly-async sensors.read_distances from sync context."""
    try:
        import asyncio
        coro = sensors.read_distances(head_range=head_range, head_speed=head_speed)
        if asyncio.iscoroutine(coro):
            return asyncio.run(coro)
        return coro
    except RuntimeError:
        # If already in an event loop (rare for this script), fall back to a simple call
        return sensors.read_distances(head_range=head_range, head_speed=head_speed)


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
        choices=["import", "services", "all"],
        default="import",
        help="What to verify: 'import', 'services', or 'all' (combine with --move to allow motion)",
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

    if args.scope in ("import", "all"):
        overall_ok &= import_caninecore_modules()

    if args.scope in ("services", "all"):
        overall_ok &= services_smoke_tests(allow_move=args.move)

    if args.move and args.scope in ("all", "import"):
        overall_ok &= minimal_head_sweep()

    print("\nSummary")
    print("-------")
    print(f"Result: {'SUCCESS' if overall_ok else 'FAILURE'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
