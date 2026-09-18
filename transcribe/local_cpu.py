"""CPU-only dev path: faster-whisper with a small model, no diarization.

Used to iterate on turn grouping and exporters with real audio when no GPU
or Modal credentials are at hand. Output quality is NOT representative.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import Segment, Transcript, Word
from .prompt import INITIAL_PROMPT, LANGUAGE


def transcribe_file(wav_path: str | Path, model_size: str = "small") -> Transcript:
    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs_iter, info = model.transcribe(
        str(wav_path),
        language=LANGUAGE,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=INITIAL_PROMPT,
        word_timestamps=True,
    )
    segments = [
        Segment(
            start=s.start,
            end=s.end,
            text=s.text.strip(),
            speaker=None,
            words=[Word(w.word, w.start, w.end, w.probability) for w in (s.words or [])],
        )
        for s in segs_iter
    ]
    return Transcript(
        segments=segments,
        language=LANGUAGE,
        duration=float(info.duration),
        model=f"faster-whisper/{model_size}",
        timing={"total_s": round(time.time() - t0, 1)},
    )
