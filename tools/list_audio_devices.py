#!/usr/bin/env python3
"""
List audio input devices (microphones) with indexes.

- Uses PyAudio; prints guidance if PyAudio isn't installed.
- Works standalone; no repo imports required.

Usage:
  python tools/list_audio_devices.py
"""
from __future__ import annotations
import os
import sys

# Optional: repo-root bootstrap (not strictly needed here)
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _this = os.path.abspath(__file__)
    _root = os.path.dirname(os.path.dirname(_this))
    if _root not in sys.path:
        sys.path.insert(0, _root)

try:
    import pyaudio  # type: ignore
except Exception as e:
    print("[audio] PyAudio not installed.")
    if os.name == "nt":
        print("  Windows fix: pip install pipwin && pipwin install pyaudio")
    else:
        print("  Raspberry Pi fix: sudo apt install -y portaudio19-dev python3-dev && python3 -m pip install pyaudio")
        print("  Fallback: sudo apt install -y python3-pyaudio")
    print(f"  Error: {e}")
    raise SystemExit(2)

pa = pyaudio.PyAudio()
try:
    host_count = pa.get_host_api_count()
    print(f"Host APIs: {host_count}")
    try:
        default_idx = pa.get_default_input_device_info().get('index')  # type: ignore
    except Exception:
        default_idx = None
    print(f"Default input device index: {default_idx}")

    count = pa.get_device_count()
    print(f"\nDevices ({count}):")
    for i in range(count):
        try:
            info = pa.get_device_info_by_index(i)
        except Exception:
            continue
        name = info.get("name")
        host = info.get("hostApi")
        in_ch = info.get("maxInputChannels")
        rate = info.get("defaultSampleRate")
        mark = " (default)" if default_idx == i else ""
        print(f"[{i}] {name}{mark} | hostApi={host} | inputs={in_ch} | rate={rate}")
    print("\nTip: Set VOICE_MIC_INDEX in packmind/packmind_config.py to match the desired device index.")
finally:
    try:
        pa.terminate()
    except Exception:
        pass

raise SystemExit(0)
