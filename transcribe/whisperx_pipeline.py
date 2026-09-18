"""The GPU pipeline: WhisperX transcribe -> align -> diarize.

Only imported inside the Modal container (whisperx, torch and pyannote are
not installed on the app host). Models are loaded once per container and
cached in module globals so warm calls skip the load.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import Segment, Transcript, Word
from .prompt import LANGUAGE, build_prompt

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
DIARIZE_MODEL = "pyannote/speaker-diarization-community-1"

_asr = None
_align = None  # (model, metadata)
_diarize = None


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def load_models(
    hf_token: str | None = None, diarize: bool = True, vocabulary: list[str] | str | None = None
) -> None:
    """Load ASR, alignment and (optionally) diarization models (idempotent)."""
    global _asr, _align, _diarize
    import whisperx

    device = _device()
    compute = "float16" if device == "cuda" else "int8"
    token = hf_token or os.environ.get("HF_TOKEN")
    if _asr is not None and vocabulary and getattr(_asr, "_vocabulary", None) != vocabulary:
        _asr = None  # prompt changed: reload the (cheap) ASR pipeline wrapper
    if _asr is None:
        _asr = whisperx.load_model(
            WHISPER_MODEL,
            device,
            compute_type=compute,
            language=LANGUAGE,
            use_auth_token=token,  # pyannote VAD model is gated
            asr_options={
                "beam_size": 5,
                "initial_prompt": build_prompt(vocabulary),
                # Whisper hallucinates numerals/repeats on silence; VAD chunks already
                # remove most silence, these keep the rest tidy.
                "suppress_numerals": False,
                "condition_on_previous_text": False,
            },
        )
        _asr._vocabulary = vocabulary
    if _align is None:
        _align = whisperx.load_align_model(language_code=LANGUAGE, device=device)
    if diarize and _diarize is None:
        from whisperx.diarize import DiarizationPipeline

        _diarize = DiarizationPipeline(model_name=DIARIZE_MODEL, token=token, device=device)


def transcribe_file(
    wav_path: str | Path,
    *,
    diarize: bool = True,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    vocabulary: list[str] | str | None = None,
    batch_size: int = 16,
) -> Transcript:
    """Run the full pipeline on a 16 kHz mono WAV and return a Transcript."""
    import whisperx

    load_models(diarize=diarize, vocabulary=vocabulary)
    device = _device()
    timing: dict[str, float] = {}

    t0 = time.time()
    audio = whisperx.load_audio(str(wav_path))
    duration = float(len(audio)) / 16000.0

    result = _asr.transcribe(audio, batch_size=batch_size, language=LANGUAGE)
    timing["transcribe_s"] = round(time.time() - t0, 1)

    t1 = time.time()
    model_a, metadata = _align
    result = whisperx.align(
        result["segments"], model_a, metadata, audio, device, return_char_alignments=False
    )
    timing["align_s"] = round(time.time() - t1, 1)

    if diarize:
        t2 = time.time()
        kwargs = {}
        if min_speakers:
            kwargs["min_speakers"] = min_speakers
        if max_speakers:
            kwargs["max_speakers"] = max_speakers
        diar = _diarize(audio, **kwargs)
        result = whisperx.assign_word_speakers(diar, result)
        timing["diarize_s"] = round(time.time() - t2, 1)

    timing["total_s"] = round(time.time() - t0, 1)

    segments = [
        Segment(
            start=float(s["start"]),
            end=float(s["end"]),
            text=str(s.get("text", "")).strip(),
            speaker=s.get("speaker"),
            words=[
                Word(
                    word=w.get("word", ""),
                    start=w.get("start"),
                    end=w.get("end"),
                    score=w.get("score"),
                    speaker=w.get("speaker"),
                )
                for w in s.get("words", [])
            ],
        )
        for s in result["segments"]
    ]
    return Transcript(
        segments=segments,
        language=LANGUAGE,
        duration=duration,
        model=WHISPER_MODEL,
        timing=timing,
    )
