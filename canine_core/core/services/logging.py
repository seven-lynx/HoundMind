from __future__ import annotations
from dataclasses import dataclass

@dataclass
class LoggingService:
    prefix: str = "CanineCore"

    def info(self, msg: str) -> None:
        print(f"[INFO] {self.prefix}: {msg}")

    def warning(self, msg: str) -> None:
        print(f"[WARN] {self.prefix}: {msg}")

    def error(self, msg: str) -> None:
        print(f"[ERROR] {self.prefix}: {msg}")
