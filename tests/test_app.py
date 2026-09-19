"""End-to-end tests of the web app with a fake transcriber backend."""

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIX = Path(__file__).parent / "fixtures" / "sample.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.sqlite3")
    monkeypatch.setattr(config, "CHUNK_MB", 1)
    from app import auth, db, main

    monkeypatch.setattr(main, "CHUNK", 1024 * 1024)
    monkeypatch.setattr(main, "limiter", auth.LoginLimiter())
    db.init_db()
    with db.connect() as conn:
        db.create_user(conn, "mama", auth.hash_password("secreta"))
    with TestClient(main.app) as c:
        yield c


def login(c, password="secreta"):
    r = c.post("/login", data={"username": "mama", "password": password}, follow_redirects=False)
    return r


def csrf_of(c):
    from app import main

    return main.sessions.read(c.cookies.get("session"))["csrf"]


def test_login_required_and_wrong_password(client):
    assert client.get("/", follow_redirects=False).status_code == 303
    assert "incorrectos" in login(client, "nope").text
    assert login(client).status_code == 303
    assert "Subir una grabación" in client.get("/").text


def test_lockout_after_failures(client):
    for _ in range(5):
        login(client, "nope")
    assert "Demasiados intentos" in login(client, "secreta").text


def _make_wav(path: Path, seconds: float = 1.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-ar", "16000", "-ac", "1", str(path)],
        check=True,
    )
    return path


def upload(c, path: Path, **fields) -> str:
    headers = {"X-CSRF-Token": csrf_of(c)}
    size = path.stat().st_size
    r = c.post("/upload/init", json={"filename": path.name, "size": size, **fields}, headers=headers)
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    chunk = r.json()["chunk"]
    data = path.read_bytes()
    for i in range(0, size, chunk):
        r = c.put(f"/upload/{job_id}/chunk/{i // chunk}", content=data[i:i + chunk], headers=headers)
        assert r.status_code == 200, r.text
    r = c.post(f"/upload/{job_id}/complete", headers=headers)
    assert r.status_code == 200, r.text
    return job_id


def test_upload_then_worker_then_transcript_page(client, tmp_path):
    from app import db
    from app.worker import FakeBackend, Worker

    login(client)
    wav = _make_wav(tmp_path / "vista.wav", seconds=1.5)
    job_id = upload(client, wav, title="Vista de prueba", min_speakers=3, vocabulary="Morovis")
    with db.connect() as conn:
        job = db.get_job(conn, job_id)
    assert job["status"] == "queued" and job["min_speakers"] == 3 and job["vocabulary"] == "Morovis"
    assert job["duration_s"] and 1.4 < job["duration_s"] < 1.6

    backend = FakeBackend(json.loads(FIX.read_text(encoding="utf-8")))
    w = Worker(backend)
    assert w.tick() >= 1  # submit + (fake backend answers immediately) result
    assert backend.submitted[0]["min_speakers"] == 3
    with db.connect() as conn:
        assert db.get_job(conn, job_id)["status"] == "done"

    page = client.get(f"/t/{job_id}")
    assert page.status_code == 200
    assert "Hablante 1" in page.text and "Se abre la sesión" in page.text
    assert client.get("/").text.count("Listo") == 1


def test_rename_merge_edit_and_downloads(client, tmp_path):
    from app import db
    from app.worker import FakeBackend, Worker

    login(client)
    job_id = upload(client, _make_wav(tmp_path / "a.wav"))
    Worker(FakeBackend(json.loads(FIX.read_text(encoding="utf-8")))).tick()
    Worker(FakeBackend(json.loads(FIX.read_text(encoding="utf-8")))).tick()
    csrf = csrf_of(client)

    r = client.post(f"/t/{job_id}/speaker/rename",
                    data={"speaker": "SPEAKER_00", "name": "Jueza", "csrf_token": csrf})
    assert r.status_code == 200 and "Jueza" in r.text

    r = client.post(f"/t/{job_id}/turn/0/text",
                    data={"text": "Se abre la sesión, licenciado.", "csrf_token": csrf})
    assert "Se abre la sesión, licenciado." in r.text

    # turn 3 is "Ha lugar." by SPEAKER_00; hand it to SPEAKER_01
    r = client.post(f"/t/{job_id}/turn/3/speaker", data={"speaker": "SPEAKER_01", "csrf_token": csrf})
    assert r.status_code == 200
    with db.connect() as conn:
        data, _ = db.get_transcript(conn, job_id)
    assert [s["speaker"] for s in data["segments"] if s["text"] == "Ha lugar."] == ["SPEAKER_01"]

    r = client.post(f"/t/{job_id}/speaker/merge",
                    data={"keep": "SPEAKER_01", "absorb": "SPEAKER_02", "csrf_token": csrf})
    assert r.status_code == 200
    with db.connect() as conn:
        data, names = db.get_transcript(conn, job_id)
    assert names == {"SPEAKER_00": "Jueza"}
    assert {s["speaker"] for s in data["segments"]} == {"SPEAKER_00", "SPEAKER_01"}

    txt = client.get(f"/t/{job_id}/download/txt")
    assert txt.status_code == 200 and "Jueza:" in txt.text
    assert client.get(f"/t/{job_id}/download/srt").status_code == 200
    docx = client.get(f"/t/{job_id}/download/docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"

    audio = client.get(f"/t/{job_id}/audio", headers={"Range": "bytes=0-99"})
    assert audio.status_code == 206 and len(audio.content) == 100

    # CSRF is enforced
    assert client.post(f"/t/{job_id}/turn/0/text", data={"text": "x", "csrf_token": "bad"}).status_code == 403

    r = client.post(f"/t/{job_id}/delete", data={"csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get(f"/t/{job_id}").status_code == 404


def test_rejects_non_audio(client, tmp_path):
    login(client)
    bad = tmp_path / "notas.txt"
    bad.write_text("hola")
    r = client.post("/upload/init", json={"filename": bad.name, "size": 4}, headers={"X-CSRF-Token": csrf_of(client)})
    assert r.status_code == 400


def test_search_across_hearings_is_accent_insensitive(client, tmp_path):
    from app import db
    from app.worker import FakeBackend, Worker

    login(client)
    job_id = upload(client, _make_wav(tmp_path / "a.wav"), title="Vista Morovis")
    Worker(FakeBackend(json.loads(FIX.read_text(encoding="utf-8")))).tick()

    r = client.get("/buscar", params={"q": "sesion"})  # matches "sesión"
    assert r.status_code == 200 and "Vista Morovis" in r.text and "<mark>sesión</mark>" in r.text
    assert f"/t/{job_id}?q=sesion" in r.text
    assert "No se encontró" in client.get("/buscar", params={"q": "zanahoria"}).text
    assert "Vista Morovis" in client.get("/buscar", params={"q": "morovis"}).text  # title indexed
    assert client.get("/buscar", params={"q": '"unbalanced'}).status_code == 200  # never a 500

    # edits are re-indexed
    csrf = csrf_of(client)
    client.post(f"/t/{job_id}/turn/0/text", data={"text": "Comienza la audiencia.", "csrf_token": csrf})
    assert "audiencia" in client.get("/buscar", params={"q": "audiencia"}).text
    assert "No se encontró" in client.get("/buscar", params={"q": "sesion"}).text

    page = client.get(f"/t/{job_id}", params={"q": "venia"})
    assert 'id="find"' in page.text and 'value="venia"' in page.text

    with db.connect() as conn:
        db.delete_job(conn, job_id)
    assert "No se encontró" in client.get("/buscar", params={"q": "venia"}).text
