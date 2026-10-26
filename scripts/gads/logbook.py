"""Run log: every assumption, warning, and excluded row is recorded, never silent."""
from __future__ import annotations


class StopAnalysis(Exception):
    """Raised when continuing would produce a misleading result."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RunLog:
    def __init__(self) -> None:
        self.assumptions: list[str] = []
        self.warnings: list[str] = []
        self.excluded: list[dict] = []

    def assume(self, msg: str) -> None:
        self.assumptions.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def exclude(self, index: int, reason: str, raw: dict) -> None:
        self.excluded.append({"index": index, "reason": reason, "raw": raw})

    def to_dict(self) -> dict:
        return {
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
            "excluded": list(self.excluded),
            "errors": [],  # kept for output compatibility; problems stop the run instead (StopAnalysis)
        }
