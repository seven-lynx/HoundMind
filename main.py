#!/usr/bin/env python3
"""
CanineCore Entry Point
======================

Entry point for CanineCore – the modular, extensible framework for composing
PiDog behaviors and services.

🔧 CanineCore: Mix and match behaviors, create custom combinations
🤖 PackMind: For a standalone AI orchestrator, run packmind/orchestrator.py

Usage:
    python main.py

Author: seven-lynx
Version: 2025.10.24
"""

import sys
import os

# Add the canine_core directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'canine_core'))

def main():
    """Main entry point for CanineCore."""
    print("🔧 CanineCore v2025.10.24")
    print("=" * 50)
    print("🎭 Mix and match behaviors | 🧠 Custom AI combinations")
    print("🔄 Hot-swap modules | 💾 Learning and memory")
    print()
    print("🤖 For the standalone AI, run: python packmind/orchestrator.py (or python packmind.py)")
    print("=" * 50)
    
    try:
        from canine_core.core.orchestrator import main as core_main
        core_main()
    except ImportError as e:
        print(f"❌ Error importing CanineCore orchestrator: {e}")
        print("Make sure all dependencies are installed and paths are correct.")
        print()
        print("📁 Expected structure:")
        print("   canine_core/core/orchestrator.py")
        print("   packmind/orchestrator.py")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 CanineCore shutdown gracefully.")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()