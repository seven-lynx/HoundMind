"""HoundMind mapping snapshot demo (no hardware required).

Run with:
    python examples/houndmind_mapping_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from houndmind_ai.mapping.mapper import MappingModule


def main() -> None:
    settings = {
        "opening_min_width_cm": 10,
        "opening_max_width_cm": 1000,
        "opening_cell_conf_min": 0.0,
        "safe_path_min_width_cm": 1,
        "safe_path_max_width_cm": 1000,
        "safe_path_cell_conf_min": 0.0,
        "safe_path_score_weight_width": 0.6,
        "safe_path_score_weight_distance": 0.4,
    }

    angles = {"-60": 120.0, "0": 80.0, "60": 60.0}
    openings, safe_paths, best_path = MappingModule._analyze_scan_openings(
        angles, settings
    )
    print("openings:", openings)
    print("safe_paths:", safe_paths)
    print("best_path:", best_path)


if __name__ == "__main__":
    main()
