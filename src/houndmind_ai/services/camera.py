"""One MJPEG producer, many viewers (M-04).

The legacy `vision_pi4` endpoint spawned a *thread* per client, each with its own encode loop
and no frame cap, so four browsers on one phone-shaped Pi was enough to starve the decision
loop. This module inverts that: the encoder owns the frames, the clients read the latest one,
and a client that falls behind misses frames rather than building a backlog.

Frames arrive on the context as bytes plus a monotonic timestamp, published by whichever vision
module is enabled. When nothing is publishing — the normal state of a shipped install, where
vision ships off — the routes answer 503 with a detail a human can act on.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiohttp import web

logger = logging.getLogger(__name__)

__all__ = ["CameraService", "FRAME_KEY", "FRAME_TS_KEY"]

# Where a vision module publishes. Names are part of the contract between `optional/` and the
# control plane, so they live here rather than being spelled out twice.
#
# The producer encodes: it publishes the JPEG bytes, not the raw array, because the raw array
# is also what `face_recognition`, `semantic_labeler` and `slam_pi4` read and re-encoding it
# for every viewer would be the legacy port-8090 mistake in reverse.
FRAME_KEY = "vision_frame_jpeg"
FRAME_TS_KEY = "vision_frame_ts"

_BOUNDARY = "houndmindframe"
_UNSUPPORTED = "no camera frames are being published; enable a vision module"


class CameraService:
    """Reads the newest frame from the context and serves it to every client."""

    def __init__(self, context, max_fps: float = 15.0) -> None:
        self._context = context
        # The cap is per client, because each client has its own socket; the frame itself is
        # never re-encoded, so the cost is the write, not the JPEG.
        self.max_fps = max(1.0, min(float(max_fps), 30.0))
        self._last_frame_ts: float | None = None

    def latest(self) -> tuple[bytes | None, float | None]:
        data = self._context.get(FRAME_KEY)
        ts = self._context.get(FRAME_TS_KEY)
        if not isinstance(data, (bytes, bytearray)) or not data:
            return None, None
        return bytes(data), ts if isinstance(ts, (int, float)) else None

    async def snapshot(self, request: web.Request) -> web.Response:
        frame, _ = self.latest()
        if frame is None:
            return web.json_response(
                {"error": "unavailable", "detail": _UNSUPPORTED}, status=503
            )
        return web.Response(body=frame, content_type="image/jpeg")

    async def stream(self, request: web.Request) -> web.StreamResponse:
        frame, _ = self.latest()
        if frame is None:
            return web.json_response(
                {"error": "unavailable", "detail": _UNSUPPORTED}, status=503
            )
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )
        await response.prepare(request)
        interval = 1.0 / self.max_fps
        last_ts = self._last_frame_ts
        try:
            while True:
                frame, ts = self.latest()
                # `ts` identity is what prevents serving the same JPEG sixty times a second
                # when the producer itself runs at two.
                if frame is not None and (ts is None or ts != last_ts):
                    header = (
                        f"--{_BOUNDARY}\r\n"
                        "Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(frame)}\r\n\r\n"
                    ).encode("ascii")
                    await response.write(header + frame + b"\r\n")
                    last_ts = ts
                await asyncio.sleep(interval)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            with contextlib.suppress(Exception):
                await response.write_eof()
        return response