from __future__ import annotations

import argparse
from pathlib import Path
import logging

from houndmind_ai.core.config import load_config
from houndmind_ai.core.logging_setup import setup_logging
import socket
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.motors import MotorModule
from houndmind_ai.hal.sensors import SensorModule
from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.behavior.attention import AttentionModule
from houndmind_ai.behavior.habituation import HabituationModule
from houndmind_ai.calibration.workflow import CalibrationModule
from houndmind_ai.mapping.mapper import MappingModule
from houndmind_ai.navigation.local_planner import LocalPlannerModule
from houndmind_ai.navigation.scanning import ScanningModule
from houndmind_ai.navigation.orientation import OrientationModule
from houndmind_ai.navigation.obstacle_avoidance import ObstacleAvoidanceModule
from houndmind_ai.perception.fusion import PerceptionModule
from houndmind_ai.logging.event_logger import EventLoggerModule
from houndmind_ai.logging.led_manager import LedManagerModule
from houndmind_ai.safety.health_monitor import HealthMonitorModule
from houndmind_ai.safety.service_watchdog import ServiceWatchdogModule
from houndmind_ai.safety.watchdog import WatchdogModule
from houndmind_ai.safety.supervisor import SafetyModule
from houndmind_ai.safety.balance import BalanceModule
from houndmind_ai.optional.voice import VoiceModule
from houndmind_ai.optional.face_recognition import FaceRecognitionModule
from houndmind_ai.optional.semantic_labeler import SemanticLabelerModule
from houndmind_ai.optional.slam_pi4 import SlamPi4Module
from houndmind_ai.optional.telemetry_dashboard import TelemetryDashboardModule
from houndmind_ai.optional.vision import VisionModule
from houndmind_ai.optional.vision_pi4 import VisionPi4Module
from houndmind_ai.optional.energy_emotion import EnergyEmotionModule
from houndmind_ai.mapping import default_path_planning_hook

logger = logging.getLogger(__name__)


def build_modules(config) -> list:
    module_configs = config.modules or {}
    # module_configs may be a dict (from JSON) or an object; normalize to dicts
    def cfg(name: str) -> dict:
        val = module_configs.get(name, {})
        return val if isinstance(val, dict) else getattr(val, "__dict__", {})

    return [
        SensorModule("hal_sensors", **cfg("hal_sensors")),
        MotorModule("hal_motors", **cfg("hal_motors")),
        PerceptionModule("perception", **cfg("perception")),
        ScanningModule("scanning", **cfg("scanning")),
        OrientationModule("orientation", **cfg("orientation")),
        CalibrationModule("calibration", **cfg("calibration")),
        MappingModule("mapping", **cfg("mapping")),
        LocalPlannerModule("local_planner", **cfg("navigation")),
        ObstacleAvoidanceModule("navigation", **cfg("navigation")),
        BehaviorModule("behavior", **cfg("behavior")),
        HabituationModule("habituation", **cfg("habituation")),
        AttentionModule("attention", **cfg("attention")),
        EventLoggerModule("event_log", **cfg("event_log")),
        LedManagerModule("led_manager", **cfg("led_manager")),
        HealthMonitorModule("health", **cfg("health")),
        ServiceWatchdogModule("service_watchdog", **cfg("service_watchdog")),
        WatchdogModule("watchdog", **cfg("watchdog")),
        BalanceModule("balance", **cfg("balance")),
        SafetyModule("safety", **cfg("safety")),
        EnergyEmotionModule("energy_emotion", **cfg("energy_emotion")),
        VisionModule("vision", **cfg("vision")),
        VisionPi4Module("vision_pi4", **cfg("vision_pi4")),
        VoiceModule("voice", **cfg("voice")),
        FaceRecognitionModule("face_recognition", **cfg("face_recognition")),
        SemanticLabelerModule("semantic_labeler", **cfg("semantic_labeler")),
        SlamPi4Module("slam_pi4", **cfg("slam_pi4")),
        TelemetryDashboardModule("telemetry_dashboard", **cfg("telemetry_dashboard")),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="HoundMind PiDog runtime")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to settings.jsonc",
    )
    args = parser.parse_args()

    config = load_config(args.config)
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

    # Attach the runtime's mutable dict so updates are reflected in logs.
    runtime.context.set("device_id", device_id)
    context_filter.set_context(runtime.context.data)

    # Register path planning hook for Pi4 if enabled
    mapping_settings = (config.settings or {}).get("mapping", {})
    if mapping_settings.get("path_planning_enabled", False):
        runtime.context.set("path_planning_hook", default_path_planning_hook)

    runtime.run()


if __name__ == "__main__":
    main()
