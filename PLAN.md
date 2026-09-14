# Transcripciones — Project Plan

A small, self-hosted web app that lets a non-technical user upload Spanish
audio files and get back accurate text transcripts, protected by a login and
reachable from anywhere on the internet.

> Terminology: the task is **speech-to-text (STT / ASR)**, not TTS. TTS is the
> reverse direction (text → voice). Everything below is about STT.

---

## 1. Goals and non-goals

**Goals**

- One user (Mom) uploads audio from a phone or laptop and gets a transcript.
- Spanish-only, high accuracy, good punctuation.
- Zero technical steps for her: open a link, log in once, drag a file, wait,
  read / copy / download.
- Runs on open-source models; no per-minute API bills as the default path.
- Password-protected and served over HTTPS.

**Non-goals (for v1)**

- Multi-tenant accounts, billing, public sign-up.
- Real-time / live transcription.
- Speaker labels and summaries (listed as optional phase 5).

---

## 2. Key decisions

### 2.1 Transcription engine: `faster-whisper`

| Option | Verdict |
|---|---|
| **faster-whisper** (CTranslate2 port of OpenAI Whisper) | **Chosen.** Best accuracy/speed trade-off, runs on CPU or GPU, mature, Python, Spanish is one of Whisper's strongest languages. |
| whisper.cpp | Great on Apple Silicon / low-RAM CPU boxes. Keep as fallback if we end up hosting on a Mac. |
| WhisperX | faster-whisper + word alignment + pyannote diarization. Use in phase 5 if speaker labels are wanted. |
| NVIDIA Parakeet / Canary | Fast and multilingual, but less battle-tested for Spanish punctuation. Not chosen. |
| Hosted APIs (OpenAI, Deepgram, AssemblyAI) | Not open-source, but the cheapest *effort*. Kept as an escape hatch behind the same interface. |

Model choice depends on hardware (see 2.2):

- GPU available → `large-v3` (best quality). ~10–20× realtime on an RTX 3060+.
- CPU only → `large-v3-turbo` with `compute_type="int8"`. Roughly 1–2× realtime
  on 8 cores; a 1-hour file takes ~30–60 minutes. Acceptable for batch use.
- If CPU turbo is too slow, drop to `medium` (int8).

Settings that matter for Spanish quality:

```python
model.transcribe(
    path,
    language="es",                      # never auto-detect; avoids Catalan/Portuguese drift
    beam_size=5,
    vad_filter=True,                    # skip silence, fewer hallucinations
    condition_on_previous_text=False,   # prevents repeated-phrase loops on long files
    initial_prompt="Hola, ¿cómo estás? Bien, gracias. Esta es una grabación en español.",
)
```

The `initial_prompt` nudges the model toward proper Spanish punctuation and
accents. We will tune it with real samples in phase 0.

### 2.2 Where it runs

This is the decision that shapes everything else. Three viable paths:

| Path | Cost | Speed | Ops burden | When to pick |
|---|---|---|---|---|
| **A. Home machine with a GPU + Cloudflare Tunnel** | $0/month | Fast | Machine must stay on; you own updates | You already have a desktop with an NVIDIA GPU (or an Apple Silicon Mac). |
| **B. Small VPS, CPU only** (Hetzner CX32 / CPX31 class, 4–8 vCPU, 8–16 GB) | ~€8–15/month | Slow (turbo int8) | Low; always on | No home hardware, low volume, patience is fine. |
| **C. Cheap VPS for the web app + serverless GPU for transcription** (Modal or RunPod Serverless) | VPS ~€5 + GPU pay-per-second (Modal has a monthly free credit) | Fast | Medium; two moving parts | No home GPU but you want fast turnaround. |

**Recommendation:** A if you have the hardware, otherwise C. B is the fallback
if you want the absolute simplest single-box setup and volume is low.

The code is written so the transcription step is a single function behind an
interface (`Transcriber.transcribe(path) -> Transcript`) with two
implementations: `LocalFasterWhisper` and `RemoteModal`. Switching paths is a
config change, not a rewrite.

### 2.3 Exposure and authentication

- **Cloudflare Tunnel** (`cloudflared`) exposes the app on a domain you own
  without opening router ports or exposing your home IP. Free. Gives HTTPS
  automatically. Works identically for a home box or a VPS.
- **App-level login**: single username + password, bcrypt-hashed, stored in
  `.env`. Session cookie lives 90 days so she logs in once per device and the
  browser remembers it. Login is rate-limited (5 failures → 15-minute lockout).
- **Optional second layer**: Cloudflare Access with email one-time-PIN. Free
  for up to 50 users. Adds an email code prompt every 30 days; only enable it
  if you're comfortable explaining that step to her. App-level login alone is
  the simpler experience.

### 2.4 Stack

- **Python 3.12 + FastAPI** — the model runs in Python, so keep one language.
- **Jinja2 + HTMX** — server-rendered pages, minimal JS, progress via polling.
  Fewer moving parts than a SPA and easy to keep accessible.
- **SQLite** — one file, one user, no DB server. Tables: `jobs`, `transcripts`.
- **Background worker** — a separate process that polls the `jobs` table and
  runs the model. No Redis/Celery for v1; SQLite as a queue is fine at this
  volume. Model is loaded once at worker start and kept warm.
- **ffmpeg** — normalize any input (mp3, m4a, wav, ogg/opus WhatsApp notes,
  aac, mp4/mov video) to 16 kHz mono WAV before transcription.
- **Docker Compose** — `web`, `worker`, `cloudflared`. One `docker compose up -d`.

---

## 3. User experience (what Mom sees)

Everything in Spanish. Large type, big buttons, works on a phone.

1. **`/login`** — "Usuario", "Contraseña", "Entrar". One-time per device.
2. **`/` (home)** — one big dashed box: *"Arrastra un archivo de audio aquí o
   toca para elegirlo"*. Below it, the list of her transcriptions, newest
   first, each showing: file name, date, duration, status chip
   (En cola / Transcribiendo… 42 % / Listo / Error).
3. **Upload** — progress bar; on completion the row appears at the top as
   "En cola". She can close the tab; it keeps going.
4. **`/t/{id}` (transcript)** — the full text in a readable column with
   paragraph breaks. Buttons: **Copiar todo**, **Descargar .txt**,
   **Descargar .docx**, **Descargar .srt** (subtitles with timestamps),
   **Escuchar** (embedded audio player, clicking a paragraph seeks the audio),
   **Eliminar**.
5. **Optional** — "Añadir a pantalla de inicio" as a PWA so it looks like an
   app icon on her phone.

Guardrails: max upload 2 GB, accepted-extension check, friendly error messages
("Este archivo no parece ser audio"), and audio files auto-deleted after 30
days (transcripts kept) to limit disk use and exposure.

---

## 4. Phases

### Phase 0 — Validate before building (½ day)

- [ ] Get 2–3 real recordings from Mom (the actual kind: voice notes,
      interviews, meetings, lectures?). Length and audio quality drive
      everything.
- [ ] Run `faster-whisper` on them from a script with `large-v3` and
      `large-v3-turbo`. Read the output with her. Decide the model.
- [ ] Decide hosting path (A / B / C) based on hardware you actually have.
- [ ] Buy or pick a domain (e.g. `transcripciones.<yourdomain>`), add it to
      Cloudflare (free plan).

**Exit criterion:** she looks at a transcript and says "sí, esto sirve".

### Phase 1 — Transcription core (1 day)

- [ ] `transcribe/` package: ffmpeg normalization, `Transcriber` interface,
      `LocalFasterWhisper` implementation, segment → paragraph grouping,
      exporters for `.txt`, `.srt`, `.docx`.
- [ ] CLI: `python -m transcribe audio.m4a` → writes outputs next to input.
- [ ] Unit tests for paragraph grouping and exporters (use a 10-second fixture).
- [ ] `Dockerfile` with ffmpeg + model weights pre-downloaded (so first run
      isn't a 3 GB surprise). Separate CPU and CUDA base image variants.

### Phase 2 — Web app (2–3 days)

- [ ] FastAPI app: login/logout, session middleware, rate limiting.
- [ ] Upload endpoint (streams to disk, creates `jobs` row).
- [ ] Worker process: claims jobs, updates `progress` as segments come in,
      writes transcript, handles failures with a readable error.
- [ ] Pages: home (list + upload), transcript view, downloads.
- [ ] HTMX polling for status/progress every 5 s while any job is active.
- [ ] Spanish copy throughout; mobile layout checked at 375 px width.
- [ ] `docker-compose.yml` for `web` + `worker` sharing a `data/` volume.
- [ ] If path C: `RemoteModal` transcriber + Modal function; worker calls it.

### Phase 3 — Deploy and expose (½ day)

- [ ] Install `cloudflared`, create tunnel, route `transcripciones.<domain>` →
      `http://web:8000`. Add as a Compose service so it restarts with the rest.
- [ ] `.env` with `APP_USERNAME`, `APP_PASSWORD_HASH`, `SECRET_KEY`,
      `MODEL_NAME`, `DEVICE`, `TUNNEL_TOKEN`. Never committed.
- [ ] Compose `restart: unless-stopped`; on a home box, make sure the machine
      doesn't sleep and Docker starts on boot.
- [ ] Nightly `data/` backup (transcripts + SQLite) — `restic` to Backblaze B2,
      or simply rsync to another disk. Verify a restore once.
- [ ] Basic health: `/healthz` endpoint + a free uptime check (UptimeRobot /
      Better Stack) that emails **you** if it goes down.

### Phase 4 — Hand-off to Mom (½ day, plus one sitting with her)

- [ ] Log her in on her phone and laptop; save the password in her browser.
- [ ] Add the PWA icon to her phone home screen.
- [ ] One-page printed guide in Spanish with screenshots: cómo subir, cómo
      esperar, cómo copiar/descargar. Keep it to five steps.
- [ ] Watch her do it once end-to-end without help. Fix whatever confused her
      before adding any features.

### Phase 5 — Optional improvements (only if she asks)

- Speaker labels ("Persona 1 / Persona 2") via WhisperX + pyannote (requires a
  free Hugging Face token to accept the pyannote license).
- Email her when a long transcript finishes.
- Automatic summary / bullet points via an LLM, shown above the full text.
- Shareable read-only link for a single transcript (expiring token).
- Record directly in the browser (MediaRecorder) instead of uploading a file.
- Search across all transcripts.

---

## 5. Repository layout (target)

```
transcripciones/
├── PLAN.md
├── README.md                 # setup + deploy instructions (for you)
├── docker-compose.yml
├── .env.example
├── docker/
│   ├── Dockerfile.cpu
│   └── Dockerfile.cuda
├── app/
│   ├── main.py               # FastAPI app, routes
│   ├── auth.py               # login, sessions, rate limit
│   ├── db.py                 # SQLite schema + helpers
│   ├── worker.py             # job loop, runs Transcriber
│   ├── templates/            # Jinja2, Spanish copy
│   └── static/               # CSS, htmx.min.js, PWA manifest
├── transcribe/
│   ├── __init__.py           # Transcriber interface
│   ├── local_faster_whisper.py
│   ├── remote_modal.py       # only if path C
│   ├── audio.py              # ffmpeg normalization
│   ├── paragraphs.py         # segments → readable paragraphs
│   └── export.py             # txt / srt / docx
├── modal_app.py              # only if path C
├── tests/
├── scripts/
│   ├── hash_password.py
│   └── backup.sh
└── docs/
    └── guia-para-mama.md     # the one-page Spanish guide
```

---

## 6. Rough cost

| Item | Path A (home GPU) | Path B (CPU VPS) | Path C (VPS + Modal) |
|---|---|---|---|
| Domain | ~$10/yr | ~$10/yr | ~$10/yr |
| Cloudflare (tunnel, DNS, HTTPS) | $0 | $0 | $0 |
| Compute | electricity | ~€8–15/mo | ~€5/mo + GPU seconds (often within free credit) |
| Backups (B2) | <$1/mo | <$1/mo | <$1/mo |

---

## 7. Open questions to answer in phase 0

1. What are the recordings? (voice notes, interviews, classes, sermons…)
   Typical length? How many per week?
2. Does she need to know *who* said what? → decides whether phase 5
   diarization is really phase 2.
3. What hardware do you have at home that can stay on 24/7? → decides A/B/C.
4. Which domain will this live under?
5. Where do the audio files come from — WhatsApp on her phone, a recorder app,
   a laptop? → decides whether phone-first upload matters most.

---

## 8. Suggested order of work for the next session

1. Answer the phase 0 questions; get two sample files.
2. Build phase 1 as a CLI and run it on the samples.
3. Only then start the web app.
