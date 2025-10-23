from __future__ import annotations
from typing import Callable, Dict
from packmind.core.context import AIContext

class VoiceService:
    """
    Owns voice command registry and parsing. External layer can handle ASR input and
    forward recognized text here for intent matching.
    """

    def __init__(self) -> None:
        self._commands: Dict[str, Callable[[], None]] = {}
        self._wake_word: str = "pidog"

    def set_wake_word(self, word: str) -> None:
        self._wake_word = word

    def register(self, keyword: str, action: Callable[[], None]) -> None:
        self._commands[keyword] = action

    def process_text(self, text: str, context: AIContext) -> bool:
        text = text.lower().strip()
        if self._wake_word in text:
            command_text = text.replace(self._wake_word, "").strip()
        else:
            command_text = text
        for key, action in self._commands.items():
            if key in command_text:
                action()
                return True
        return False
