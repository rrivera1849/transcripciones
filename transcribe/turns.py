"""Turn segments into readable speaker turns, and speaker rename / merge."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import Segment, Transcript
from .prompt import default_speaker_name

# Start a new paragraph for the same speaker after this much silence.
PARAGRAPH_GAP_S = 4.0
# Drop segments shorter than this with no words (Whisper hallucinates on noise).
MIN_SEGMENT_S = 0.3

_WS = re.compile(r"\s+")


@dataclass
class Turn:
    speaker: str | None  # raw id, e.g. SPEAKER_00, or None if undiarised
    start: float
    end: float
    text: str


def clean_text(text: str) -> str:
    return _WS.sub(" ", text).strip()


def group_turns(segments: list[Segment]) -> list[Turn]:
    """Merge consecutive same-speaker segments into turns."""
    turns: list[Turn] = []
    for seg in segments:
        text = clean_text(seg.text)
        if not text:
            continue
        if (seg.end - seg.start) < MIN_SEGMENT_S and not seg.words:
            continue
        if (
            turns
            and turns[-1].speaker == seg.speaker
            and seg.start - turns[-1].end <= PARAGRAPH_GAP_S
        ):
            last = turns[-1]
            last.text = f"{last.text} {text}"
            last.end = max(last.end, seg.end)
        else:
            turns.append(Turn(seg.speaker, seg.start, seg.end, text))
    return turns


def speaker_names(transcript: Transcript, overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Map raw speaker ids to display names, applying user overrides."""
    overrides = overrides or {}
    names: dict[str, str] = {}
    for i, sid in enumerate(transcript.speakers()):
        names[sid] = overrides.get(sid) or default_speaker_name(i)
    return names


def rename_speaker(overrides: dict[str, str], speaker_id: str, new_name: str) -> dict[str, str]:
    out = dict(overrides)
    out[speaker_id] = new_name.strip()
    return out


def merge_speakers(transcript: Transcript, keep: str, absorb: str) -> Transcript:
    """Relabel every segment/word of `absorb` as `keep` (the model split one voice)."""
    for seg in transcript.segments:
        if seg.speaker == absorb:
            seg.speaker = keep
        for w in seg.words:
            if w.speaker == absorb:
                w.speaker = keep
    return transcript


def fmt_ts(seconds: float, with_ms: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if with_ms:
        ms = round((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"
