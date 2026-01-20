from __future__ import annotations

import argparse
import time


def _read_distance(dog) -> float | None:
    try:
        if hasattr(dog, "read_distance"):
            return float(dog.read_distance())
        return float(dog.ultrasonic.read_distance())
    except Exception:
        return None


def _read_touch(dog) -> str | None:
    try:
        return dog.dual_touch.read() or "N"
    except Exception:
        return None


def _read_sound(dog) -> tuple[bool | None, int | None]:
    try:
        detected = bool(dog.ears.isdetected())
        direction = int(dog.ears.read())
        return detected, direction
    except Exception:
        return None, None


def _read_imu(
    dog,
) -> tuple[tuple[float, float, float] | None, tuple[float, float, float] | None]:
    try:
        acc_raw = dog.accData
        gyro_raw = dog.gyroData
        acc = (float(acc_raw[0]), float(acc_raw[1]), float(acc_raw[2]))
        gyro = (float(gyro_raw[0]), float(gyro_raw[1]), float(gyro_raw[2]))
        return acc, gyro
    except Exception:
        return None, None


def _safe_action(dog, action: str, speed: int = 180) -> None:
    try:
        dog.do_action(action.replace(" ", "_"), step_count=1, speed=speed)
        if hasattr(dog, "wait_all_done"):
            dog.wait_all_done()
    except Exception:
        pass


def _head_move(dog, yaw: int, speed: int = 70) -> None:
    try:
        dog.head_move([[int(yaw), 0, 0]], speed=speed)
        if hasattr(dog, "wait_head_done"):
            dog.wait_head_done()
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PiDog hardware checkup (sensors + minimal motion)"
    )
    parser.add_argument(
        "--skip-motion", action="store_true", help="Do not run any motion actions"
    )
    parser.add_argument(
        "--pause", type=float, default=0.6, help="Pause between steps (seconds)"
    )
    args = parser.parse_args()

    from pidog import Pidog  # type: ignore

    dog = Pidog()
    try:
        print("[checkup] Reading sensors...")
        distance = _read_distance(dog)
        touch = _read_touch(dog)
        sound_detected, sound_dir = _read_sound(dog)
        acc, gyro = _read_imu(dog)

        print(f"[checkup] distance_cm: {distance}")
        print(f"[checkup] touch: {touch}")
        print(f"[checkup] sound: detected={sound_detected} dir={sound_dir}")
        print(f"[checkup] acc: {acc}")
        print(f"[checkup] gyro: {gyro}")

        if args.skip_motion:
            print("[checkup] Motion skipped.")
            return

        print("[checkup] Running minimal motion...")
        _safe_action(dog, "stand")
        time.sleep(args.pause)
        _safe_action(dog, "turn left")
        time.sleep(args.pause)
        _safe_action(dog, "turn right")
        time.sleep(args.pause)
        _head_move(dog, -30)
        time.sleep(args.pause)
        _head_move(dog, 30)
        time.sleep(args.pause)
        _head_move(dog, 0)
        print("[checkup] Done.")
    finally:
        try:
            dog.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
