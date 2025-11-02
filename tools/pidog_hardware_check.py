#!/usr/bin/env python3
"""
PiDog Hardware Check (run on the robot)
=======================================

Purpose: Quickly validate PiDog subsystems with clear OK/FAIL output.

Safe by default:
- No motion unless you pass --move
- Skips features not present on your kit

Examples (run on the Pi):
  python3 tools/pidog_hardware_check.py                # sensors-only
  python3 tools/pidog_hardware_check.py --move         # include motion/head sweep
  python3 tools/pidog_hardware_check.py --scope audio  # only test audio
  python3 tools/pidog_hardware_check.py --scope all --move --sound single_bark_1
"""
from __future__ import annotations

import argparse
import platform
import sys
import time
from typing import Tuple

OK = "✓"
FAIL = "✗"


def _print_header(title: str) -> None:
    print("\n" + title)
    print("=" * len(title))


def check_environment() -> None:
    _print_header("Environment")
    os_name = platform.system()
    machine = platform.machine()
    py_ver = sys.version.split()[0]
    print(f"OS: {os_name}")
    print(f"Arch: {machine}")
    print(f"Python: {py_ver}")
    is_pi_like = os_name == "Linux" and ("arm" in machine.lower() or "aarch" in machine.lower())
    print(f"Pi-like environment: {'yes' if is_pi_like else 'no'}")


def get_dog():
    try:
        from pidog import Pidog  # type: ignore
    except Exception as e:
        print(f"{FAIL} pidog import failed: {e}")
        return None
    try:
        dog = Pidog()
        print(f"{OK} Pidog() instantiated")
        return dog
    except Exception as e:
        print(f"{FAIL} Pidog() init failed: {e}")
        return None


def test_distance(dog) -> bool:
    _print_header("Ultrasonic distance (cm)")
    try:
        d = dog.read_distance()
        val = float(d if d is not None else 0.0)
        print(f"{OK} read_distance() = {val:.1f} cm")
        return True
    except Exception as e:
        print(f"{FAIL} read_distance(): {e}")
        return False


def test_head_scan(dog, yaw: int = 20, speed: int = 60) -> bool:
    _print_header("Head scan + distance (requires --move)")
    try:
        dog.head_move([[0, 0, 0]], speed=speed)
        dog.wait_head_done()
        time.sleep(0.15)
        center = float(dog.read_distance() or 0.0)

        dog.head_move([[max(-90, -abs(yaw)), 0, 0]], speed=speed)
        dog.wait_head_done()
        time.sleep(0.15)
        left = float(dog.read_distance() or 0.0)

        dog.head_move([[min(90, abs(yaw)), 0, 0]], speed=speed)
        dog.wait_head_done()
        time.sleep(0.15)
        right = float(dog.read_distance() or 0.0)

        dog.head_move([[0, 0, 0]], speed=speed)
        dog.wait_head_done()
        print(f"{OK} scan cm center={center:.0f} left={left:.0f} right={right:.0f}")
        return True
    except Exception as e:
        print(f"{FAIL} head scan: {e}")
        return False


def test_motion(dog) -> bool:
    _print_header("Motion (requires --move)")
    ok = True
    try:
        dog.do_action("stand", speed=60)
        dog.wait_all_done()
        print(f"{OK} do_action('stand')")
    except Exception as e:
        print(f"{FAIL} stand: {e}")
        ok = False
    try:
        dog.do_action("forward", step_count=1, speed=60)
        dog.wait_all_done()
        print(f"{OK} do_action('forward', 1)")
    except Exception as e:
        print(f"{FAIL} forward: {e}")
        ok = False
    try:
        dog.do_action("turn_left", step_count=1, speed=70)
        dog.wait_all_done()
        print(f"{OK} do_action('turn_left', 1)")
    except Exception as e:
        print(f"{FAIL} turn_left: {e}")
        ok = False
    try:
        dog.do_action("lie", speed=50)
        dog.wait_all_done()
        print(f"{OK} do_action('lie')")
    except Exception as e:
        print(f"{FAIL} lie: {e}")
        ok = False
    return ok


def test_imu(dog) -> bool:
    _print_header("IMU (accData/gyroData)")
    ok = True
    try:
        acc = getattr(dog, "accData", None)
        if acc is not None:
            ax, ay, az = acc
            print(f"{OK} accData = ({ax}, {ay}, {az})")
        else:
            print(f"{FAIL} accData not available")
            ok = False
    except Exception as e:
        print(f"{FAIL} accData: {e}")
        ok = False
    try:
        gyro = getattr(dog, "gyroData", None)
        if gyro is not None:
            gx, gy, gz = gyro
            print(f"{OK} gyroData = ({gx}, {gy}, {gz})")
        else:
            print(f"{FAIL} gyroData not available")
            ok = False
    except Exception as e:
        print(f"{FAIL} gyroData: {e}")
        ok = False
    return ok


def test_ears(dog) -> bool:
    _print_header("Sound direction (ears)")
    try:
        ears = getattr(dog, "ears", None)
        if ears is None:
            print(f"{FAIL} ears module not present")
            return False
        detected = False
        try:
            detected = bool(ears.isdetected())
        except Exception:
            pass
        if detected:
            try:
                deg = int(ears.read())
                print(f"{OK} ears: detected; direction={deg}°")
            except Exception:
                print(f"{OK} ears detected; read() failed, but sensor present")
        else:
            print(f"{OK} ears: no sound detected right now")
        return True
    except Exception as e:
        print(f"{FAIL} ears: {e}")
        return False


def test_touch(dog) -> bool:
    _print_header("Dual touch")
    try:
        touch = getattr(dog, "dual_touch", None)
        if touch is None:
            print(f"{FAIL} dual_touch module not present")
            return False
        try:
            v = touch.read()
            print(f"{OK} dual_touch.read() = {v}")
            return True
        except Exception as e:
            print(f"{FAIL} dual_touch.read(): {e}")
            return False
    except Exception as e:
        print(f"{FAIL} dual_touch: {e}")
        return False


def test_audio(dog, sound: str, volume: int) -> bool:
    _print_header("Audio")
    try:
        dog.speak(sound, volume=max(0, min(100, int(volume))))
        print(f"{OK} speak('{sound}', volume={volume})")
        return True
    except Exception as e:
        print(f"{FAIL} speak(): {e}")
        return False


def test_led(dog) -> bool:
    _print_header("RGB LED strip")
    try:
        strip = getattr(dog, "rgb_strip", None)
        if strip is None:
            print(f"{FAIL} rgb_strip not present")
            return False
        # Try a quick breath pattern and then close
        try:
            strip.set_mode("breath", "blue", bps=1.0, brightness=0.5)
            print(f"{OK} rgb_strip.set_mode('breath','blue')")
            time.sleep(0.5)
            strip.close()
            print(f"{OK} rgb_strip.close()")
            return True
        except Exception as e:
            print(f"{FAIL} rgb_strip control: {e}")
            return False
    except Exception as e:
        print(f"{FAIL} LED: {e}")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PiDog Hardware Check (run on the robot)")
    parser.add_argument(
        "--scope",
        choices=["all", "sensors", "motion", "audio", "led"],
        default="all",
        help="Limit what to test",
    )
    parser.add_argument("--move", action="store_true", help="Allow limited motion tests")
    parser.add_argument("--sound", type=str, default="single_bark_1", help="Sound name for audio test")
    parser.add_argument("--volume", type=int, default=60, help="Audio volume 0-100")
    args = parser.parse_args(argv)

    check_environment()
    dog = get_dog()
    if dog is None:
        print("\nSummary\n-------\nResult: FAILURE (no Pidog instance)")
        return 1

    overall_ok = True
    try:
        if args.scope in ("all", "sensors"):
            overall_ok &= test_distance(dog)
            overall_ok &= test_imu(dog)
            overall_ok &= test_ears(dog)
            overall_ok &= test_touch(dog)
            if args.move:
                overall_ok &= test_head_scan(dog)

        if args.scope in ("all", "motion") and args.move:
            overall_ok &= test_motion(dog)
        elif args.scope == "motion" and not args.move:
            print(f"{FAIL} motion scope requested but --move not provided (skipping)")

        if args.scope in ("all", "audio"):
            overall_ok &= test_audio(dog, args.sound, args.volume)

        if args.scope in ("all", "led"):
            overall_ok &= test_led(dog)
    finally:
        try:
            # Center head and close safely
            hm = getattr(dog, "head_move", None)
            if callable(hm):
                hm([[0, 0, 0]], speed=50)
            wait_done = getattr(dog, "wait_head_done", None)
            if callable(wait_done):
                wait_done()
        except Exception:
            pass
        try:
            _close = getattr(dog, "close", None)
            if callable(_close):
                _close()
        except Exception:
            pass

    print("\nSummary")
    print("-------")
    print(f"Result: {'SUCCESS' if overall_ok else 'FAILURE'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
