"""
Vision Inference Scheduler

Runs a vision model's inference in a separate thread for Pi 4 hardware: frames in,
results out, latest-frame-wins with a bounded queue.

Nothing is started unless a module supplies an `inference_fn`. `optional/vision_pi4.py` used to
ship a placeholder here — a thread whose whole job was `sleep(0.05)` returning
`{"result": "ok"}` — which made an idle camera look like it was inferring something (M-03).
Configurable via `settings.vision_pi4` (Pi 4 only).
"""

import queue
import threading
from collections.abc import Callable
from typing import Any


class VisionInferenceScheduler:
    """
    Schedules vision inference jobs in a background thread or process.
    Accepts frames, runs inference, and returns results via callback or queue.
    """
    def __init__(self, inference_fn: Callable[[Any], Any], result_callback: Callable[[Any], None] | None = None, max_queue_size: int = 4):
        self.inference_fn = inference_fn
        self.result_callback = result_callback
        self.frame_queue: queue.Queue[Any] = queue.Queue(maxsize=max_queue_size)
        self.result_queue: queue.Queue[Any] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._stop_event.clear()
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=2)

    def submit_frame(self, frame: Any):
        try:
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            # Drop frame if queue is full (backpressure)
            pass

    def get_result(self, timeout: float = 0.1) -> Any | None:
        try:
            return self.result_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self):
        while not self._stop_event.is_set():
            try:
                frame = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            result = self.inference_fn(frame)
            if self.result_callback:
                self.result_callback(result)
            else:
                self.result_queue.put(result)
