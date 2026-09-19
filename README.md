# transcripciones

Spanish courtroom transcription with speaker labels. Web app (phase 2) plus a
Modal GPU backend running WhisperX + pyannote. See `PLAN.md` for the design
and `docs/SETUP.md` for the accounts you need.

## Run the web app locally (phase 2)

```bash
uv sync --group dev
uv run python scripts/add_user.py mama            # prints a generated password
# forgot it later?  uv run python scripts/set_password.py mama   (users can also change it at /cuenta)
cp .env.example .env                              # set MODAL_TOKEN_ID/SECRET; TRANSCRIBER=modal
uv run modal deploy modal_app.py                  # REQUIRED once per code change: creates the
                                                  # persistent app the worker looks up by name
                                                  # (`modal run` alone is temporary and won't do)
uv run python -m app                              # web + worker; open http://127.0.0.1:8000
```

Set `TRANSCRIBER=local` (and optionally `LOCAL_MODEL=large-v3-turbo`) to
transcribe on the laptop's CPU without Modal; that path has no speaker labels
and is meant for development only.

Docker: `docker compose up -d --build` runs `web` and `worker` with `data/`
mounted. Phase 3 adds `cloudflared` and moves this to a VPS.

## Quick start (phase 1: transcription only)

```bash
uv sync --extra local --group dev
uv run pytest

# GPU on Modal (needs Modal + HF accounts, see docs/SETUP.md §1–2)
modal deploy modal_app.py
modal run modal_app.py --file samples/hearing.m4a --out out/

# Re-export txt/srt/docx from a saved result without re-running the GPU
uv run python -m transcribe --from-json out/hearing.json --out out/

# Or, after deploying, via the CLI
uv run python -m transcribe samples/hearing.m4a --modal --out out/

# CPU-only dev path, small model, no speaker labels, first 2 minutes
uv run python -m transcribe samples/hearing.m4a --local --slice 0:120
```

Outputs land in `out/`: `.json` (raw segments + words), `.txt`, `.srt`, and
`.docx` with one paragraph per speaker turn.

## Layout

```
app/
  main.py           FastAPI routes: login, chunked upload, job list, search, transcript page, exports, audio
  worker.py         queue -> Modal (or local CPU) -> transcripts; retention sweep; restart-safe
  db.py             SQLite schema (users, jobs, transcripts, FTS5 search index)
  auth.py           bcrypt, signed 90-day session cookie, login lockout, CSRF
  templates/        Spanish UI (Jinja2 + HTMX)
  static/           style.css, upload.js (chunked upload), transcript.js (player, edit, find), htmx
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
