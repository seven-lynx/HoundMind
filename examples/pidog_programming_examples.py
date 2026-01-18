"""HoundMind Pi3 examples (hardware-only).

Run with:
    python examples/pidog_programming_examples.py
"""

from __future__ import annotations

import time

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.main import build_modules


def run_runtime(cycles: int = 50) -> None:
    config = load_config()
    config.loop.max_cycles = cycles
    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()


def main() -> None:
    print("HoundMind Pi3 example: run runtime for 50 cycles")
    run_runtime(50)
    time.sleep(0.5)


if __name__ == "__main__":
    main()
