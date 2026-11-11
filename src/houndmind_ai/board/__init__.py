"""Board identity: which Raspberry Pi this is, and whether it is one we ship for."""

from houndmind_ai.board.detect import (
    MODEL_PATH,
    SUPPORTED_KINDS,
    BoardInfo,
    classify_model,
    detect,
)

__all__ = ["MODEL_PATH", "SUPPORTED_KINDS", "BoardInfo", "classify_model", "detect"]