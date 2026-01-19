from __future__ import annotations

import argparse
from pathlib import Path

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


def build_modules(config) -> list:
    module_configs = config.modules
    return [
        SensorModule("hal_sensors", **module_configs.get("hal_sensors", {}).__dict__),
        MotorModule("hal_motors", **module_configs.get("hal_motors", {}).__dict__),
        PerceptionModule("perception", **module_configs.get("perception", {}).__dict__),
        ScanningModule("scanning", **module_configs.get("scanning", {}).__dict__),
        OrientationModule(
            "orientation", **module_configs.get("orientation", {}).__dict__
        ),
        CalibrationModule(
            "calibration", **module_configs.get("calibration", {}).__dict__
        ),
        MappingModule("mapping", **module_configs.get("mapping", {}).__dict__),
        LocalPlannerModule(
            "local_planner", **module_configs.get("navigation", {}).__dict__
        ),
        ObstacleAvoidanceModule(
            "navigation", **module_configs.get("navigation", {}).__dict__
        ),
        BehaviorModule("behavior", **module_configs.get("behavior", {}).__dict__),
        HabituationModule("habituation", **module_configs.get("habituation", {}).__dict__),
        AttentionModule("attention", **module_configs.get("attention", {}).__dict__),
        EventLoggerModule("event_log", **module_configs.get("event_log", {}).__dict__),
        LedManagerModule(
            "led_manager", **module_configs.get("led_manager", {}).__dict__
        ),
        HealthMonitorModule("health", **module_configs.get("health", {}).__dict__),
        ServiceWatchdogModule(
            "service_watchdog", **module_configs.get("service_watchdog", {}).__dict__
        ),
        WatchdogModule("watchdog", **module_configs.get("watchdog", {}).__dict__),
        BalanceModule("balance", **module_configs.get("balance", {}).__dict__),
        SafetyModule("safety", **module_configs.get("safety", {}).__dict__),
        EnergyEmotionModule(
            "energy_emotion", **module_configs.get("energy_emotion", {}).__dict__
        ),
        VisionModule("vision", **module_configs.get("vision", {}).__dict__),
        VisionPi4Module("vision_pi4", **module_configs.get("vision_pi4", {}).__dict__),
        VoiceModule("voice", **module_configs.get("voice", {}).__dict__),
        FaceRecognitionModule(
            "face_recognition", **module_configs.get("face_recognition", {}).__dict__
        ),
        SemanticLabelerModule(
            "semantic_labeler", **module_configs.get("semantic_labeler", {}).__dict__
        ),
        SlamPi4Module("slam_pi4", **module_configs.get("slam_pi4", {}).__dict__),
        TelemetryDashboardModule(
            "telemetry_dashboard",
            **module_configs.get("telemetry_dashboard", {}).__dict__,
        ),
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
