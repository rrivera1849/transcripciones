"""App-host side of the Modal hand-off: upload to the Volume, spawn, wait.

Requires `modal deploy modal_app.py` to have been run once, and Modal
credentials in the environment (MODAL_TOKEN_ID / MODAL_TOKEN_SECRET) or in
~/.modal.toml.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from . import Transcript

APP_NAME = "transcripciones"
VOLUME_NAME = "audio-in"
CLASS_NAME = "Transcriber"


def upload_to_volume(local_path: str | Path, job_id: str) -> str:
    """Stream a file into the shared Volume; return its remote path."""
    import modal

    vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
    remote = f"/{job_id}/input{Path(local_path).suffix}"
    with vol.batch_upload(force=True) as batch:
        batch.put_file(str(local_path), remote)
    return remote


def spawn(job_id: str, remote_path: str, **options):
    """Start the GPU job without waiting; returns a FunctionCall handle."""
    import modal

    transcriber = modal.Cls.from_name(APP_NAME, CLASS_NAME)()
    return transcriber.run.spawn(job_id, remote_path, options)


def transcribe_on_modal(local_path: str | Path, **options) -> Transcript:
    """Blocking convenience wrapper used by the CLI."""
    job_id = uuid.uuid4().hex
    remote = upload_to_volume(local_path, job_id)
    call = spawn(job_id, remote, **{k: v for k, v in options.items() if v is not None})
    result = call.get()
    return Transcript.from_dict(result)
