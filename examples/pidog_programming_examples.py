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


def example_scripted_habituation_demo() -> None:
    """Simulate repeated stimuli to show habituation behavior.

    This demo starts the runtime (with hardware disabled), then injects
    repeated `perception` updates into the runtime context to trigger
    habituation logic. The example prints out emitted `behavior_action`
    and any `behavior_habituation` markers in the context so beginners
    can observe how repeated stimuli are suppressed.
    """
    print("Running: Scripted Habituation Demo (simulate repeated sounds)")
    config = load_config()
    _safe_disable_hardware(config)
    # Make habituation easy to trigger for the demo
    settings = config.settings or {}
    hab = settings.get("habituation", {})
    hab["enabled"] = True
    hab["window_s"] = 1.0
    hab["threshold"] = 3
    hab["recovery_s"] = 3.0
    settings["habituation"] = hab
    config.settings = settings

    runtime = HoundMindRuntime(config, build_modules(config))
    # Start modules manually so we can inject perception between ticks.
    runtime.start()
    try:
        # Simulate a burst of 6 sound events spaced 0.3s apart
        for i in range(6):
            runtime.context.set("perception", {"sound": True, "touch": "N", "obstacle": False})
            runtime.tick()
            # Print the last behavior action and any habituation flag
            action = runtime.context.get("behavior_action")
            hab_flag = runtime.context.get("behavior_habituation")
            print(f"tick {i+1}: action={action} hab={hab_flag}")
            time.sleep(0.3)

        # Now wait quiet period for recovery and tick a few more times
        print("Waiting for recovery window...")
        time.sleep(float(hab.get("recovery_s", 3.0)) + 0.5)
        for i in range(3):
            runtime.context.set("perception", {"sound": True, "touch": "N", "obstacle": False})
            runtime.tick()
            print(f"recovery tick {i+1}: action={runtime.context.get('behavior_action')} hab={runtime.context.get('behavior_habituation')}")
            time.sleep(0.3)
    finally:
        runtime.stop()


def example_energy_demo() -> None:
    """Show energy boosts and decay by injecting touch events.

    Demonstrates `settings.energy` behavior: enable it and then simulate
    touch stimuli that temporarily raise `energy_level`. The demo prints
    energy_level each tick so beginners can see decay and boosts.
    """
    print("Running: Energy Demo (simulate touch boosts)")
    config = load_config()
    _safe_disable_hardware(config)
    settings = config.settings or {}
    energy = settings.get("energy", {})
    energy["enabled"] = True
    energy["initial"] = 0.2
    energy["decay_per_tick"] = 0.02
    energy["boost_touch"] = 0.15
    settings["energy"] = energy
    config.settings = settings

    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.start()
    try:
        for i in range(20):
            # Inject a touch every 5 ticks
            touch = "T" if (i % 5 == 0) else "N"
            runtime.context.set("perception", {"sound": False, "touch": touch, "obstacle": False})
            runtime.tick()
            energy_lvl = runtime.context.get("energy_level")
            print(f"tick {i+1}: touch={touch} energy={energy_lvl}")
            time.sleep(0.2)
    finally:
        runtime.stop()


def example_scripted_stimuli_demo() -> None:
    """General demo that injects different stimuli and prints runtime snapshots.

    Useful for learning how modules communicate via the `RuntimeContext`.
    Beginners can inspect keys under `runtime.context.data` to explore state.
    """
    print("Running: Scripted Stimuli Demo (varied stimuli)")
    config = load_config()
    _safe_disable_hardware(config)
    config.loop.max_cycles = 20
    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.start()
    try:
        # Sequence: sound -> touch -> obstacle -> quiet
        seq = [
            {"sound": True, "touch": "N", "obstacle": False},
            {"sound": False, "touch": "T", "obstacle": False},
            {"sound": False, "touch": "N", "obstacle": True},
            {"sound": False, "touch": "N", "obstacle": False},
        ]
        for i in range(16):
            perception = seq[i % len(seq)]
            runtime.context.set("perception", perception)
            runtime.tick()
            # Dump a small snapshot for the beginner: behavior_action and module statuses
            print(
                {
                    "tick": i + 1,
                    "perception": perception,
                    "behavior_action": runtime.context.get("behavior_action"),
                    "module_statuses": runtime.context.get("module_statuses"),
                }
            )
            time.sleep(0.2)
    finally:
        runtime.stop()


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
        # Placeholder for future edits
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
    # Placeholder for future edits
