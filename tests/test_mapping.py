from houndmind_ai.mapping.mapper import MappingModule


def test_analyze_scan_openings_basic():
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

    # Provide a simple sweep with three angles: left=120cm, fwd=80cm, right=60cm
    angles = {"-60": 120.0, "0": 80.0, "60": 60.0}
    openings, safe_paths, best_path = MappingModule._analyze_scan_openings(
        angles, settings
    )

    assert isinstance(openings, list)
    assert isinstance(safe_paths, list)
    # Best path should be a dict and correspond to the longest/widest candidate
    assert best_path is not None
    assert best_path.get("distance_cm", 0) >= 60
