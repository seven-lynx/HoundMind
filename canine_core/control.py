#!/usr/bin/env python3
"""
CanineCore Control Script
- Pick modules from a list to run
- Or run a natural random cycle across modes

Beginner-friendly: shows common presets and behavior aliases.
"""
import asyncio
from typing import List

from canine_core.core.orchestrator import Orchestrator
from canine_core.config.canine_config import PRESETS, CanineConfig

ALIASES = [
    "idle_behavior",
    "smart_patrol",
    "smarter_patrol",
    "voice_patrol",
    "guard_mode",
    "whisper_voice_control",
    "find_open_space",
]


def prompt_menu(title: str, options: List[str]) -> int:
    print("\n" + title)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    while True:
        choice = input("Select an option: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return int(choice) - 1
        print("Please enter a valid number.")


def main() -> None:
    print("\n=== CanineCore Control ===")
    modes = ["Run a single module", "Run a custom sequence", "Run random cycle", "Run a preset"]
    mode_idx = prompt_menu("Choose a mode:", modes)

    # Build orchestrator (uses CanineConfig by default; for presets we re-create with the selected name)
    orch = Orchestrator(config_path=None)

    if mode_idx == 0:  # single
        idx = prompt_menu("Pick a module to run once:", ALIASES)
        spec = ALIASES[idx]
        dur = input("Duration in seconds (default 20): ").strip() or "20"
        asyncio.run(orch.run_single(spec, float(dur)))

    elif mode_idx == 1:  # sequence
        print("Pick modules (comma-separated indices), e.g. 1,3,5")
        for i, a in enumerate(ALIASES, 1):
            print(f"  {i}. {a}")
        raw = input("Your picks: ").strip()
        indices = [int(x)-1 for x in raw.split(',') if x.strip().isdigit() and 1 <= int(x) <= len(ALIASES)]
        seq = [ALIASES[i] for i in indices] or ["idle_behavior"]
        dur = input("Duration per module (seconds, default 20): ").strip() or "20"
        asyncio.run(orch.run_sequence(seq, [float(dur)] * len(seq)))

    elif mode_idx == 2:  # random cycle
        dur_min = input("Min duration (default 20): ").strip() or "20"
        dur_max = input("Max duration (default 45): ").strip() or "45"
        print("Cycling randomly across:")
        print(", ".join(ALIASES))
        asyncio.run(orch.run_random_cycle(ALIASES, float(dur_min), float(dur_max)))

    else:  # preset
        names = list(PRESETS.keys())
        idx = prompt_menu("Choose a preset:", names)
        preset_name = names[idx]
        cfg_cls = PRESETS[preset_name]
        cfg = cfg_cls()
        # Recreate orchestrator with the preset so its settings apply to services/behavior
        orch = Orchestrator(config_path=preset_name)
        # Choose available behaviors from preset
        choices = getattr(cfg, 'AVAILABLE_BEHAVIORS', ALIASES)
        print(f"Running preset '{preset_name}' across: {', '.join(choices)}")
        asyncio.run(orch.run_random_cycle(choices, cfg.PATROL_DURATION_MIN, cfg.PATROL_DURATION_MAX))


if __name__ == "__main__":
    main()
