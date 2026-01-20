"""Beginner-friendly PiDog programming examples.

This script provides a small interactive menu of safe examples you can
run on your development machine. By default examples run with hardware
modules disabled so you can explore behaviors and logs without moving
servos or requiring sensors.

Run with:
    python examples/pidog_programming_examples.py

Use the menu to select a demo or let it cycle through all of them.
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.main import build_modules


def _safe_disable_hardware(config) -> None:
    """Disable potentially dangerous hardware modules for desktop demos."""
    for key in (
        "hal_motors",
        "hal_sensors",
        "vision",
        "vision_pi4",
        "face_recognition",
        "semantic_labeler",
        "voice",
    ):
        mod = config.modules.get(key)
        if mod is not None:
            mod.enabled = False


def run_runtime(cycles: int = 50, disable_hardware: bool = True) -> None:
    """Load config, apply safe defaults, build modules and run for N cycles."""
    config = load_config()
    config.loop.max_cycles = cycles
    if disable_hardware:
        _safe_disable_hardware(config)
    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()


def example_autonomy_personality_demo() -> None:
    """Demonstrate personality bias: higher curiosity favors explore mode."""
    print("Running: Autonomy Personality Demo (curiosity boosted)")
    config = load_config()
    # safe defaults for desktop demos
    _safe_disable_hardware(config)
    config.loop.max_cycles = 30
    # apply personality multipliers via settings dict
    settings = config.settings or {}
    settings["personality"] = {"curiosity": 5.0, "sociability": 0.2, "activity": 0.5, "apply_to_autonomy": True}
    config.settings = settings
    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()


def example_micro_idle_demo() -> None:
    """Show micro-idle behaviors by increasing chance and frequency."""
    print("Running: Micro-idle Demo (high chance)")
    config = load_config()
    _safe_disable_hardware(config)
    config.loop.max_cycles = 40
    settings = config.settings or {}
    behavior = settings.get("behavior", {})
    behavior["micro_idle_enabled"] = True
    behavior["micro_idle_chance"] = 0.8
    behavior["micro_idle_interval_s"] = 1.0
    settings["behavior"] = behavior
    config.settings = settings
    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()


def example_autonomy_cycle_demo() -> None:
    """Cycle through autonomy modes deterministically to observe behavior choices."""
    print("Running: Autonomy Cycle Demo (weights adjusted)")
    config = load_config()
    _safe_disable_hardware(config)
    config.loop.max_cycles = 36
    settings = config.settings or {}
    # Bias weights so modes rotate visibly
    behavior = settings.get("behavior", {})
    behavior["autonomy_weights"] = {"idle": 1.0, "patrol": 2.0, "explore": 3.0, "interact": 1.0, "play": 1.0, "rest": 0.5}
    settings["behavior"] = behavior
    config.settings = settings
    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()


def example_quick_runtime_demo() -> None:
    """Simple runtime run for quick observation (safe defaults)."""
    print("Running: Quick Runtime Demo (50 cycles)")
    run_runtime(50, disable_hardware=True)


EXAMPLES: list[tuple[str, Callable[[], None]]] = [
    ("Quick runtime demo", example_quick_runtime_demo),
    ("Autonomy personality demo", example_autonomy_personality_demo),
    ("Micro-idle demo", example_micro_idle_demo),
    ("Autonomy cycle demo", example_autonomy_cycle_demo),
]


def _print_menu(items: Sequence[tuple[str, Callable[[], None]]]) -> None:
    print("\nPiDog Programming Examples — choose an option:\n")
    for i, (label, _) in enumerate(items, start=1):
        print(f"  {i}) {label}")
    print("  a) Run all examples sequentially")
    print("  q) Quit")


def main() -> None:
    while True:
        _print_menu(EXAMPLES)
        choice = input("Select an option: ").strip().lower()
        if choice == "q":
            print("Goodbye.")
            return
        if choice == "a":
            for label, fn in EXAMPLES:
                print(f"\n--- {label} ---")
                try:
                    fn()
                except KeyboardInterrupt:
                    print("Demo interrupted.")
                time.sleep(0.5)
            print("All examples completed.")
            continue
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(EXAMPLES):
                label, fn = EXAMPLES[idx]
                print(f"\n--- {label} ---")
                try:
                    fn()
                except KeyboardInterrupt:
                    print("Demo interrupted.")
                time.sleep(0.5)
            else:
                print("Invalid selection.")
        except ValueError:
            print("Invalid selection.")


if __name__ == "__main__":
    main()
