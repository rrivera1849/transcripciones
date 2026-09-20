"""FastAPI routes. All user-facing copy is Spanish."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from transcribe import Transcript
from transcribe.audio import ACCEPTED_EXTENSIONS, probe
from transcribe.export import to_docx, to_srt, to_txt
from transcribe.prompt import ROLE_SUGGESTIONS
from transcribe.roles import suggest_roles
from transcribe.turns import (
    clean_segments,
    fmt_ts,
    group_turns,
    merge_speakers,
    merge_turns,
    replace_text,
    replace_turn_text,
    set_turn_speaker,
    speaker_names,
    split_turn,
    turn_spans,
)

from . import auth, config, db

BASE = Path(__file__).parent
app = FastAPI(title="Transcripciones", docs_url=None, redoc_url=None)
STATIC_DIR = BASE / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

_asset_versions: dict[str, str] = {}


def asset(path: str) -> str:
    """/static/<path>?v=<content hash>: a new deploy gets a new URL, so no browser
    or Cloudflare cache can keep serving the previous CSS/JS."""
    v = _asset_versions.get(path)
    if v is None:
        try:
            v = hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]
        except OSError:
            v = "0"
        _asset_versions[path] = v
    return f"/static/{path}?v={v}"


templates.env.globals["asset"] = asset


@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        if "v" in request.query_params:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
    elif "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response
templates.env.filters["ts"] = fmt_ts
templates.env.globals["ROLE_SUGGESTIONS"] = ROLE_SUGGESTIONS

sessions = auth.Sessions(config.secret_key())
limiter = auth.LoginLimiter()
CHUNK = config.CHUNK_MB * 1024 * 1024
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
SPEAKER_COLORS = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#be185d", "#4d7c0f"]


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# --- auth plumbing -------------------------------------------------------

class NotLoggedIn(Exception):
    pass


@app.exception_handler(NotLoggedIn)
async def _not_logged_in(request: Request, exc: NotLoggedIn):
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


def current_session(request: Request) -> dict:
    session = sessions.read(request.cookies.get(auth.COOKIE))
    if not session:
        raise NotLoggedIn()
    return session


def csrf_ok(request: Request, session: dict, form_token: str | None = None) -> None:
    token = form_token or request.headers.get("X-CSRF-Token")
    auth.require_csrf(request, session, token)


def render(request: Request, name: str, session: dict | None = None, **ctx) -> HTMLResponse:
    ctx.update(request=request, session=session, csrf=(session or {}).get("csrf", ""))
    return templates.TemplateResponse(request, name, ctx)


# --- login ---------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if sessions.read(request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/", status_code=303)
    with db.connect() as conn:
        no_users = db.count_users(conn) == 0
    return render(request, "login.html", error=None, no_users=no_users)


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip().lower()
    key = (username, request.client.host if request.client else "?")
    if limiter.locked(key):
        return render(request, "login.html", no_users=False,
                      error="Demasiados intentos. Espera 15 minutos e inténtalo de nuevo.")
    with db.connect() as conn:
        user = db.get_user(conn, username)
    if not user or not auth.verify_password(password, user["password_hash"]):
        limiter.fail(key)
        return render(request, "login.html", no_users=False,
                      error="Usuario o contraseña incorrectos.")
    limiter.reset(key)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        auth.COOKIE, sessions.issue(username), max_age=config.SESSION_DAYS * 86400,
        httponly=True, samesite="lax", secure=request.url.scheme == "https",
    )
    return resp


@app.post("/logout")
def logout(request: Request, session: dict = Depends(current_session),
           csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


MIN_PASSWORD_LEN = 8


def _account(request: Request, session: dict, **ctx) -> HTMLResponse:
    with db.connect() as conn:
        user = db.get_user(conn, session["u"])
    ctx.setdefault("email", (user["email"] if user else "") or "")
    ctx.setdefault("error", None)
    ctx.setdefault("ok", False)
    ctx.setdefault("email_ok", False)
    ctx["mail_enabled"] = bool(config.SMTP_HOST)
    return render(request, "account.html", session, **ctx)


@app.get("/cuenta", response_class=HTMLResponse)
def account_page(request: Request, session: dict = Depends(current_session)):
    return _account(request, session)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.post("/cuenta/correo", response_class=HTMLResponse)
def set_email(request: Request, session: dict = Depends(current_session),
              email: str = Form(""), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    email = email.strip()[:200]
    if email and not _EMAIL_RE.match(email):
        return _account(request, session, email=email, error="Ese correo no parece válido.")
    with db.connect() as conn:
        db.set_email(conn, session["u"], email)
    return _account(request, session, email=email, email_ok=True)


@app.post("/cuenta", response_class=HTMLResponse)
def change_password(request: Request, session: dict = Depends(current_session),
                    current: str = Form(...), new: str = Form(...), confirm: str = Form(...),
                    csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        user = db.get_user(conn, session["u"])
        if not user or not auth.verify_password(current, user["password_hash"]):
            error = "La contraseña actual no es correcta."
        elif len(new) < MIN_PASSWORD_LEN:
            error = f"La contraseña nueva debe tener al menos {MIN_PASSWORD_LEN} caracteres."
        elif new != confirm:
            error = "Las dos contraseñas nuevas no coinciden."
        elif new == current:
            error = "La contraseña nueva es igual a la actual."
        else:
            db.set_password(conn, session["u"], auth.hash_password(new))
            error = None
    return _account(request, session, error=error, ok=error is None)


# --- home + job list -----------------------------------------------------

def _job_view(row) -> dict:
    j = dict(row)
    j["pct"] = int(100 * j["received_bytes"] / j["size_bytes"]) if j["size_bytes"] else 0
    j["duration"] = fmt_ts(j["duration_s"]) if j.get("duration_s") else ""
    j["date"] = (j["created_at"] or "")[:10]
    j["status_label"] = {
        "uploading": "Subiendo", "queued": "En cola", "running": j.get("stage") or "Transcribiendo",
        "done": "Listo", "error": "Error",
    }[j["status"]]
    return j


@app.get("/", response_class=HTMLResponse)
def home(request: Request, session: dict = Depends(current_session)):
    with db.connect() as conn:
        jobs = [_job_view(r) for r in db.list_jobs(conn)]
        active = db.any_active(conn)
    return render(request, "index.html", session, jobs=jobs, active=active,
                  default_speakers=config.DEFAULT_MIN_SPEAKERS, chunk=CHUNK,
                  max_bytes=config.MAX_UPLOAD_MB * 1024 * 1024,
                  extensions=sorted(ACCEPTED_EXTENSIONS))


@app.get("/buscar", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", session: dict = Depends(current_session)):
    q = q.strip()[:200]
    with db.connect() as conn:
        results = [dict(_job_view(r), snippet=r["snippet"]) for r in db.search(conn, q)] if q else []
    return render(request, "search.html", session, q=q, results=results)


@app.get("/jobs", response_class=HTMLResponse)
def jobs_partial(request: Request, session: dict = Depends(current_session)):
    with db.connect() as conn:
        jobs = [_job_view(r) for r in db.list_jobs(conn)]
        active = db.any_active(conn)
    return render(request, "_jobs.html", session, jobs=jobs, active=active)


# --- chunked upload ------------------------------------------------------

def _safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ACCEPTED_EXTENSIONS:
        raise HTTPException(400, "Este archivo no parece ser audio o video.")
    return ext


def _job_or_404(conn, job_id: str):
    if not JOB_ID.match(job_id):
        raise HTTPException(404)
    job = db.get_job(conn, job_id)
    if not job:
        raise HTTPException(404)
    return job


@app.post("/upload/init")
async def upload_init(request: Request, session: dict = Depends(current_session)):
    csrf_ok(request, session)
    body = await request.json()
    filename = str(body.get("filename", ""))[:200]
    size = int(body.get("size", 0))
    ext = _safe_ext(filename)
    if size <= 0 or size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el máximo de {config.MAX_UPLOAD_MB} MB.")
    title = (str(body.get("title") or "").strip() or Path(filename).stem)[:200]
    min_speakers = body.get("min_speakers")
    min_speakers = int(min_speakers) if min_speakers not in (None, "", 0, "0") else None
    vocabulary = (str(body.get("vocabulary") or "").strip() or None)
    with db.connect() as conn:
        job_id = db.create_job(
            conn, title=title, original_filename=filename, size_bytes=size,
            min_speakers=min_speakers, vocabulary=vocabulary and vocabulary[:1000],
            created_by=session["u"],
        )
        path = config.AUDIO_DIR / job_id / f"input{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        db.update_job(conn, job_id, audio_path=str(path))
    return {"job_id": job_id, "chunk": CHUNK}


@app.put("/upload/{job_id}/chunk/{index}")
async def upload_chunk(request: Request, job_id: str, index: int,
                       session: dict = Depends(current_session)):
    csrf_ok(request, session)
    data = await request.body()
    with db.connect() as conn:
        job = _job_or_404(conn, job_id)
        if job["status"] != "uploading":
            raise HTTPException(409, "La subida ya terminó.")
        expected = index * CHUNK
        if job["received_bytes"] != expected:
            if job["received_bytes"] > expected:
                return {"received": job["received_bytes"]}  # duplicate chunk after a retry
            raise HTTPException(409, "Falta un fragmento anterior.")
        if job["received_bytes"] + len(data) > job["size_bytes"]:
            raise HTTPException(400, "Se recibieron más datos que el tamaño anunciado.")
        with open(job["audio_path"], "ab") as f:
            f.write(data)
        received = job["received_bytes"] + len(data)
        db.update_job(conn, job_id, received_bytes=received)
    return {"received": received}


@app.post("/upload/{job_id}/complete")
def upload_complete(request: Request, job_id: str, session: dict = Depends(current_session)):
    csrf_ok(request, session)
    with db.connect() as conn:
        job = _job_or_404(conn, job_id)
        if job["received_bytes"] != job["size_bytes"]:
            raise HTTPException(400, "La subida está incompleta.")
        try:
            info = probe(job["audio_path"])
        except subprocess.CalledProcessError:
            info = {"duration": 0}
        if not info.get("duration"):
            db.update_job(conn, job_id, status="error", stage=None,
                          error="El archivo no contiene audio que se pueda leer.")
            raise HTTPException(400, "El archivo no contiene audio que se pueda leer.")
        db.update_job(conn, job_id, status="queued", stage="En cola", duration_s=info["duration"])
    return {"ok": True}


# --- transcript page -----------------------------------------------------

def _load(conn, job_id: str, session: dict):
    job = _job_or_404(conn, job_id)
    found = db.get_transcript(conn, job_id)
    if not found:
        raise HTTPException(404)
    data, overrides = found
    transcript = Transcript.from_dict(data)
    cleaned = clean_segments(transcript.segments)
    if len(cleaned) != len(transcript.segments):  # legacy uncleaned data: normalise once
        transcript.segments = cleaned
        db.update_transcript(conn, job_id, data=transcript.to_dict(), edited_by=session["u"])
    return job, transcript, overrides


def _speaker_ctx(transcript: Transcript, overrides: dict) -> list[dict]:
    names = speaker_names(transcript, overrides)
    suggested = suggest_roles(transcript)
    return [
        {
            "id": sid, "name": names[sid], "color": SPEAKER_COLORS[i % len(SPEAKER_COLORS)],
            # Only propose a role while the voice still has its default name.
            "suggestion": None if overrides.get(sid) else suggested.get(sid),
        }
        for i, sid in enumerate(transcript.speakers())
    ]


def _turns_ctx(transcript: Transcript, overrides: dict) -> dict:
    speakers = _speaker_ctx(transcript, overrides)
    by_id = {s["id"]: s for s in speakers}
    grouped = group_turns(transcript.segments)
    turns = [
        {
            "i": i, "start": t.start, "end": t.end, "text": t.text, "speaker": t.speaker,
            "name": by_id[t.speaker]["name"] if t.speaker in by_id else "",
            "color": by_id[t.speaker]["color"] if t.speaker in by_id else "#666",
            "can_merge_up": i > 0 and grouped[i - 1].speaker == t.speaker,
            "spans": turn_spans(t),
        }
        for i, t in enumerate(grouped)
    ]
    doubtful = sum(1 for t in turns for _, w in t["spans"] if w is not None)
    return {"turns": turns, "speakers": speakers, "doubtful": doubtful}


@app.get("/t/{job_id}", response_class=HTMLResponse)
def transcript_page(request: Request, job_id: str, q: str = "",
                    session: dict = Depends(current_session)):
    with db.connect() as conn:
        job, transcript, overrides = _load(conn, job_id, session)
        revs = db.list_revisions(conn, job_id)
        revisions, can_undo = len(revs), db.undo_target(revs) is not None
    ctx = _turns_ctx(transcript, overrides)
    audio_ok = job["audio_path"] and Path(job["audio_path"]).exists() and not job["audio_deleted_at"]
    return render(request, "transcript.html", session, job=_job_view(job), audio_ok=audio_ok,
                  duration=fmt_ts(transcript.duration or 0), q=q.strip()[:200],
                  retention_days=config.RETENTION_DAYS, revisions=revisions, can_undo=can_undo, **ctx)


def _turns_response(request: Request, session: dict, job_id: str) -> HTMLResponse:
    with db.connect() as conn:
        job, transcript, overrides = _load(conn, job_id, session)
    return render(request, "_turns.html", session, job=_job_view(job),
                  **_turns_ctx(transcript, overrides))


@app.post("/t/{job_id}/speaker/rename", response_class=HTMLResponse)
def speaker_rename(request: Request, job_id: str, session: dict = Depends(current_session),
                   speaker: str = Form(...), name: str = Form(...), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _, transcript, overrides = _load(conn, job_id, session)
        if speaker in transcript.speakers():
            overrides[speaker] = name.strip()[:60]
            db.update_transcript(conn, job_id, speaker_names=overrides, edited_by=session["u"],
                                 action=f"nombrar hablante «{overrides[speaker]}»")
    return _turns_response(request, session, job_id)


@app.post("/t/{job_id}/speaker/merge", response_class=HTMLResponse)
def speaker_merge(request: Request, job_id: str, session: dict = Depends(current_session),
                  keep: str = Form(...), absorb: str = Form(...), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _, transcript, overrides = _load(conn, job_id, session)
        ids = transcript.speakers()
        if keep in ids and absorb in ids and keep != absorb:
            merge_speakers(transcript, keep, absorb)
            overrides.pop(absorb, None)
            db.update_transcript(conn, job_id, data=transcript.to_dict(),
                                 speaker_names=overrides, edited_by=session["u"],
                                 action="unir dos hablantes")
    return _turns_response(request, session, job_id)


@app.post("/t/{job_id}/turn/{index}/text", response_class=HTMLResponse)
def turn_text(request: Request, job_id: str, index: int,
              session: dict = Depends(current_session),
              text: str = Form(...), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _, transcript, _overrides = _load(conn, job_id, session)
        turns = group_turns(transcript.segments)
        if 0 <= index < len(turns) and text.strip():
            transcript.segments = replace_turn_text(transcript.segments, turns[index], text)
            db.update_transcript(conn, job_id, data=transcript.to_dict(), edited_by=session["u"],
                                 action=f"editar el párrafo de {fmt_ts(turns[index].start)}")
    return _turns_response(request, session, job_id)


@app.post("/t/{job_id}/turn/{index}/merge-up", response_class=HTMLResponse)
def turn_merge_up(request: Request, job_id: str, index: int,
                  session: dict = Depends(current_session), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _, transcript, _overrides = _load(conn, job_id, session)
        turns = group_turns(transcript.segments)
        if 1 <= index < len(turns) and turns[index - 1].speaker == turns[index].speaker:
            transcript.segments = merge_turns(transcript.segments, turns[index - 1], turns[index])
            db.update_transcript(conn, job_id, data=transcript.to_dict(), edited_by=session["u"],
                                 action=f"unir párrafos en {fmt_ts(turns[index].start)}")
    return _turns_response(request, session, job_id)


@app.post("/t/{job_id}/turn/{index}/speaker", response_class=HTMLResponse)
def turn_speaker(request: Request, job_id: str, index: int,
                 session: dict = Depends(current_session),
                 speaker: str = Form(...), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _, transcript, _overrides = _load(conn, job_id, session)
        turns = group_turns(transcript.segments)
        if 0 <= index < len(turns) and speaker in transcript.speakers():
            transcript.segments = set_turn_speaker(transcript.segments, turns[index], speaker)
            db.update_transcript(conn, job_id, data=transcript.to_dict(), edited_by=session["u"],
                                 action=f"cambiar el hablante en {fmt_ts(turns[index].start)}")
    return _turns_response(request, session, job_id)


@app.post("/t/{job_id}/turn/{index}/split", response_class=HTMLResponse)
def turn_split(request: Request, job_id: str, index: int,
               session: dict = Depends(current_session),
               before: str = Form(...), after: str = Form(...), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _, transcript, _overrides = _load(conn, job_id, session)
        turns = group_turns(transcript.segments)
        if 0 <= index < len(turns) and before.strip() and after.strip():
            transcript.segments = split_turn(transcript.segments, turns[index], before, after)
            db.update_transcript(conn, job_id, data=transcript.to_dict(), edited_by=session["u"],
                                 action=f"dividir el párrafo de {fmt_ts(turns[index].start)}")
    return _turns_response(request, session, job_id)


@app.post("/t/{job_id}/replace", response_class=HTMLResponse)
def replace_all(request: Request, job_id: str, session: dict = Depends(current_session),
                find: str = Form(...), replace: str = Form(""), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    count = 0
    with db.connect() as conn:
        _, transcript, _overrides = _load(conn, job_id, session)
        if find.strip():
            transcript.segments, count = replace_text(transcript.segments, find[:200], replace[:200])
            if count:
                db.update_transcript(conn, job_id, data=transcript.to_dict(), edited_by=session["u"],
                                     action=f"reemplazar «{find.strip()[:40]}» por «{replace.strip()[:40]}»")
    resp = _turns_response(request, session, job_id)
    resp.headers["HX-Trigger"] = json.dumps({"replaced": count})
    return resp


# --- revision history ----------------------------------------------------

def _local_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso).astimezone(ZoneInfo(config.DISPLAY_TZ))
    except (ValueError, KeyError):
        return iso
    return dt.strftime("%d/%m/%Y %H:%M")


@app.get("/t/{job_id}/historial", response_class=HTMLResponse)
def history_partial(request: Request, job_id: str, session: dict = Depends(current_session)):
    with db.connect() as conn:
        job = _job_or_404(conn, job_id)
        revs = db.list_revisions(conn, job_id)
    for r in revs:
        r["when"] = _local_time(r["created_at"])
    return render(request, "_history.html", session, job=_job_view(job), revisions=revs)


@app.post("/t/{job_id}/restaurar")
def restore(request: Request, job_id: str, session: dict = Depends(current_session),
            rev: int = Form(...), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _job_or_404(conn, job_id)
        with db.tx(conn):
            db.restore_revision(conn, job_id, rev, session["u"])
    return RedirectResponse(f"/t/{job_id}", status_code=303)


@app.post("/t/{job_id}/deshacer")
def undo(request: Request, job_id: str, session: dict = Depends(current_session),
         csrf_token: str = Form(...)):
    """Put back the state before the most recent change."""
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _job_or_404(conn, job_id)
        target = db.undo_target(db.list_revisions(conn, job_id))
        if target is not None:
            with db.tx(conn):
                db.restore_revision(conn, job_id, target, session["u"], action="deshacer")
    return RedirectResponse(f"/t/{job_id}", status_code=303)


@app.post("/t/{job_id}/retry")
def retry_job(request: Request, job_id: str, session: dict = Depends(current_session),
              csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        job = _job_or_404(conn, job_id)
        audio_there = job["audio_path"] and Path(job["audio_path"]).exists()
        if job["status"] == "error" and audio_there and job["received_bytes"] == job["size_bytes"]:
            db.update_job(conn, job_id, status="queued", stage="En cola", error=None,
                          modal_call_id=None)
    return RedirectResponse("/", status_code=303)


@app.post("/t/{job_id}/title")
def rename_job(request: Request, job_id: str, session: dict = Depends(current_session),
               title: str = Form(...), csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    with db.connect() as conn:
        _job_or_404(conn, job_id)
        db.update_job(conn, job_id, title=title.strip()[:200] or "Sin título")
    return RedirectResponse(f"/t/{job_id}", status_code=303)


@app.post("/t/{job_id}/delete")
def delete_job(request: Request, job_id: str, session: dict = Depends(current_session),
               csrf_token: str = Form(...)):
    csrf_ok(request, session, csrf_token)
    import shutil

    with db.connect() as conn:
        job = _job_or_404(conn, job_id)
        db.delete_job(conn, job_id)
    if job["audio_path"]:
        shutil.rmtree(Path(job["audio_path"]).parent, ignore_errors=True)
    return RedirectResponse("/", status_code=303)


# --- downloads + audio ---------------------------------------------------

def _slug(title: str) -> str:
    s = re.sub(r"[^\w\-. ]+", "", title, flags=re.UNICODE).strip().replace(" ", "_")
    return s[:80] or "transcripcion"


@app.get("/t/{job_id}/download/{fmt}")
def download(job_id: str, fmt: str, session: dict = Depends(current_session)):
    with db.connect() as conn:
        job, transcript, overrides = _load(conn, job_id, session)
    stem = _slug(job["title"])
    headers = {"Content-Disposition": f'attachment; filename="{stem}.{fmt}"'}
    if fmt == "txt":
        return Response(to_txt(transcript, overrides, title=job["title"]),
                        media_type="text/plain; charset=utf-8", headers=headers)
    if fmt == "srt":
        return Response(to_srt(transcript, overrides), media_type="text/plain; charset=utf-8",
                        headers=headers)
    if fmt == "json":
        return Response(json.dumps(transcript.to_dict(), ensure_ascii=False, indent=1),
                        media_type="application/json", headers=headers)
    if fmt == "docx":
        import tempfile

        tmp = Path(tempfile.mkdtemp()) / f"{stem}.docx"
        to_docx(transcript, tmp, overrides, title=job["title"], subtitle=job["created_at"][:10])
        return FileResponse(str(tmp), filename=f"{stem}.docx",
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    raise HTTPException(404)


@app.get("/t/{job_id}/audio")
def audio(request: Request, job_id: str, session: dict = Depends(current_session)):
    with db.connect() as conn:
        job = _job_or_404(conn, job_id)
    path = Path(job["audio_path"] or "")
    if not path.exists() or job["audio_deleted_at"]:
        raise HTTPException(404)
    size = path.stat().st_size
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    rng = request.headers.get("range")
    start, end = 0, size - 1
    status = 200
    if rng and rng.startswith("bytes="):
        a, _, b = rng[6:].partition("-")
        start = int(a) if a else max(0, size - int(b or 0))
        end = int(b) if (b and a) else end
        end = min(end, size - 1)
        if start > end:
            raise HTTPException(416)
        status = 206

    def stream():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(stream(), status_code=status, media_type=media, headers=headers)


@app.get("/healthz")
def healthz():
    with db.connect() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}
