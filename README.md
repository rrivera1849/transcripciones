# transcripciones

Spanish courtroom transcription with speaker labels. Web app (phase 2) plus a
Modal GPU backend running WhisperX + pyannote. See `PLAN.md` for the design
and `docs/SETUP.md` for the accounts you need.

## Quick start (phase 1: transcription only)

```bash
uv sync --extra local --group dev
uv run pytest

# GPU on Modal (needs Modal + HF accounts, see docs/SETUP.md §1–2)
modal deploy modal_app.py
modal run modal_app.py --file samples/hearing.m4a --out out/

# Or, after deploying, via the CLI
uv run python -m transcribe samples/hearing.m4a --modal --out out/

# CPU-only dev path, small model, no speaker labels, first 2 minutes
uv run python -m transcribe samples/hearing.m4a --local --slice 0:120
```

Outputs land in `out/`: `.json` (raw segments + words), `.txt`, `.srt`, and
`.docx` with one paragraph per speaker turn.

## Layout

```
modal_app.py        Modal app: image with baked weights, Volume `audio-in`, Transcriber class, daily sweep
transcribe/         shared package (also shipped into the Modal image)
  __init__.py       Transcript / Segment / Word dataclasses
  prompt.py         Puerto Rican courtroom vocabulary for Whisper, role suggestions
  audio.py          ffmpeg probe / normalise / slice
  whisperx_pipeline.py  transcribe → align → diarize (runs on the GPU)
  local_cpu.py      faster-whisper on CPU for development
  turns.py          segments → speaker turns; rename / merge speakers
  export.py         txt / srt / docx writers
  modal_client.py   upload to Volume, spawn, wait (used by the CLI and, later, the worker)
tests/              unit tests on a fixture transcript
samples/            local audio, git-ignored
```
