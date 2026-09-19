"""The GPU pipeline: WhisperX transcribe -> align -> diarize.

Only imported inside the Modal container (whisperx, torch and pyannote are
not installed on the app host). Models are loaded once per container and
cached in module globals so warm calls skip the load.
"""

from __future__ import annotations

import gc
import logging
import os
import time
from pathlib import Path

from . import Segment, Transcript, Word
from .prompt import LANGUAGE, build_prompt

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
DIARIZE_MODEL = "pyannote/speaker-diarization-community-1"

log = logging.getLogger("whisperx_pipeline")

_asr = None
_align = None  # (model, metadata)
_diarize = None

DEFAULT_BATCH_SIZE = 8
MIN_BATCH_SIZE = 2


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _release_gpu() -> None:
    """Drop cached CUDA blocks so per-job intermediates don't accumulate across jobs."""
    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _gpu_mem() -> str:
    import torch

    if not torch.cuda.is_available():
        return "cpu"
    used = torch.cuda.memory_allocated() / 2**30
    reserved = torch.cuda.memory_reserved() / 2**30
    return f"gpu {used:.1f} GiB used / {reserved:.1f} GiB reserved"


def _set_prompt(vocabulary: list[str] | str | None) -> None:
    """Swap the initial prompt in place; never reload the model for a vocabulary change."""
    from dataclasses import replace

    prompt = build_prompt(vocabulary)
    if getattr(_asr.options, "initial_prompt", None) != prompt:
        _asr.options = replace(_asr.options, initial_prompt=prompt)


def load_models(
    hf_token: str | None = None, diarize: bool = True, vocabulary: list[str] | str | None = None
) -> None:
    """Load ASR, alignment and (optionally) diarization models (idempotent)."""
    global _asr, _align, _diarize
    import whisperx

    device = _device()
    compute = "float16" if device == "cuda" else "int8"
    token = hf_token or os.environ.get("HF_TOKEN")
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
    _set_prompt(vocabulary)
    if _align is None:
        _align = whisperx.load_align_model(language_code=LANGUAGE, device=device)
    if diarize and _diarize is None:
        from whisperx.diarize import DiarizationPipeline

        _diarize = DiarizationPipeline(model_name=DIARIZE_MODEL, token=token, device=device)


def _is_oom(e: Exception) -> bool:
    return "out of memory" in str(e).lower()


def _transcribe_with_fallback(audio, batch_size: int) -> dict:
    """Run ASR; on CUDA OOM free the cache and retry with a smaller batch."""
    bs = max(batch_size, MIN_BATCH_SIZE)
    while True:
        try:
            return _asr.transcribe(audio, batch_size=bs, language=LANGUAGE)
        except RuntimeError as e:
            if not _is_oom(e) or bs <= MIN_BATCH_SIZE:
                raise
            log.warning("CUDA OOM at batch_size=%d; retrying with %d", bs, bs // 2)
            bs //= 2
            _release_gpu()


def transcribe_file(
    wav_path: str | Path,
    *,
    diarize: bool = True,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    vocabulary: list[str] | str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Transcript:
    """Run the full pipeline on a 16 kHz mono WAV and return a Transcript."""
    import whisperx

    load_models(diarize=diarize, vocabulary=vocabulary)
    device = _device()
    timing: dict[str, float] = {}
    _release_gpu()
    log.info("start: %s", _gpu_mem())

    t0 = time.time()
    audio = whisperx.load_audio(str(wav_path))
    duration = float(len(audio)) / 16000.0

    result = _transcribe_with_fallback(audio, batch_size)
    timing["transcribe_s"] = round(time.time() - t0, 1)
    _release_gpu()

    t1 = time.time()
    model_a, metadata = _align
    result = whisperx.align(
        result["segments"], model_a, metadata, audio, device, return_char_alignments=False
    )
    timing["align_s"] = round(time.time() - t1, 1)
    _release_gpu()

    if diarize:
        t2 = time.time()
        kwargs = {}
        if min_speakers:
            kwargs["min_speakers"] = min_speakers
        if max_speakers:
            kwargs["max_speakers"] = max_speakers
        diar = _diarize(audio, **kwargs)
        result = whisperx.assign_word_speakers(diar, result)
        del diar
        timing["diarize_s"] = round(time.time() - t2, 1)
        _release_gpu()

    timing["total_s"] = round(time.time() - t0, 1)
    log.info("done: %s", _gpu_mem())

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
