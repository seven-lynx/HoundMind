"""
ScanningService: shared, hardware-safe head scanning utilities.

Features:
- Clamp head yaw to safe limits and move head
- Read distance (in centimeters) after settle time, with graceful fallback if hardware absent
- Scan a sequence of angles and return angle->distance map

All methods are cooperative (async) and avoid blocking the event loop.
"""
from __future__ import annotations
import asyncio
from typing import Dict, Iterable, Optional


class ScanningService:
    def __init__(self, hardware: object, logger: Optional[object] = None) -> None:
        self._hardware = hardware
        self._dog = getattr(hardware, "dog", None)
        self._logger = logger

    @staticmethod
    def _clamp_yaw(yaw_deg: int) -> int:
        # Conservative clamp; servos typically support ±90, we use ±80
        return max(-80, min(80, int(yaw_deg)))

    def _read_distance(self) -> float:
        dog = self._dog
        if dog is None:
            return 1000.0
        try:
            d = dog.read_distance()
            return float(d if d is not None else 1000.0)
        except Exception:
            return 1000.0

    async def move_and_read(self, yaw_deg: int, settle_s: float, move_speed: int) -> float:
        """Move head yaw then read distance. If move unsupported, just wait and read."""
        yaw_cmd = self._clamp_yaw(yaw_deg)
        dog = self._dog
        if dog is not None and hasattr(dog, "head_move"):
            try:
                dog.head_move([[yaw_cmd, 0, 0]], speed=int(move_speed))
                await asyncio.sleep(float(settle_s))
                return self._read_distance()
            except Exception as e:
                if self._logger:
                    try:
                        _warn = getattr(self._logger, "warning", None)
                        if callable(_warn):
                            _warn(f"ScanningService move failed: {e}")
                    except Exception:
                        pass
        # Fallback: brief wait then read
        await asyncio.sleep(max(0.0, float(settle_s) * 0.5))
        return self._read_distance()

    async def scan_sequence(
        self,
        angles: Iterable[int],
        settle_s: float,
        between_reads_s: float,
        move_speed: int,
        center_end: bool = True,
    ) -> Dict[int, float]:
        """Scan a list of yaw angles (deg). Returns {angle: distance_cm}.

        Angles are clamped per sample but keys are the requested angles.
        """
        out: Dict[int, float] = {}
        for yaw in list(angles):
            dist = await self.move_and_read(int(yaw), settle_s, move_speed)
            out[int(yaw)] = dist
            await asyncio.sleep(float(between_reads_s))
        if center_end:
            try:
                await self.move_and_read(0, max(0.05, float(settle_s) * 0.5), move_speed)
            except Exception:
                pass
        return out
