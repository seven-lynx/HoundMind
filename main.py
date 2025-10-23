#!/usr/bin/env python3
"""
PiDog Modular System Entry Point
===============================

Entry point for the PiDog Modular System - a composable, extensible framework
for building custom PiDog behaviors and personalities.

🔧 MODULAR SYSTEM: Mix and match behaviors, create custom combinations
🤖 STANDALONE AIs: For ready-to-run complete AI systems, see standalone_ai/

Usage:
    python main.py

Author: seven-lynx
Version: 0.5.1
"""

import sys
import os

# Add the canine_core directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'canine_core'))

def main():
    """Main entry point for PiDog Modular System."""
    print("🔧 PiDog Modular System v0.5.1")
    print("=" * 50)
    print("🎭 Mix and match behaviors | 🧠 Custom AI combinations")
    print("🔄 Hot-swap modules | 💾 Learning and memory")
    print()
    print("� For standalone AI systems, run files in standalone_ai/ directly")
    print("=" * 50)
    
    try:
        from canine_core.core.orchestrator import main as core_main
        core_main()
    except ImportError as e:
        print(f"❌ Error importing modular system: {e}")
        print("Make sure all dependencies are installed and paths are correct.")
        print()
        print("📁 Expected structure:")
        print("   modular_system/core/master.py")
        print("   standalone_ai/*.py")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 PiDog modular system shutdown gracefully.")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()