"""Modal app: GPU transcription with WhisperX + pyannote.

NOT YET RUN: written without Modal/Hugging Face access; first `modal deploy`
may need small fixes (pins, API names). See docs/SETUP.md §6.

Deploy once:   modal deploy modal_app.py
Try a file:    modal run modal_app.py --file samples/x.m4a --out out/
Sweep:         runs daily, deletes inputs older than 24 h from the Volume.

Secrets: a Modal secret named `huggingface` with key HF_TOKEN (needed to
download the gated pyannote models at image build time and at runtime).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import modal

APP_NAME = "transcripciones"
VOLUME_NAME = "audio-in"
AUDIO_MOUNT = "/audio"
MODEL_DIR = "/models"
WHISPER_MODEL = "large-v3"
GPU = os.environ.get("TRANSCRIBE_GPU", "A10G")
SIX_HOURS = 6 * 60 * 60

hf_secret = modal.Secret.from_name("huggingface")
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _download_models() -> None:
    """Bake all weights into the image so cold starts don't download 4 GB."""
    import whisperx
    from faster_whisper import download_model

    os.environ.setdefault("HF_HOME", MODEL_DIR)
    download_model(WHISPER_MODEL)  # lands in HF_HOME, where whisperx looks at runtime
    whisperx.load_align_model(language_code="es", device="cpu")
    from whisperx.diarize import DiarizationPipeline

    DiarizationPipeline(use_auth_token=os.environ["HF_TOKEN"], device="cpu")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git")
    .pip_install(
        "whisperx==3.4.2",
        "python-docx>=1.1",
    )
    .env({"HF_HOME": MODEL_DIR, "TOKENIZERS_PARALLELISM": "false"})
    .run_function(_download_models, secrets=[hf_secret])
    # Ship the shared package with the image so it stays in sync with the host.
    .add_local_python_source("transcribe")
)

app = modal.App(APP_NAME, image=image)


@app.cls(
    gpu=GPU,
    timeout=SIX_HOURS,
    volumes={AUDIO_MOUNT: volume},
    secrets=[hf_secret],
    scaledown_window=120,  # keep the GPU warm 2 min for back-to-back files
)
class Transcriber:
    @modal.enter()
    def load(self):
        os.environ["WHISPER_MODEL"] = WHISPER_MODEL
        from transcribe.whisperx_pipeline import load_models

        t0 = time.time()
        load_models()
        print(f"models loaded in {time.time() - t0:.1f}s")

    @modal.method()
    def run(self, job_id: str, remote_path: str, options: dict | None = None) -> dict:
        from transcribe.audio import normalize, probe
        from transcribe.whisperx_pipeline import transcribe_file

        options = options or {}
        volume.reload()
        src = Path(AUDIO_MOUNT) / remote_path.lstrip("/")
        if not src.exists():
            raise FileNotFoundError(f"{remote_path} not in volume {VOLUME_NAME}")

        info = probe(src)
        print(f"[{job_id}] {src.name}: {info}")
        wav = Path("/tmp") / f"{job_id}.wav"
        normalize(src, wav)

        transcript = transcribe_file(
            wav,
            diarize=options.get("diarize", True),
            min_speakers=options.get("min_speakers"),
            max_speakers=options.get("max_speakers"),
        )
        print(f"[{job_id}] done: {transcript.timing} speakers={transcript.speakers()}")

        # Input is no longer needed anywhere on Modal.
        try:
            src.unlink()
            src.parent.rmdir()
            volume.commit()
        except OSError as e:
            print(f"[{job_id}] cleanup warning: {e}")
        wav.unlink(missing_ok=True)
        return transcript.to_dict()


@app.function(schedule=modal.Period(days=1), volumes={AUDIO_MOUNT: volume})
def sweep_stale_inputs(max_age_hours: int = 24) -> int:
    """Delete inputs left behind by crashed runs."""
    import shutil

    volume.reload()
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in Path(AUDIO_MOUNT).iterdir():
        if entry.is_dir() and entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    if removed:
        volume.commit()
    print(f"swept {removed} stale job dir(s)")
    return removed


@app.local_entrypoint()
def main(file: str, out: str = "out", min_speakers: int = 0, max_speakers: int = 0):
    """Transcribe one local file end-to-end and write json/txt/srt/docx."""
    import uuid

    from transcribe import Transcript
    from transcribe.export import write_all

    src = Path(file)
    job_id = uuid.uuid4().hex
    remote = f"/{job_id}/input{src.suffix}"
    with volume.batch_upload(force=True) as batch:
        batch.put_file(str(src), remote)
    print(f"uploaded {src.name} -> {VOLUME_NAME}:{remote}")

    opts = {}
    if min_speakers:
        opts["min_speakers"] = min_speakers
    if max_speakers:
        opts["max_speakers"] = max_speakers
    result = Transcriber().run.remote(job_id, remote, opts)
    transcript = Transcript.from_dict(result)
    paths = write_all(transcript, out, src.stem, title=src.stem)
    print(f"speakers: {transcript.speakers()}  timing: {transcript.timing}")
    for k, p in paths.items():
        print(f"  {k}: {p}")
