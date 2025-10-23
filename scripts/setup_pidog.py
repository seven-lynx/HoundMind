#!/usr/bin/env python3
"""
PiDog AI Setup Script
====================

This script helps you set up and test your PiDog AI configuration.
"""

import sys
import os

def main():
    print("🐕 PiDog AI Setup Assistant")
    print("===========================")
    print()
    
    # Check if config file exists
    config_exists = os.path.exists("packmind_config.py")
    
    if config_exists:
        print("✅ packmind_config.py found")
        
        # Test import
        try:
            from packmind_config import load_config, validate_config
            print("✅ Configuration system working")
            
            # Test all presets
            presets = ["default", "simple", "advanced", "indoor", "explorer"]
            print("\n📋 Available Configuration Presets:")
            
            for preset in presets:
                try:
                    config = load_config(preset)
                    warnings = validate_config(config)
                    
                    status = "⚠️" if warnings else "✅"
                    print(f"{status} {preset.title():10} - SLAM: {'✓' if config.ENABLE_SLAM_MAPPING else '✗'} Speed: {config.SPEED_NORMAL}")
                    
                    if warnings and preset == "default":
                        print("   Warnings:")
                        for warning in warnings:
                            print(f"     - {warning}")
                            
                except Exception as e:
                    print(f"❌ {preset.title():10} - Error: {e}")
                    
        except ImportError as e:
            print(f"❌ Configuration import failed: {e}")
            return False
            
    else:
        print("❌ packmind_config.py not found")
        print("\n💡 To set up configuration:")
        print("   1. The packmind_config.py file should be in the same directory")
        print("   2. Copy it from the provided template")
        print("   3. Edit the PiDogConfig class values as needed")
        return False
    
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
        print("   Install: pip install speech_recognition pyaudio")
    
    # Check SLAM dependencies
    try:
        import numpy as np
        print("✅ NumPy available (required for SLAM)")
    except ImportError:
        print("⚠️ NumPy not available (SLAM features disabled)")
        print("   Install: pip install numpy")
    
    print("\n🎯 Quick Configuration Test:")
    
    if config_exists:
        try:
            from packmind_config import load_config
            
            # Test configuration loading
            config = load_config("default")
            print(f"   Default speeds: Walk={config.SPEED_NORMAL}, Turn={config.SPEED_TURN_NORMAL}")
            print(f"   Obstacle threshold: {config.OBSTACLE_IMMEDIATE_THREAT}cm")
            print(f"   Wake word: '{config.WAKE_WORD}'")
            
            # Recommend preset based on dependencies
            print("\n💡 Recommended Configuration:")
            
            has_numpy = True
            has_voice = True
            try:
                import numpy
            except ImportError:
                has_numpy = False
            
            try:
                import speech_recognition, pyaudio
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
    print("   Run: python3 advanced_pidog_ai.py")
    print("   Or:  python advanced_pidog_ai.py")
    print("\n📚 Voice Commands (when enabled):")
    print("   'PiDog, status' - Show current status")
    print("   'PiDog, show config' - Display configuration") 
    print("   'PiDog, load simple config' - Switch to simple mode")
    print("   'PiDog, test walk normal' - Test movement calibration")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)