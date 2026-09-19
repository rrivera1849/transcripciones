"""Configuration from environment variables, with local-dev defaults."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments, no override of real env vars."""
    path = path or Path(os.environ.get("ENV_FILE", ".env"))
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)


load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", "data")).resolve()
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "app.sqlite3"

# "modal" (GPU, production) or "local" (CPU faster-whisper, no speakers; dev only)
TRANSCRIBER = os.environ.get("TRANSCRIBER", "modal")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "small")

RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "4096"))
CHUNK_MB = 5
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "90"))
WORKER_POLL_S = float(os.environ.get("WORKER_POLL_S", "3"))
MODAL_POLL_S = float(os.environ.get("MODAL_POLL_S", "20"))

LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_S = 15 * 60

DEFAULT_MIN_SPEAKERS = 3


def secret_key() -> str:
    """SECRET_KEY from the environment, else a persisted random one under DATA_DIR."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = DATA_DIR / "secret_key"
    if path.exists():
        return path.read_text().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    path.write_text(key)
    path.chmod(0o600)
    return key
