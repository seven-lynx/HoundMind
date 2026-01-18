from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


def apply_servo_offsets(dog, offsets: Dict[str, float]) -> None:
    """Apply stored servo offsets to a PiDog `dog` instance.

    Offsets is a mapping of servo name -> degrees offset. The function will
    try to set servo zero positions if the `dog` API supports it. This is a
    lightweight hook used by a calibration routine.
    """
    if dog is None:
        logger.debug("No dog instance available to apply servo offsets")
        return
    for servo, offset in (offsets or {}).items():
        try:
            if hasattr(dog, "set_servo_zero"):
                dog.set_servo_zero(servo, float(offset))
                logger.info("Applied servo zero for %s: %s", servo, offset)
            elif hasattr(dog, "servos") and servo in getattr(dog, "servos"):
                # Some hardware APIs allow direct property set.
                getattr(dog, "servos")[servo].zero_offset = float(offset)
                logger.info("Set servo property zero for %s: %s", servo, offset)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to apply offset for %s: %s", servo, exc)


def collect_servo_defaults(dog) -> Dict[str, float]:
    """Read current servo zero offsets from the hardware API (if available).

    Returns a dict of servo->offset for persisting into config.
    """
    result: Dict[str, float] = {}
    if dog is None:
        return result
    try:
        if hasattr(dog, "get_servo_zero"):
            for name in getattr(dog, "servo_names", []) or []:
                try:
                    result[name] = float(dog.get_servo_zero(name))
                except Exception:
                    continue
        elif hasattr(dog, "servos"):
            for name, s in getattr(dog, "servos").items():
                try:
                    result[name] = float(getattr(s, "zero_offset", 0.0))
                except Exception:
                    continue
    except Exception:  # noqa: BLE001
        logger.debug("collect_servo_defaults failed", exc_info=True)
    return result
