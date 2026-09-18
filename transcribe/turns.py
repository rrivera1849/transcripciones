"""Turn segments into readable speaker turns, and speaker rename / merge."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import Segment, Transcript
from .prompt import default_speaker_name

# Start a new paragraph for the same speaker after this much silence.
PARAGRAPH_GAP_S = 4.0
# Also break a long same-speaker turn at the next pause of at least this length.
MAX_TURN_S = 60.0
MIN_BREAK_GAP_S = 1.0
# Drop segments shorter than this with no words (Whisper hallucinates on noise).
MIN_SEGMENT_S = 0.3
# Whisper repetition loops: collapse N identical consecutive segments, and
# runs of one repeated token inside a segment ("no, no, no, no, ...").
MAX_REPEATED_SEGMENTS = 2
MAX_REPEATED_TOKENS = 3

_WS = re.compile(r"\s+")


@dataclass
class Turn:
    speaker: str | None  # raw id, e.g. SPEAKER_00, or None if undiarised
    start: float
    end: float
    text: str
    seg_from: int = 0  # index range into the *cleaned* segment list (inclusive)
    seg_to: int = 0


def clean_text(text: str) -> str:
    return _WS.sub(" ", text).strip()


_TOKEN_RUN = re.compile(
    r"(\b(\w+)\b[,.\s]*)(?:\2\b[,.\s]*){" + str(MAX_REPEATED_TOKENS) + ",}", re.IGNORECASE
)


def collapse_token_runs(text: str) -> str:
    """'No, no, no, no, no, no.' -> 'No, no, no.'"""

    def _shrink(m: re.Match) -> str:
        units = re.findall(r"\b\w+\b[,.\s]*", m.group(0))
        return "".join(units[:MAX_REPEATED_TOKENS])

    new = _TOKEN_RUN.sub(_shrink, text)
    if new == text:
        return text
    new = new.rstrip(", ")
    return new + "." if text.rstrip().endswith(".") and not new.endswith(".") else new


def clean_segments(segments: list[Segment]) -> list[Segment]:
    """Remove Whisper hallucination loops; keeps timing of the surviving segment."""
    out: list[Segment] = []
    for seg in segments:
        text = clean_text(seg.text)
        if not text:
            continue
        if (seg.end - seg.start) < MIN_SEGMENT_S and not seg.words:
            continue
        key = text.lower()
        run = [s for s in out[-MAX_REPEATED_SEGMENTS:] if clean_text(s.text).lower() == key]
        if len(run) == MAX_REPEATED_SEGMENTS and len(out) >= MAX_REPEATED_SEGMENTS:
            # third+ identical segment in a row: extend the previous one instead
            out[-1].end = max(out[-1].end, seg.end)
            continue
        out.append(
            Segment(seg.start, seg.end, collapse_token_runs(text), seg.speaker, list(seg.words))
        )
    return out


def group_turns(segments: list[Segment]) -> list[Turn]:
    """Merge consecutive same-speaker segments into readable turns."""
    turns: list[Turn] = []
    for i, seg in enumerate(clean_segments(segments)):
        text = seg.text
        gap = seg.start - turns[-1].end if turns else 0.0
        too_long = turns and (seg.end - turns[-1].start) > MAX_TURN_S and gap >= MIN_BREAK_GAP_S
        if (
            turns
            and turns[-1].speaker == seg.speaker
            and gap <= PARAGRAPH_GAP_S
            and not too_long
        ):
            last = turns[-1]
            last.text = f"{last.text} {text}"
            last.end = max(last.end, seg.end)
            last.seg_to = i
        else:
            turns.append(Turn(seg.speaker, seg.start, seg.end, text, i, i))
    return turns


def replace_turn_text(segments: list[Segment], turn: Turn, new_text: str) -> list[Segment]:
    """Collapse the turn's segments into one carrying the edited text."""
    segs = clean_segments(segments)
    first, last = segs[turn.seg_from], segs[turn.seg_to]
    merged = Segment(first.start, last.end, clean_text(new_text), first.speaker, [])
    return segs[: turn.seg_from] + [merged] + segs[turn.seg_to + 1 :]


def set_turn_speaker(segments: list[Segment], turn: Turn, speaker: str) -> list[Segment]:
    segs = clean_segments(segments)
    for s in segs[turn.seg_from : turn.seg_to + 1]:
        s.speaker = speaker
        for w in s.words:
            w.speaker = speaker
    return segs


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
