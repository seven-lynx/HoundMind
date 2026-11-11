from __future__ import annotations

import argparse
import logging
import socket
from pathlib import Path

from houndmind_ai.act.gateway import MotionGatewayModule
from houndmind_ai.behavior.attention import AttentionModule
from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.behavior.habituation import HabituationModule
from houndmind_ai.calibration.workflow import CalibrationModule
from houndmind_ai.core.config import load_config
from houndmind_ai.core.logging_setup import setup_logging
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.hal.module import HalModule
from houndmind_ai.hal.motors import MotorModule
from houndmind_ai.hal.sensors import SensorModule
from houndmind_ai.kernel.config_schema import ConfigError
from houndmind_ai.kernel.registry import Capability, ModuleRegistry
from houndmind_ai.logging.event_logger import EventLoggerModule
from houndmind_ai.logging.led_manager import LedManagerModule
from houndmind_ai.mapping import default_path_planning_hook
from houndmind_ai.mapping.mapper import MappingModule
from houndmind_ai.navigation.local_planner import LocalPlannerModule
from houndmind_ai.navigation.obstacle_avoidance import ObstacleAvoidanceModule
from houndmind_ai.navigation.orientation import OrientationModule
from houndmind_ai.navigation.scanning import ScanningModule
from houndmind_ai.optional.energy_emotion import EnergyEmotionModule
from houndmind_ai.optional.face_recognition import FaceRecognitionModule
from houndmind_ai.optional.semantic_labeler import SemanticLabelerModule
from houndmind_ai.optional.slam_pi4 import SlamPi4Module
from houndmind_ai.optional.telemetry_dashboard import TelemetryDashboardModule
from houndmind_ai.optional.vision import VisionModule
from houndmind_ai.optional.vision_pi4 import VisionPi4Module
from houndmind_ai.optional.voice import VoiceModule
from houndmind_ai.perception.fusion import PerceptionModule
from houndmind_ai.safety.balance import BalanceModule
from houndmind_ai.safety.health_monitor import HealthMonitorModule
from houndmind_ai.safety.sensor_health import SensorHealthModule
from houndmind_ai.safety.service_watchdog import ServiceWatchdogModule
from houndmind_ai.safety.supervisor import SafetyModule
from houndmind_ai.safety.watchdog import WatchdogModule

logger = logging.getLogger(__name__)


def build_registry(config, hal: DogHAL | None = None) -> ModuleRegistry:
    """Construct the module list and register capabilities.

    Registration order is tick order. The HAL module comes first because every hardware-facing
    module asks the context for `hal`; the gateway sits immediately before the motors so a
    decision made this tick is the one executed this tick; producers that run later (safety,
    watchdog, behaviour) publish intent for the *next* tick, exactly as before.

    `hal` is the test seam: pass `FakeDogHAL()` and the whole runtime runs on a scripted dog.
    """
    module_configs = config.modules or {}

    # module_configs may be a dict (from JSON) or an object; normalize to dicts
    def cfg(name: str) -> dict:
        val = module_configs.get(name, {})
        return val if isinstance(val, dict) else getattr(val, "__dict__", {})

    registry = ModuleRegistry()
    registry.register(HalModule("hal", **cfg("hal"), hal=hal), [Capability.SAFETY])
    registry.register(SensorModule("hal_sensors", **cfg("hal_sensors")), [Capability.SENSORS])
    registry.register(
        MotionGatewayModule("motion_gateway", **cfg("motion_gateway")), [Capability.SAFETY]
    )
    registry.register(MotorModule("hal_motors", **cfg("hal_motors")), [Capability.MOTION])
    registry.register(PerceptionModule("perception", **cfg("perception")), [Capability.PERCEPTION])
    registry.register(ScanningModule("scanning", **cfg("scanning")), [Capability.NAVIGATION])
    registry.register(OrientationModule("orientation", **cfg("orientation")), [Capability.NAVIGATION])
    registry.register(CalibrationModule("calibration", **cfg("calibration")), [Capability.CALIBRATION])
    registry.register(MappingModule("mapping", **cfg("mapping")), [Capability.MAPPING])
    registry.register(LocalPlannerModule("local_planner", **cfg("navigation")), [Capability.NAVIGATION])
    registry.register(ObstacleAvoidanceModule("navigation", **cfg("navigation")), [Capability.NAVIGATION])
    registry.register(BehaviorModule("behavior", **cfg("behavior")), [Capability.BEHAVIOUR])
    registry.register(HabituationModule("habituation", **cfg("habituation")), [Capability.BEHAVIOUR])
    registry.register(AttentionModule("attention", **cfg("attention")), [Capability.BEHAVIOUR])
    registry.register(EventLoggerModule("event_log", **cfg("event_log")), [Capability.TELEMETRY])
    registry.register(LedManagerModule("led_manager", **cfg("led_manager")), [Capability.TELEMETRY])
    registry.register(HealthMonitorModule("health", **cfg("health")), [Capability.DIAGNOSTICS])
    registry.register(SensorHealthModule("sensor_health", **cfg("sensor_health")), [Capability.DIAGNOSTICS])
    registry.register(ServiceWatchdogModule("service_watchdog", **cfg("service_watchdog")), [Capability.SAFETY])
    registry.register(WatchdogModule("watchdog", **cfg("watchdog")), [Capability.SAFETY])
    registry.register(BalanceModule("balance", **cfg("balance")), [Capability.SAFETY])
    registry.register(SafetyModule("safety", **cfg("safety")), [Capability.SAFETY])
    registry.register(EnergyEmotionModule("energy_emotion", **cfg("energy_emotion")), [Capability.BEHAVIOUR])
    registry.register(VisionModule("vision", **cfg("vision")), [Capability.VISION])
    registry.register(VisionPi4Module("vision_pi4", **cfg("vision_pi4")), [Capability.VISION])
    registry.register(VoiceModule("voice", **cfg("voice")), [Capability.AUDIO])
    registry.register(FaceRecognitionModule("face_recognition", **cfg("face_recognition")), [Capability.VISION])
    registry.register(SemanticLabelerModule("semantic_labeler", **cfg("semantic_labeler")), [Capability.VISION])
    registry.register(SlamPi4Module("slam_pi4", **cfg("slam_pi4")), [Capability.MAPPING])
    registry.register(
        TelemetryDashboardModule("telemetry_dashboard", **cfg("telemetry_dashboard")),
        [Capability.TELEMETRY],
    )
    return registry


def build_modules(config, hal: DogHAL | None = None) -> list:
    """The tick list. Kept as a list for the runtime; the registry holds the capabilities."""
    return build_registry(config, hal=hal).modules()


def main() -> None:
    parser = argparse.ArgumentParser(description="HoundMind PiDog runtime")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to settings.jsonc",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        # A bad config must stop the process here, before any hardware is touched. Print the
        # problems in full: the operator cannot fix a file they cannot read the errors from.
        logger.error("%s", exc.format())
        raise SystemExit(2) from None

    context_filter = setup_logging((config.settings or {}).get("logging", {}))
    runtime = HoundMindRuntime(config, build_modules(config))

    # Bind the runtime context dict into logging so runtime keys (tick, module statuses)
    # flow into all log records automatically. Use hostname as a fallback device id.
    try:
        device = (config.settings or {}).get("device", {})
        device_id = device.get("device_id") if isinstance(device, dict) else None
        if not device_id:
            device_id = socket.gethostname()
    except Exception:
        logger.exception("Failed to determine device id; using hostname fallback")
        device_id = socket.gethostname()

    # Bind the context by callable, not by dict: the filter then reads through the store's
    # lock, so a log line from a background thread cannot race the loop (H-02).
    runtime.context.set("device_id", device_id)
    context_filter.set_context_source(runtime.context.get)

    # Register path planning hook for Pi4 if enabled
    mapping_settings = (config.settings or {}).get("mapping", {})
    if mapping_settings.get("path_planning_enabled", False):
        runtime.context.set("path_planning_hook", default_path_planning_hook)

    runtime.run()


if __name__ == "__main__":
    main()
