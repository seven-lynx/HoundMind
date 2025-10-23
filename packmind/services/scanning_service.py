from __future__ import annotations
import time
import threading
from typing import Callable, Dict, Optional, Sequence, List

from packmind.core.context import AIContext


class ScanningService:
    """
    Active ultrasonic/head scanning routines used by multiple consumers:
    - ObstacleService (avoidance decisions)
    - Navigation/Mapping (SLAM updates and triangulation)

    Provides synchronous scan calls and an optional background loop that
    performs scans at intervals and emits results via callback.
    """

    def __init__(
        self,
        context: AIContext,
        head_scan_speed: int = 90,
        scan_samples: int = 3,
    ) -> None:
        self._ctx = context
        self._head_speed = head_scan_speed
        self._samples = max(1, scan_samples)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._interval: float = 0.5
        self._mode: str = "three_way"
        self._on_scan: Optional[Callable[[Dict[str, float]], None]] = None
        # Sweep params
        self._sweep_left: int = 50
        self._sweep_right: int = 50
        self._sweep_step: int = 5
        self._sweep_dwell: float = 0.0  # if >0, pause at each step before sampling

    # --- Background loop management ---
    def start_continuous(self, mode: str = "three_way", interval: float = 0.5, on_scan: Optional[Callable[[Dict[str, float]], None]] = None) -> None:
        self._mode = mode
        self._interval = max(0.1, interval)
        self._on_scan = on_scan
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._mode == "three_way":
                    res = self.scan_three_way()
                elif self._mode == "sweep":
                    res = self._sweep_once()
                else:
                    # Default to three_way if unknown mode
                    res = self.scan_three_way()
                if self._on_scan:
                    self._on_scan(res)
            except Exception:
                pass
            time.sleep(self._interval)

    # --- Synchronous scans ---
    def scan_three_way(self, left_deg: int = 50, right_deg: int = 50, settle_s: float = 0.3, samples: Optional[int] = None) -> Dict[str, float]:
        """
        Scan forward and to both sides by configurable degrees.
        - left_deg/right_deg: degrees from center to scan (defaults 50° left/right)
        - settle_s: wait time after head stops before sampling
        - samples: number of ultrasonic samples; overrides default if provided
        Returns distances in cm with safe defaults on host PCs.
        """
        dog = self._ctx.dog
        if dog is None:
            raise RuntimeError("ScanningService requires a PiDog instance (context.dog is None)")

        result: Dict[str, float] = {}
        n = self._samples if samples is None else max(1, int(samples))

        try:
            # Center/forward
            self._head_move(0)
            if settle_s > 0:
                time.sleep(settle_s)
            distances = self._read_distance_samples(n)
            if not distances:
                raise RuntimeError("No valid distance readings for 'forward'")
            result["forward"] = self._median_or_default(distances, default=0.0)

            # Right (negative yaw)
            self._head_move(-int(right_deg))
            if settle_s > 0:
                time.sleep(settle_s)
            distances = self._read_distance_samples(n)
            if not distances:
                raise RuntimeError("No valid distance readings for 'right'")
            result["right"] = self._median_or_default(distances, default=0.0)

            # Left (positive yaw)
            self._head_move(int(left_deg))
            if settle_s > 0:
                time.sleep(settle_s)
            distances = self._read_distance_samples(n)
            if not distances:
                raise RuntimeError("No valid distance readings for 'left'")
            result["left"] = self._median_or_default(distances, default=0.0)
            return result
        finally:
            # Always return head to center
            try:
                self._head_move(0)
            except Exception:
                pass

    def sweep_scan(self, angles: Sequence[int]) -> Dict[int, float]:
        """Scan arbitrary yaw angles; returns a mapping angle->distance cm."""
        dog = self._ctx.dog
        if dog is None:
            raise RuntimeError("ScanningService requires a PiDog instance (context.dog is None)")
        result: Dict[int, float] = {}
        try:
            for yaw in angles:
                self._head_move(int(yaw))
                distances = self._read_distance_samples(self._samples)
                if not distances:
                    raise RuntimeError(f"No valid distance readings at yaw {yaw}")
                result[int(yaw)] = self._median_or_default(distances, default=0.0)
            return result
        finally:
            try:
                self._head_move(0)
            except Exception:
                pass

    def start_continuous_sweep(
        self,
        left_deg: int = 50,
        right_deg: int = 50,
        step_deg: int = 5,
        dwell_s: float = 0.0,
        interval: float = 0.1,
        on_scan: Optional[Callable[[Dict[str, float]], None]] = None,
    ) -> None:
        """
        Start a continuous sweep across [-right_deg, +left_deg] in increments.
        - If dwell_s > 0, the head pauses at each step before sampling (higher accuracy).
        - If dwell_s == 0, samples are taken as the head is moving (faster, noisier),
          which can benefit certain mapping pipelines that fuse many quick readings.
        """
        self._sweep_left = int(max(0, left_deg))
        self._sweep_right = int(max(0, right_deg))
        self._sweep_step = max(1, int(step_deg))
        self._sweep_dwell = max(0.0, float(dwell_s))
        self._mode = "sweep"
        self.start_continuous(mode="sweep", interval=max(0.05, interval), on_scan=on_scan)

    # --- Helpers ---
    def _head_move(self, yaw: int) -> None:
        dog = self._ctx.dog
        if dog is None:
            raise RuntimeError("ScanningService requires a PiDog instance (context.dog is None)")
        dog.head_move([[int(yaw), 0, 0]], speed=self._head_speed)
        # Minimal settle between move commands; callers add extra settle for sampling.
        time.sleep(0.05)

    def _read_distance_samples(self, n: int) -> list[float]:
        dog = self._ctx.dog
        if dog is None:
            raise RuntimeError("ScanningService requires a PiDog instance (context.dog is None)")
        out: list[float] = []
        for _ in range(max(1, n)):
            d = dog.ultrasonic.read_distance()
            if isinstance(d, (int, float)) and d > 0:
                out.append(float(d))
            time.sleep(0.1)
        return out

    def _sweep_once(self) -> Dict[str, float]:
        """
        Perform one sweep pass and return a dictionary with sampled angles as keys
        (degrees as strings like "-20" or "35") and distances in cm.
        """
        dog = self._ctx.dog
        if dog is None:
            raise RuntimeError("ScanningService requires a PiDog instance (context.dog is None)")
        samples: Dict[str, float] = {}
        try:
            for ang in self._sweep_angles():
                self._head_move(ang)
                if self._sweep_dwell > 0:
                    time.sleep(self._sweep_dwell)
                distances = self._read_distance_samples(1 if self._sweep_dwell == 0 else self._samples)
                if not distances:
                    raise RuntimeError(f"No valid distance readings at yaw {ang}")
                samples[str(ang)] = self._median_or_default(distances, default=0.0)
            return samples
        finally:
            # Optionally return to center to keep posture natural
            try:
                self._head_move(0)
            except Exception:
                pass

    def _sweep_angles(self) -> List[int]:
        """Generate sweep angle sequence from -right to +left by step size, inclusive."""
        start = -self._sweep_right
        end = self._sweep_left
        step = self._sweep_step
        angles: List[int] = []
        a = start
        while a <= end:
            angles.append(int(a))
            a += step
        if angles and angles[-1] != end:
            angles.append(int(end))
        return angles

    @staticmethod
    def _median_or_default(values: list[float], default: float) -> float:
        if not values:
            return default
        s = sorted(values)
        return s[len(s) // 2]
