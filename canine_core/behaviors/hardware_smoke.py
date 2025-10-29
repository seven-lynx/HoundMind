from __future__ import annotations
import asyncio
from typing import Optional, Tuple

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class HardwareSmokeBehavior(Behavior):
    name = "hardware_smoke"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._ok: bool = True

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        log = ctx.logger
        log.info("[smoke] Starting hardware smoke checks…")
        try:
            ctx.emotions.set_color((0, 64, 255))
        except Exception:
            pass

        # --- Distance / scan (cm) ---
        try:
            rng = int(getattr(ctx.config, "HEAD_SCAN_RANGE", 20))
            spd = int(getattr(ctx.config, "HEAD_SCAN_SPEED", 60))
            fwd, left, right = ctx.sensors.read_distances(head_range=min(30, rng), head_speed=min(80, spd))
            log.info(f"[smoke] distance_cm center={fwd:.0f} left={left:.0f} right={right:.0f}")
        except Exception as e:
            self._ok = False
            log.error(f"[smoke] distance read failed: {e}")

        # --- IMU ---
        if ctx.imu is not None:
            try:
                acc = ctx.imu.read_accel()
                gyro = ctx.imu.read_gyro()
                if acc is not None:
                    ax, ay, az = acc
                    log.info(f"[smoke] imu.acc=({ax:.1f},{ay:.1f},{az:.1f})")
                else:
                    log.warning("[smoke] imu.acc unavailable")
                if gyro is not None:
                    gx, gy, gz = gyro
                    log.info(f"[smoke] imu.gyro=({gx:.1f},{gy:.1f},{gz:.1f})")
                else:
                    log.warning("[smoke] imu.gyro unavailable")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] imu read failed: {e}")

        # --- Battery ---
        if ctx.battery is not None:
            try:
                pct = ctx.battery.read_percentage()
                if pct is None:
                    log.warning("[smoke] battery percentage unavailable")
                else:
                    log.info(f"[smoke] battery={pct:.0f}%")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] battery read failed: {e}")

        # --- Ears / Touch ---
        if ctx.sensors_facade is not None:
            try:
                heard = ctx.sensors_facade.sound_detected()
                if heard is True:
                    deg = ctx.sensors_facade.sound_direction_deg()
                    if deg is not None:
                        log.info(f"[smoke] ears: detected direction={deg}°")
                    else:
                        log.info("[smoke] ears: detected (no direction)")
                elif heard is False:
                    log.info("[smoke] ears: no sound detected")
                else:
                    log.warning("[smoke] ears unavailable")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] ears read failed: {e}")
            try:
                touch = ctx.sensors_facade.touch_read()
                if touch is None:
                    log.warning("[smoke] touch unavailable")
                else:
                    log.info(f"[smoke] touch={touch}")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] touch read failed: {e}")

        # --- Optional minimal motion ---
        allow_move = bool(getattr(ctx.config, "SMOKE_ALLOW_MOVE", False))
        speed = int(getattr(ctx.config, "SMOKE_SPEED", 60))
        if allow_move and getattr(ctx.hardware, "dog", None) is not None:
            log.info("[smoke] running limited motion checks (config SMOKE_ALLOW_MOVE=True)")
            try:
                ctx.motion.act("stand", speed=speed)
                ctx.motion.wait()
                log.info("[smoke] stand OK")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] stand failed: {e}")
            try:
                ctx.motion.act("forward", step_count=1, speed=speed)
                ctx.motion.wait()
                log.info("[smoke] forward(1) OK")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] forward failed: {e}")
            try:
                # Use small IMU-assisted turn when available, fallback to step-based internally
                try:
                    dps = float(getattr(ctx.config, "TURN_DEGREES_PER_STEP", 15.0))
                except Exception:
                    dps = 15.0
                ctx.motion.turn_by_angle(dps, max(50, speed), ctx)
                log.info("[smoke] turn_left(~1 step) OK")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] turn_left failed: {e}")
            try:
                ctx.motion.act("lie", speed=max(40, speed - 10))
                ctx.motion.wait()
                log.info("[smoke] lie OK")
            except Exception as e:
                self._ok = False
                log.error(f"[smoke] lie failed: {e}")
        else:
            log.info("[smoke] movement tests skipped (SMOKE_ALLOW_MOVE=False or no hardware)")

        # LED result
        try:
            if self._ok:
                ctx.emotions.set_color((0, 128, 0))
            else:
                ctx.emotions.set_color((200, 0, 0))
        except Exception:
            pass
        log.info(f"[smoke] Checks complete. Result={'OK' if self._ok else 'FAIL'}")

    async def on_event(self, event: Event) -> None:
        # No event handling; smoke checks run once in start()
        return

    async def stop(self) -> None:
        # Nothing to clean up
        return


BEHAVIOR_CLASS = HardwareSmokeBehavior
