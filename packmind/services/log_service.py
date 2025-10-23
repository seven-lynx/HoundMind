from __future__ import annotations
from typing import Optional, Any, Dict, List
import logging
import time

class LogService:
    """
    File-backed patrol/event logging with an in-memory ring buffer.
    """

    def __init__(self, enabled: bool = True, file_path: Optional[str] = None, session_id: Optional[int] = None) -> None:
        self.enabled = enabled
        self.file_path = file_path
        self.session_id = session_id
        self.start_time = time.time()
        self.memory: List[Dict[str, Any]] = []
        self.max_entries = 1000
        # Optional Python logger for JSON events
        try:
            self._py_logger = logging.getLogger("packmind.events")
        except Exception:
            self._py_logger = None

    def log(self, event_type: str, description: str, state: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        ts = time.time()
        entry = {
            "session_id": self.session_id,
            "timestamp": ts,
            "elapsed_time": ts - self.start_time,
            "event_type": event_type,
            "description": description,
            **state,
            "additional_data": data or {}
        }
        self.memory.append(entry)
        if len(self.memory) > self.max_entries:
            self.memory = self.memory[-self.max_entries:]

        if self.file_path:
            try:
                with open(self.file_path, 'a', encoding='utf-8') as f:
                    line = f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] ({entry['elapsed_time']:6.1f}s) {event_type:12} | {description}"
                    f.write(line + "\n")
            except Exception:
                # Non-fatal on hosts without file permissions
                pass
        # Emit to Python logger if configured (JSON via formatter)
        try:
            if getattr(self, "_py_logger", None):
                self._py_logger.info(description, extra=entry)
        except Exception:
            pass

    def event(
        self,
        event_type: str,
        description: str,
        *,
        behavior_state: str,
        emotional_state: str,
        energy_level: float,
        scan_data: Dict[str, float],
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Convenience wrapper that normalizes state fields for patrol events.

        Stores flattened scan_* fields for easy grepping and keeps full
        details in additional_data when provided.
        """
        state = {
            "behavior_state": behavior_state,
            "emotional_state": emotional_state,
            "energy_level": round(float(energy_level), 3),
            "scan_forward": round(float(scan_data.get("forward", 0.0)), 1),
            "scan_left": round(float(scan_data.get("left", 0.0)), 1),
            "scan_right": round(float(scan_data.get("right", 0.0)), 1),
        }
        self.log(event_type, description, state, data)

    def generate_report(
        self,
        *,
        final_behavior: str,
        final_emotion: str,
        final_energy_level: float,
        final_scan_data: Dict[str, float],
    ) -> Dict[str, Any]:
        """Summarize this session from in-memory entries.

        Mirrors the structure previously returned by orchestrator.generate_patrol_report.
        """
        current_time = time.time()
        event_counts: Dict[str, int] = {}
        obstacles_detected = 0
        interactions = 0
        voice_commands = 0
        emotion_changes = 0

        for entry in self.memory:
            et = entry.get("event_type", "")
            event_counts[et] = event_counts.get(et, 0) + 1
            if et == "EMOTION_CHANGE":
                emotion_changes += 1
            elif et in ("THREAT_IMMEDIATE", "THREAT_APPROACHING"):
                obstacles_detected += 1
            elif et == "TOUCH_INTERACTION":
                interactions += 1
            elif et == "VOICE_COMMAND":
                voice_commands += 1

        report: Dict[str, Any] = {
            "session_info": {
                "session_id": self.session_id,
                "start_time": self.start_time,
                "end_time": current_time,
                "total_duration": current_time - self.start_time,
                "log_file": self.file_path,
            },
            "activity_summary": {
                "total_events": len(self.memory),
                "event_breakdown": event_counts,
                "obstacles_encountered": obstacles_detected,
                "interactions": interactions,
                "voice_commands": voice_commands,
                "emotion_changes": emotion_changes,
            },
            "final_state": {
                "behavior": final_behavior,
                "emotion": final_emotion,
                "energy_level": final_energy_level,
                "scan_data": dict(final_scan_data),
            },
        }
        return report

    def dump(self) -> List[Dict[str, Any]]:
        return list(self.memory)
