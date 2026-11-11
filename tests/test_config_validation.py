import unittest

from houndmind_ai.core.config import Config, LoopConfig, load_config, validate_config


def make_config(settings: dict) -> Config:
    """A config whose per-value types are already valid; only the relations are in question."""
    return Config(loop=LoopConfig(tick_hz=5, max_cycles=None), modules={}, settings=settings)


class ConfigValidationTests(unittest.TestCase):
    """The cross-field half of validation.

    Per-value typing is enforced by `kernel/config_schema.py` before this runs, so a test here
    always starts from values that would load — only their relationship can be wrong.
    """

    def test_distance_bounds_are_ordered(self) -> None:
        warnings = validate_config(make_config({"sensors": {"distance_min_cm": 200, "distance_max_cm": 2}}))
        self.assertIn("sensors.distance_min_cm should be less than distance_max_cm", warnings)

    def test_poll_rate_is_capped_by_performance(self) -> None:
        config = make_config(
            {
                "sensors": {"poll_hz": 50},
                "performance": {"sensor_poll_hz_max": 20},
            }
        )
        self.assertIn(
            "sensors.poll_hz exceeds performance.sensor_poll_hz_max", validate_config(config)
        )

    def test_scan_interval_must_sit_inside_its_bounds(self) -> None:
        warnings = validate_config(
            make_config(
                {
                    "navigation": {
                        "scan_interval_s": 5.0,
                        "scan_interval_min_s": 0.2,
                        "scan_interval_max_s": 2.0,
                    }
                }
            )
        )
        self.assertIn(
            "navigation.scan_interval_s is above performance.scan_interval_max_s", warnings
        )

    def test_safety_distances_are_ordered(self) -> None:
        warnings = validate_config(
            make_config(
                {
                    "navigation": {
                        "emergency_stop_cm": 30,
                        "min_distance_cm": 15,
                        "safe_distance_cm": 10,
                    }
                }
            )
        )
        self.assertIn(
            "navigation.emergency_stop_cm should be less than min_distance_cm", warnings
        )
        self.assertIn(
            "navigation.min_distance_cm should be less than safe_distance_cm", warnings
        )

    def test_stuck_detection_needs_more_than_two_samples(self) -> None:
        warnings = validate_config(make_config({"navigation": {"stuck_min_samples": 2}}))
        self.assertIn("navigation.stuck_min_samples should be >= 3", warnings)

    def test_turn_speed_should_exceed_walk_speed(self) -> None:
        warnings = validate_config(
            make_config({"movement": {"speed_normal": 200, "speed_turn_normal": 100}})
        )
        self.assertIn(
            "movement.speed_turn_normal should be faster than speed_normal", warnings
        )

    def test_a_huge_log_buffer_is_flagged(self) -> None:
        warnings = validate_config(make_config({"logging": {"log_max_entries": 100000}}))
        self.assertIn(
            "logging.log_max_entries is large and may use significant memory", warnings
        )

    def test_override_priority_must_keep_safety(self) -> None:
        warnings = validate_config(
            make_config({"safety": {"override_priority": ["watchdog", "behavior"]}})
        )
        self.assertIn("safety.override_priority should include 'safety'", warnings)

    def test_the_shipped_config_earns_no_warnings(self) -> None:
        """A repo that ships a config its own validator complains about is a broken signal."""
        self.assertEqual(validate_config(load_config()), [])


if __name__ == "__main__":
    unittest.main()
