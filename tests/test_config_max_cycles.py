from houndmind_ai.core.config import Config


def test_max_cycles_coercion_numeric_string():
    raw = {"loop": {"tick_hz": "5", "max_cycles": "3"}}
    cfg = Config.from_dict(raw)
    assert cfg.loop.tick_hz == 5
    assert cfg.loop.max_cycles == 3


def test_max_cycles_none_and_invalid():
    raw_none = {"loop": {"tick_hz": 5}}
    cfg_none = Config.from_dict(raw_none)
    assert cfg_none.loop.max_cycles is None

    raw_invalid = {"loop": {"tick_hz": 5, "max_cycles": "notint"}}
    cfg_invalid = Config.from_dict(raw_invalid)
    assert cfg_invalid.loop.max_cycles is None
