#!/usr/bin/env python3
"""
PiDog AI Setup Script
====================

This script helps you set up and test your PiDog AI configuration.
"""

import sys
import os

# Ensure repo root in sys.path when run from tools/
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _tools_dir = os.path.abspath(os.path.dirname(__file__))
    _repo_root = os.path.abspath(os.path.join(_tools_dir, os.pardir))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)


def main():
    print("🐕 PiDog AI Setup Assistant")
    print("===========================")
    print()

    # Test configuration import from packmind
    try:
        from packmind.packmind_config import load_config, validate_config  # type: ignore
        print("✅ Configuration system available (packmind/packmind_config.py)")
    except Exception as e:
        print(f"❌ Configuration import failed: {e}")
        print("   Ensure you're running from the repo root and Python can import 'packmind'.")
        return False

    # Test all presets
    presets = ["default", "simple", "advanced", "indoor", "explorer"]
    print("\n📋 Available Configuration Presets:")

    for preset in presets:
        try:
            config = load_config(preset)
            warnings = validate_config(config)

            status = "⚠️" if warnings else "✅"
            slam = getattr(config, "ENABLE_SLAM_MAPPING", False)
            speed = getattr(config, "SPEED_NORMAL", "-")
            print(f"{status} {preset.title():10} - SLAM: {'✓' if slam else '✗'} Speed: {speed}")

            if warnings and preset == "default":
                print("   Warnings:")
                for warning in warnings:
                    print(f"     - {warning}")

        except Exception as e:
            print(f"❌ {preset.title():10} - Error: {e}")
    
    print("\n🔧 Dependency Check:")
    
    # Check PiDog library
    try:
        from pidog import Pidog
        print("✅ PiDog library available")
    except ImportError:
        print("❌ PiDog library not found")
        print("   Install: pip install pidog")
    
    # Check voice recognition
    try:
        import speech_recognition as sr
        import pyaudio
        print("✅ Voice recognition available (speech_recognition + pyaudio)")
    except ImportError:
        print("⚠️ Voice recognition not available")
        print("   Install: pip install SpeechRecognition pyaudio")
    
    # Check SLAM dependencies
    try:
        import numpy as np
        print("✅ NumPy available (required for SLAM)")
    except ImportError:
        print("⚠️ NumPy not available (SLAM features disabled)")
        print("   Install: pip install numpy")
    
    print("\n🎯 Quick Configuration Test:")
    try:
        from packmind.packmind_config import load_config  # type: ignore

        # Test configuration loading
        config = load_config("default")
        print(f"   Default speeds: Walk={getattr(config, 'SPEED_NORMAL', '-')}, Turn={getattr(config, 'SPEED_TURN_NORMAL', '-')}")
        print(f"   Obstacle threshold: {getattr(config, 'OBSTACLE_IMMEDIATE_THREAT', '-')}cm")
        print(f"   Wake word: '{getattr(config, 'WAKE_WORD', '-')}'")

        # Recommend preset based on dependencies
        print("\n💡 Recommended Configuration:")

        has_numpy = True
        has_voice = True
        try:
            import numpy  # noqa: F401
        except ImportError:
            has_numpy = False

        try:
            import speech_recognition  # noqa: F401
            import pyaudio  # noqa: F401
        except ImportError:
            has_voice = False

        if has_numpy and has_voice:
            print("   🚀 'advanced' preset - Full AI capabilities")
        elif has_numpy:
            print("   🏠 'indoor' preset - SLAM mapping without voice")
        else:
            print("   🔧 'simple' preset - Basic obstacle avoidance")
    except Exception as e:
        print(f"   Error testing configuration: {e}")
    
    print("\n🚀 Ready to Start!")
    print("   Run: python3 packmind/orchestrator.py")
    print("   Or:  python3 packmind.py")
    print("\n📚 Voice Commands (when enabled):")
    print("   'PiDog, status' - Show current status")
    print("   'PiDog, show config' - Display configuration") 
    print("   'PiDog, load simple config' - Switch to simple mode")
    print("   'PiDog, test walk normal' - Test movement calibration")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)