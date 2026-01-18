import unittest

from houndmind_ai.core.config import Config, LoopConfig
from houndmind_ai.core.module import Module, ModuleError
from houndmind_ai.core.runtime import HoundMindRuntime


class CounterModule(Module):
    def __init__(self, name: str = "counter") -> None:
        super().__init__(name)
        self.count = 0

    def tick(self, context) -> None:
        self.count += 1


class FailingModule(Module):
    def __init__(self, name: str = "fail", required: bool = False) -> None:
        super().__init__(name, required=required)

    def start(self, context) -> None:
        raise RuntimeError("boom")


class RuntimeTests(unittest.TestCase):
    def test_runtime_ticks(self) -> None:
        config = Config(
            loop=LoopConfig(tick_hz=1000, max_cycles=2), modules={}, settings={}
        )
        counter = CounterModule()
        runtime = HoundMindRuntime(config, [counter])
        runtime.run()
        self.assertEqual(counter.count, 2)

    def test_optional_module_failure_is_disabled(self) -> None:
        config = Config(
            loop=LoopConfig(tick_hz=1000, max_cycles=1), modules={}, settings={}
        )
        failing = FailingModule(required=False)
        counter = CounterModule()
        runtime = HoundMindRuntime(config, [failing, counter])
        runtime.run()
        self.assertFalse(failing.status.enabled)
        self.assertFalse(failing.status.started)
        self.assertGreaterEqual(counter.count, 1)

    def test_required_module_failure_raises(self) -> None:
        config = Config(
            loop=LoopConfig(tick_hz=1000, max_cycles=1), modules={}, settings={}
        )
        failing = FailingModule(required=True)
        runtime = HoundMindRuntime(config, [failing])
        with self.assertRaises(ModuleError):
            runtime.run()


if __name__ == "__main__":
    unittest.main()
