"""Shared data model for transcripts.

Everything that runs both inside the Modal GPU function and on the app host
lives in this package. Keep it free of heavy imports (torch, whisperx); those
are imported lazily inside the modules that need them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Word:
    word: str
    start: float | None = None
    end: float | None = None
    score: float | None = None
    speaker: str | None = None


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    segments: list[Segment]
    language: str = "es"
    duration: float | None = None
    model: str | None = None
    timing: dict[str, float] = field(default_factory=dict)

    # --- speakers -------------------------------------------------------
    def speakers(self) -> list[str]:
        """Raw speaker ids in order of first appearance."""
        seen: list[str] = []
        for s in self.segments:
            if s.speaker and s.speaker not in seen:
                seen.append(s.speaker)
        return seen

    # --- serialisation --------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Transcript:
        segs = [
            Segment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=str(s.get("text", "")).strip(),
                speaker=s.get("speaker"),
                words=[Word(**w) for w in s.get("words", [])],
            )
            for s in d.get("segments", [])
        ]
        return cls(
            segments=segs,
            language=d.get("language", "es"),
            duration=d.get("duration"),
            model=d.get("model"),
            timing=d.get("timing", {}),
        )
