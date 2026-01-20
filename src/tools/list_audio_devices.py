from __future__ import annotations

import argparse
import platform
import subprocess
import sys


def _print_sounddevice_devices() -> bool:
    try:
        import sounddevice as sd  # type: ignore
    except Exception:
        return False

    devices = sd.query_devices()
    if not devices:
        print("[audio] No devices found via sounddevice")
        return True

    print("[audio] Devices (sounddevice):")
    for idx, dev in enumerate(devices):
        name = dev.get("name", "unknown")
        hostapi = dev.get("hostapi", "?")
        max_in = dev.get("max_input_channels", 0)
        max_out = dev.get("max_output_channels", 0)
        print(f"  [{idx}] {name} (hostapi={hostapi}) in={max_in} out={max_out}")
    return True


def _run_cmd(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except Exception:
        return False
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        print(output.strip())
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List audio devices for HoundMind setup"
    )
    parser.parse_args()

    if _print_sounddevice_devices():
        return

    system = platform.system().lower()
    if system == "linux":
        print("[audio] sounddevice not available; trying arecord/aplay")
        ok_in = _run_cmd(["arecord", "-l"])
        ok_out = _run_cmd(["aplay", "-l"])
        if ok_in or ok_out:
            return

    print("[audio] Unable to list devices (install sounddevice or use OS tools).")
    sys.exit(1)


if __name__ == "__main__":
    main()
