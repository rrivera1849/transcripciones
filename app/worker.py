"""Background worker: queued jobs -> transcriber -> transcripts table.

Backends:
  modal  (default) upload to the Modal Volume, spawn Transcriber.run, poll the call id
  local  CPU faster-whisper (no speaker labels); for development without Modal
  fake   returns a fixture transcript; used by tests

Survives restarts: a job left in `running` with a modal_call_id is re-attached
to its FunctionCall on boot instead of being re-submitted.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from transcribe import Transcript
from transcribe.audio import normalize

from . import config, db

log = logging.getLogger("worker")


class ModalBackend:
    def submit(self, job: dict) -> str:
        from transcribe.modal_client import spawn, upload_to_volume

        remote = upload_to_volume(job["audio_path"], job["id"])
        opts = {}
        if job.get("min_speakers"):
            opts["min_speakers"] = int(job["min_speakers"])
        if job.get("vocabulary"):
            opts["vocabulary"] = job["vocabulary"]
        call = spawn(job["id"], remote, **opts)
        return call.object_id

    def poll(self, call_id: str) -> dict | None:
        import modal

        call = modal.FunctionCall.from_id(call_id)
        try:
            return call.get(timeout=0)
        except TimeoutError:
            return None


class LocalBackend:
    """Blocking CPU transcription; `submit` does all the work and `poll` returns it."""

    def __init__(self):
        self._results: dict[str, dict] = {}

    def submit(self, job: dict) -> str:
        from transcribe.local_cpu import transcribe_file

        with tempfile.TemporaryDirectory() as td:
            wav = normalize(job["audio_path"], Path(td) / "input.wav")
            transcript = transcribe_file(wav, model_size=config.LOCAL_MODEL)
        self._results[job["id"]] = transcript.to_dict()
        return f"local:{job['id']}"

    def poll(self, call_id: str) -> dict | None:
        return self._results.pop(call_id.split(":", 1)[1], None)


class FakeBackend:
    def __init__(self, result: dict):
        self.result = result
        self.submitted: list[dict] = []

    def submit(self, job: dict) -> str:
        self.submitted.append(job)
        return f"fake:{job['id']}"

    def poll(self, call_id: str) -> dict | None:
        return dict(self.result)


def make_backend(name: str | None = None):
    name = name or config.TRANSCRIBER
    if name == "modal":
        return ModalBackend()
    if name == "local":
        return LocalBackend()
    raise ValueError(f"unknown TRANSCRIBER {name!r}")


class Worker:
    def __init__(self, backend, db_path: Path | None = None):
        self.backend = backend
        self.db_path = db_path
        self._last_modal_poll: dict[str, float] = {}

    # one pass over the queue; returns number of state changes (for tests)
    def tick(self) -> int:
        changes = 0
        with db.connect(self.db_path) as conn:
            for job in db.jobs_with_status(conn, "queued"):
                changes += self._submit(conn, dict(job))
            for job in db.jobs_with_status(conn, "running"):
                changes += self._check(conn, dict(job))
            changes += self._retention(conn)
        return changes

    def _submit(self, conn, job: dict) -> int:
        db.update_job(conn, job["id"], status="running", stage="Enviando al servidor GPU")
        try:
            call_id = self.backend.submit(job)
        except Exception as e:  # noqa: BLE001
            log.error("submit failed for %s: %s", job["id"], traceback.format_exc())
            db.update_job(conn, job["id"], status="error", stage=None, error=_friendly(e))
            return 1
        db.update_job(conn, job["id"], modal_call_id=call_id, stage="Transcribiendo")
        return 1

    def _check(self, conn, job: dict) -> int:
        call_id = job.get("modal_call_id")
        if not call_id:
            # crashed between status change and call id: re-queue
            db.update_job(conn, job["id"], status="queued", stage="En cola")
            return 1
        last = self._last_modal_poll.get(call_id, 0)
        if time.time() - last < config.MODAL_POLL_S and not call_id.startswith(("fake:", "local:")):
            return 0
        self._last_modal_poll[call_id] = time.time()
        try:
            result = self.backend.poll(call_id)
        except Exception as e:  # noqa: BLE001
            log.error("job %s failed: %s", job["id"], traceback.format_exc())
            db.update_job(conn, job["id"], status="error", stage=None, error=_friendly(e))
            return 1
        if result is None:
            return 0
        transcript = Transcript.from_dict(result)
        with db.tx(conn):
            db.save_transcript(conn, job["id"], transcript.to_dict())
            db.update_job(
                conn, job["id"], status="done", stage=None, finished_at=db.now(),
                duration_s=transcript.duration or job.get("duration_s"),
            )
        log.info("job %s done: %s", job["id"], transcript.timing)
        return 1

    def _retention(self, conn) -> int:
        """Delete audio RETENTION_DAYS after transcription (0 = right away, <0 = never)."""
        if config.RETENTION_DAYS < 0:
            return 0
        cutoff = (datetime.now(UTC) - timedelta(days=config.RETENTION_DAYS)).isoformat()
        rows = conn.execute(
            """SELECT id, audio_path FROM jobs
               WHERE status = 'done' AND audio_deleted_at IS NULL AND finished_at < ?""",
            (cutoff,),
        ).fetchall()
        n = 0
        for row in rows:
            if row["audio_path"]:
                shutil.rmtree(Path(row["audio_path"]).parent, ignore_errors=True)
            db.update_job(conn, row["id"], audio_deleted_at=db.now())
            n += 1
        return n

    def run_forever(self) -> None:
        log.info("worker started (backend=%s)", type(self.backend).__name__)
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.error("tick failed: %s", traceback.format_exc())
            time.sleep(config.WORKER_POLL_S)


def _friendly(e: Exception) -> str:
    name = type(e).__name__
    msg = str(e).strip().splitlines()[0] if str(e).strip() else name
    if name == "NotFoundError" and "not found in environment" in msg:
        return ("El servicio de transcripción no está desplegado en Modal. "
                "Ejecuta `uv run modal deploy modal_app.py` y pulsa Reintentar.")
    if name == "AuthError" or "token" in msg.lower() and "modal" in msg.lower():
        return "Faltan o son incorrectas las credenciales de Modal (MODAL_TOKEN_ID / MODAL_TOKEN_SECRET)."
    return f"No se pudo transcribir: {msg[:300]}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.init_db()
    Worker(make_backend()).run_forever()


if __name__ == "__main__":
    main()
