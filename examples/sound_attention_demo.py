"""Sound attention demo (Pi3 hardware-only).

Turns the head toward detected sound and uses LED attention signal.
Run with:
    python examples/sound_attention_demo.py
"""

from __future__ import annotations

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.main import build_modules


def main() -> None:
    config = load_config()
    # Ensure attention and LED manager are enabled for this demo.
    config.modules["attention"].enabled = True
    config.modules["led_manager"].enabled = True
    config.loop.max_cycles = 200
    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()


if __name__ == "__main__":
    main()
