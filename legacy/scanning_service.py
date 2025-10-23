import time
import types
import pytest

from packmind.core.context import AIContext
from packmind.services.scanning_service import ScanningService


class FakeUltrasonic:
    def __init__(self, sequence):
        self._seq = list(sequence)
        self._i = 0

    def read_distance(self):
        if not self._seq:
            return -1
        val = self._seq[self._i % len(self._seq)]
        self._i += 1
        return val


class FakeDog:
    def __init__(self, distances=(100, 100, 100)):
        # Provide repeating sequences for forward/right/left phases
        self._distance_sequences = {
            "forward": [distances[0], distances[0], distances[0]],
            "right": [distances[1], distances[1], distances[1]],
            "left": [distances[2], distances[2], distances[2]],
        }
        self._phase = "forward"
        self.ultrasonic = FakeUltrasonic(self._distance_sequences[self._phase])
        self.moves = []

    def head_move(self, poses, speed=90):
        yaw = poses[0][0]
        # Track requested yaw
        self.moves.append((yaw, speed))
        # Update sampling phase based on yaw
        if yaw == 0:
            self._phase = "forward"
        elif yaw < 0:
            self._phase = "right"
        elif yaw > 0:
            self._phase = "left"
        self.ultrasonic = FakeUltrasonic(self._distance_sequences[self._phase])


@pytest.fixture
def ctx():
    c = AIContext()
    c.dog = FakeDog((120, 80, 200))
    return c


def three_way_scan_returns_median_and_centers_head(ctx, monkeypatch):
    svc = ScanningService(ctx, head_scan_speed=50, scan_samples=3)
    res = svc.scan_three_way(left_deg=50, right_deg=50, settle_s=0.0, samples=3)
    assert res == {"forward": 120.0, "right": 80.0, "left": 200.0}
    # Head should have been centered at end (last move yaw == 0)
    assert ctx.dog.moves[-1][0] == 0


def three_way_scan_raises_on_missing_readings():
    c = AIContext()
    # Ultrasonic always invalid
    class BadDog(FakeDog):
        def __init__(self):
            super().__init__((-1, -1, -1))
    c.dog = BadDog()
    svc = ScanningService(c)
    with pytest.raises(RuntimeError):
        svc.scan_three_way(settle_s=0.0, samples=1)
