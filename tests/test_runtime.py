import signal
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


class StopAskingModule(Module):
    """Asks the runtime to stop from inside a tick, the way a signal handler does."""

    def __init__(self, name: str = "stopper") -> None:
        super().__init__(name)
        self.runtime: HoundMindRuntime | None = None
        self.count = 0
        self.stopped = False

    def tick(self, context) -> None:
        self.count += 1
        if self.runtime is not None:
            self.runtime.request_stop("SIGTERM received")

    def stop(self, context) -> None:
        self.stopped = True


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


class StopSignalTests(unittest.TestCase):
    """`systemctl stop` sends SIGTERM, which used to end the process without unwinding (#212)."""

    def test_a_stop_request_ends_the_loop_and_runs_stop(self) -> None:
        config = Config(loop=LoopConfig(tick_hz=1000, max_cycles=50), modules={}, settings={})
        stopper = StopAskingModule()
        counter = CounterModule()
        runtime = HoundMindRuntime(config, [stopper, counter])
        stopper.runtime = runtime

        runtime.run()

        self.assertEqual(stopper.count, 1)
        self.assertTrue(runtime.stop_requested)
        self.assertEqual(runtime.stop_reason, "SIGTERM received")
        # The modules were stopped, which is the whole point: the HAL closes and the servos relax.
        self.assertTrue(stopper.stopped)
        # It ended on the request, well before the cycle budget would have ended it.
        self.assertLess(counter.count, 50)

    def test_the_sigterm_handler_asks_for_a_stop_without_raising(self) -> None:
        """A raising handler would land inside `tick()`'s per-module `except Exception`."""
        config = Config(loop=LoopConfig(tick_hz=1000, max_cycles=1), modules={}, settings={})
        runtime = HoundMindRuntime(config, [])
        restore = runtime._install_stop_signals()
        try:
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            handler(signal.SIGTERM, None)  # type: ignore[operator]
        finally:
            restore()

        self.assertTrue(runtime.stop_requested)
        self.assertIn("SIGTERM", runtime.stop_reason or "")

    def test_the_first_stop_reason_wins(self) -> None:
        config = Config(loop=LoopConfig(tick_hz=1000, max_cycles=1), modules={}, settings={})
        runtime = HoundMindRuntime(config, [])

        runtime.request_stop("SIGTERM received")
        runtime.request_stop("SIGHUP received")

        self.assertEqual(runtime.stop_reason, "SIGTERM received")


if __name__ == "__main__":
    unittest.main()
