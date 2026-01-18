import unittest

from houndmind_ai.core.config import Config, LoopConfig, validate_config


class ConfigValidationTests(unittest.TestCase):
    def test_loop_tick_invalid(self) -> None:
        config = Config(
            loop=LoopConfig(tick_hz=0, max_cycles=1), modules={}, settings={}
        )
        warnings = validate_config(config)
        self.assertIn("loop.tick_hz should be > 0", warnings)

    def test_attention_ranges(self) -> None:
        config = Config(
            loop=LoopConfig(tick_hz=5, max_cycles=1),
            modules={},
            settings={"attention": {"head_yaw_max_deg": 120, "sound_cooldown_s": -1}},
        )
        warnings = validate_config(config)
        self.assertIn("attention.head_yaw_max_deg should be in (0, 90]", warnings)
        self.assertIn("attention.sound_cooldown_s should be >= 0", warnings)

    def test_balance_ranges(self) -> None:
        config = Config(
            loop=LoopConfig(tick_hz=5, max_cycles=1),
            modules={},
            settings={
                "balance": {
                    "update_hz": -1,
                    "compensation_scale": -0.5,
                    "max_pitch_deg": 0,
                    "max_roll_deg": 0,
                    "lpf_alpha": 1.5,
                }
            },
        )
        warnings = validate_config(config)
        self.assertIn("balance.update_hz should be >= 0", warnings)
        self.assertIn("balance.compensation_scale should be >= 0", warnings)
        self.assertIn("balance.max_pitch_deg should be > 0", warnings)
        self.assertIn("balance.max_roll_deg should be > 0", warnings)
        self.assertIn("balance.lpf_alpha should be in (0, 1]", warnings)


if __name__ == "__main__":
    unittest.main()
