"""SQLite schema and helpers. One file, WAL mode, used by web and worker."""

from __future__ import annotations

import json
import sqlite3
import uuid
import zlib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    audio_path TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    received_bytes INTEGER NOT NULL DEFAULT 0,
    duration_s REAL,
    status TEXT NOT NULL,            -- uploading | queued | running | done | error
    stage TEXT,                      -- human-readable progress
    error TEXT,
    min_speakers INTEGER,
    vocabulary TEXT,
    modal_call_id TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    audio_deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS transcripts (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    data TEXT NOT NULL,              -- Transcript.to_dict() as JSON
    speaker_names TEXT NOT NULL DEFAULT '{}',
    edited_at TEXT,
    edited_by TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
    job_id UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS transcript_revisions (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    edited_by TEXT,
    action TEXT NOT NULL,            -- what the change *after* this snapshot did
    data BLOB NOT NULL,              -- zlib(JSON) of the transcript before the change
    speaker_names TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revisions_job ON transcript_revisions(job_id, id);
"""

# Columns added after the first release; applied by init_db when missing.
MIGRATIONS = [("users", "email", "ALTER TABLE users ADD COLUMN email TEXT")]

MAX_REVISIONS = 30

ACTIVE_STATUSES = ("uploading", "queued", "running")


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(ddl)
        # backfill the search index for transcripts saved before it existed
        missing = conn.execute(
            """SELECT t.job_id FROM transcripts t
               LEFT JOIN transcript_fts f ON f.job_id = t.job_id WHERE f.job_id IS NULL"""
        ).fetchall()
        for row in missing:
            reindex(conn, row["job_id"])


@contextmanager
def tx(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --- users ---------------------------------------------------------------

def get_user(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def create_user(conn: sqlite3.Connection, username: str, password_hash: str) -> None:
    conn.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, now()),
    )


def set_password(conn: sqlite3.Connection, username: str, password_hash: str) -> bool:
    cur = conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username)
    )
    return cur.rowcount == 1


def set_email(conn: sqlite3.Connection, username: str, email: str | None) -> None:
    conn.execute("UPDATE users SET email = ? WHERE username = ?", (email or None, username))


def count_users(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# --- jobs ----------------------------------------------------------------

def create_job(
    conn: sqlite3.Connection,
    *,
    title: str,
    original_filename: str,
    size_bytes: int,
    min_speakers: int | None,
    vocabulary: str | None,
    created_by: str,
) -> str:
    job_id = new_id()
    ts = now()
    conn.execute(
        """INSERT INTO jobs (id, title, original_filename, size_bytes, status, stage,
               min_speakers, vocabulary, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'uploading', 'Subiendo', ?, ?, ?, ?, ?)""",
        (job_id, title, original_filename, size_bytes, min_speakers, vocabulary, created_by, ts, ts),
    )
    return job_id


def get_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()


def jobs_with_status(conn: sqlite3.Connection, *statuses: str) -> list[sqlite3.Row]:
    q = ",".join("?" * len(statuses))
    return conn.execute(
        f"SELECT * FROM jobs WHERE status IN ({q}) ORDER BY created_at", statuses
    ).fetchall()


def any_active(conn: sqlite3.Connection) -> bool:
    q = ",".join("?" * len(ACTIVE_STATUSES))
    return conn.execute(
        f"SELECT 1 FROM jobs WHERE status IN ({q}) LIMIT 1", ACTIVE_STATUSES
    ).fetchone() is not None


def update_job(conn: sqlite3.Connection, job_id: str, **fields: Any) -> None:
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
    if "title" in fields:
        reindex(conn, job_id)


def delete_job(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.execute("DELETE FROM transcript_fts WHERE job_id = ?", (job_id,))


# --- transcripts ---------------------------------------------------------

def save_transcript(conn: sqlite3.Connection, job_id: str, data: dict) -> None:
    conn.execute(
        """INSERT INTO transcripts (job_id, data) VALUES (?, ?)
           ON CONFLICT(job_id) DO UPDATE SET data = excluded.data""",
        (job_id, json.dumps(data, ensure_ascii=False)),
    )
    reindex(conn, job_id)


def get_transcript(conn: sqlite3.Connection, job_id: str) -> tuple[dict, dict] | None:
    row = conn.execute("SELECT * FROM transcripts WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return json.loads(row["data"]), json.loads(row["speaker_names"])


def update_transcript(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    data: dict | None = None,
    speaker_names: dict | None = None,
    edited_by: str | None = None,
    action: str | None = None,
) -> None:
    """Write a change. With `action`, the previous state is kept as a revision first."""
    if action:
        _snapshot(conn, job_id, action, edited_by)
    sets, vals = ["edited_at = ?", "edited_by = ?"], [now(), edited_by]
    if data is not None:
        sets.append("data = ?")
        vals.append(json.dumps(data, ensure_ascii=False))
    if speaker_names is not None:
        sets.append("speaker_names = ?")
        vals.append(json.dumps(speaker_names, ensure_ascii=False))
    conn.execute(f"UPDATE transcripts SET {', '.join(sets)} WHERE job_id = ?", (*vals, job_id))
    if data is not None:
        reindex(conn, job_id)


# --- revisions -----------------------------------------------------------

def _snapshot(conn: sqlite3.Connection, job_id: str, action: str, edited_by: str | None) -> None:
    row = conn.execute(
        "SELECT data, speaker_names FROM transcripts WHERE job_id = ?", (job_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute(
        """INSERT INTO transcript_revisions (job_id, created_at, edited_by, action, data, speaker_names)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (job_id, now(), edited_by, action[:120], zlib.compress(row["data"].encode("utf-8")),
         row["speaker_names"]),
    )
    conn.execute(
        """DELETE FROM transcript_revisions WHERE job_id = ? AND id NOT IN (
               SELECT id FROM transcript_revisions WHERE job_id = ? ORDER BY id DESC LIMIT ?)""",
        (job_id, job_id, MAX_REVISIONS),
    )


def list_revisions(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    """Newest first; no data payload."""
    rows = conn.execute(
        """SELECT id, created_at, edited_by, action FROM transcript_revisions
           WHERE job_id = ? ORDER BY id DESC""",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def restore_revision(conn: sqlite3.Connection, job_id: str, rev_id: int, edited_by: str) -> bool:
    """Put a snapshot back as the current transcript. The current state is kept, so this is undoable."""
    row = conn.execute(
        "SELECT data, speaker_names FROM transcript_revisions WHERE id = ? AND job_id = ?",
        (rev_id, job_id),
    ).fetchone()
    if row is None:
        return False
    update_transcript(
        conn, job_id,
        data=json.loads(zlib.decompress(row["data"]).decode("utf-8")),
        speaker_names=json.loads(row["speaker_names"]),
        edited_by=edited_by, action="restaurar una versión anterior",
    )
    return True


# --- search --------------------------------------------------------------

def reindex(conn: sqlite3.Connection, job_id: str) -> None:
    """Rebuild the full-text row for one job from its title and transcript text."""
    row = conn.execute(
        """SELECT j.title, t.data FROM jobs j LEFT JOIN transcripts t ON t.job_id = j.id
           WHERE j.id = ?""",
        (job_id,),
    ).fetchone()
    conn.execute("DELETE FROM transcript_fts WHERE job_id = ?", (job_id,))
    if row is None or row["data"] is None:
        return
    body = " ".join(
        " ".join(str(s.get("text", "")).split()) for s in json.loads(row["data"]).get("segments", [])
    )
    conn.execute(
        "INSERT INTO transcript_fts (job_id, title, body) VALUES (?, ?, ?)",
        (job_id, row["title"], body),
    )


def fts_query(q: str) -> str:
    """Turn free text into a safe FTS5 query: every word required, prefix-matched."""
    words = [w.replace('"', "") for w in q.split()]
    words = [w for w in words if w]
    return " ".join(f'"{w}"*' for w in words)


def search(conn: sqlite3.Connection, q: str, limit: int = 50) -> list[dict]:
    match = fts_query(q)
    if not match:
        return []
    rows = conn.execute(
        """SELECT j.*, snippet(transcript_fts, 2, '<mark>', '</mark>', '…', 14) AS snippet,
                  bm25(transcript_fts) AS rank
           FROM transcript_fts JOIN jobs j ON j.id = transcript_fts.job_id
           WHERE transcript_fts MATCH ?
           ORDER BY rank LIMIT ?""",
        (match, limit),
    ).fetchall()
    return [dict(r) for r in rows]
