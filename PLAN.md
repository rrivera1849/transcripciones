# Transcripciones — Project Plan

A small, self-hosted web app that lets a non-technical user upload Spanish
courtroom recordings and get back accurate, speaker-labelled transcripts,
protected by a login and reachable from anywhere on the internet.

> Terminology: the task is **speech-to-text (STT / ASR)**, not TTS. TTS is the
> reverse direction (text → voice). Everything below is about STT.

---

## 1. What we know (decisions locked in)

| Question | Answer | Consequence |
|---|---|---|
| Hosting | Cheap VPS for the web app + **Modal** serverless GPU for transcription | Two components; transcription is an async remote job. |
| Content | **Court hearings**, recorded inside the courtroom | Long files (1–4 h), several speakers, far-field mics, legal vocabulary, sensitive data. |
| Speaker labels | **Wanted** | Diarization is core scope, not a stretch goal. |
| Source of files | Laptop | Desktop-first UI; large uploads must be reliable; phone support is nice-to-have. |
| Sample audio | None yet, coming soon | Build against public stand-in audio; re-tune when real samples arrive. |

---

## 2. Goals and non-goals

**Goals**

- One user (Mom) uploads a hearing recording and gets back a transcript with
  timestamps and speaker labels ("Hablante 1", "Hablante 2", …) that she can
  rename to "Juez", "Fiscal", "Testigo", etc.
- Spanish-only, high accuracy, good punctuation, correct legal terms.
- Zero technical steps for her: open a link, log in once, drag a file, wait,
  read / copy / download a Word document.
- Open-source models on infrastructure we control; no per-minute API vendor.
- Password-protected, HTTPS, audio deleted automatically after a retention
  window.

**Non-goals (v1)**

- Multiple accounts, public sign-up, billing.
- Real-time / live transcription during the hearing.
- Automatic identification of *who* a speaker is by name (she renames them).
- Certified / legally admissible transcripts. This is a working aid; the
  output must be reviewed by a human before any official use.

---

## 3. Architecture

```
 Mom's laptop                 VPS (Hetzner CX22-class, ~€4–8/mo)                 Modal (GPU, pay per second)
 ┌──────────┐   HTTPS   ┌─────────────────────────────────────┐              ┌──────────────────────────┐
 │ Browser  │ ────────► │ cloudflared ─► web (FastAPI+HTMX)   │              │ transcribe_hearing()     │
 │ upload   │           │                 │  SQLite + data/   │  spawn job   │  ffmpeg normalize        │
 │ 2 GB ok  │           │              worker ────────────────┼────────────► │  WhisperX large-v3 (es)  │
 └──────────┘           │                 ▲   signed URL      │              │  wav2vec2 es alignment   │
                        │                 │◄──────────────────┼── fetch ─────│  pyannote 3.1 diarize    │
                        │                 │   poll result     │              │  → JSON segments         │
                        └─────────────────┴───────────────────┘              └──────────────────────────┘
```

**Flow for one file**

1. Browser uploads in chunks to the VPS (`/upload`), which stores the file
   under `data/audio/{job_id}/` and inserts a `jobs` row (`queued`).
2. The worker picks up the job, mints a one-time signed download URL for the
   file, and calls `transcribe_hearing.spawn(url, options)` on Modal. It
   stores the Modal call id and marks the job `running`.
3. The Modal function downloads the audio, normalizes it with ffmpeg, runs
   WhisperX (transcribe → align → diarize) and returns JSON: segments with
   start, end, text, speaker, and word timings. It keeps nothing after return.
4. The worker polls the call id every 30 s, writes the result into
   `transcripts`, groups segments into speaker turns, and marks the job `done`
   (or `error` with a readable message).
5. Mom's page polls every 5 s via HTMX and flips to "Listo".

Why signed URL instead of passing bytes: hearing files can be multi-GB, and a
URL keeps the VPS as the only place the raw audio is stored. Why `spawn` +
poll instead of a blocking call: a 3-hour hearing can take 15–30 minutes;
the worker must survive restarts and never hold an HTTP connection that long.

---

## 4. Transcription pipeline (the Modal function)

**Engine: WhisperX** (faster-whisper under the hood, plus alignment and
diarization). Chosen over plain faster-whisper because speaker labels are
required, and WhisperX gives word-level timestamps that make the diarization
assignment much more accurate.

| Stage | Model | Notes |
|---|---|---|
| ASR | `large-v3` via faster-whisper, `compute_type="float16"` | Best Spanish accuracy. On GPU the speed difference vs. turbo is irrelevant. |
| Alignment | `wav2vec2` Spanish alignment model (WhisperX default for `es`) | Gives word-level timestamps. |
| Diarization | `pyannote/speaker-diarization-3.1` | Requires a Hugging Face token and accepting the model license once. Free. |
| Post-processing | ours | Merge consecutive same-speaker segments into turns; drop segments shorter than 0.3 s; normalize whitespace. |

Whisper settings for courtroom Spanish:

```python
asr_options = {
    "beam_size": 5,
    "condition_on_previous_text": False,   # avoid repeated-phrase loops on long files
    "initial_prompt": (
        "Transcripción de una vista judicial en español. "
        "Intervienen el juez, la fiscal, el abogado defensor, el acusado y los testigos. "
        "Señoría, con la venia, letrado, sentencia, prueba testifical, acusación, defensa."
    ),
}
language = "es"        # never auto-detect
vad = True             # skip silence, fewer hallucinations
min_speakers / max_speakers = None  # let pyannote decide; expose as an optional field later
```

The `initial_prompt` is our "custom vocabulary". It will be tuned per
jurisdiction once we know which country's courts these are (Spanish legal
vocabulary differs between Spain, Puerto Rico, Mexico, …). See open questions.

**Modal specifics**

- GPU: `A10G` (or `L4`). Expect roughly 10–20× realtime end-to-end including
  diarization; a 3-hour hearing ≈ 10–20 min of GPU ≈ $0.20–0.40.
- `timeout=6 * 3600` so long hearings never get killed; `retries=1`.
- Model weights baked into the image at build time (`large-v3`, alignment,
  pyannote) so cold starts are seconds, not minutes.
- Secrets: `HF_TOKEN` stored as a Modal secret, never in the repo.
- Modal's free monthly credit will likely cover Mom's usage entirely.

**Known limitations to tell Mom up front**

- Diarization is good, not perfect: overlapping speech, someone speaking from
  the back of the room, or two similar voices can get merged or split. The UI
  lets her rename and fix speakers rather than pretending it's always right.
- Inaudible passages come out as gaps or guesses. Timestamps let her jump to
  the audio and check.

---

## 5. Web app

**Stack:** Python 3.12, FastAPI, Jinja2 + HTMX (server-rendered, minimal JS),
SQLite (also used as the job queue), one background worker process, Docker
Compose with `web`, `worker`, `cloudflared`.

**Auth:** single username + bcrypt password from `.env`; signed session cookie
lasting 90 days; login rate-limited (5 failures → 15-minute lockout).
Cloudflare Tunnel provides HTTPS and hides the VPS. Cloudflare Access is
optional and skipped by default to keep her experience simple.

**Pages (all copy in Spanish):**

1. `/login` — Usuario / Contraseña / Entrar.
2. `/` — big dashed drop zone ("Arrastra la grabación aquí o haz clic para
   elegirla"), then the list of hearings newest-first: name, date, duration,
   status chip (Subiendo 63 % → En cola → Transcribiendo… → Listo / Error).
   She can rename a hearing ("Caso 2026-0142, vista 2").
3. `/t/{id}` — the transcript as a sequence of speaker turns:

   ```
   [00:12:05]  Juez        Se abre la sesión. Letrado, tiene la palabra.
   [00:12:11]  Abogado     Con la venia, señoría. …
   ```

   - **Speaker sidebar**: each detected speaker with a colour and an editable
     name. Renaming "Hablante 2" → "Fiscal" updates every turn instantly and is
     saved. A "Fusionar con…" option merges two speakers the model split.
   - **Audio player** pinned at the bottom; clicking a turn seeks to it; the
     current turn highlights while playing.
   - **Inline edit**: click a turn to correct a word. Edits are saved; the
     original is kept for undo.
   - **Buttons**: Copiar todo · Descargar .docx · Descargar .txt ·
     Descargar .srt · Eliminar.
4. `/settings` (for you, not her): retention days, min/max speakers default.

**Exports**

- `.docx` — the primary deliverable: title block (name, date, duration),
  then one paragraph per turn with bold speaker name and grey timestamp.
  Built with `python-docx`.
- `.txt` — same content, plain.
- `.srt` — subtitles with speaker prefix, useful for playing alongside video.

**Uploads from a laptop**

- Chunked upload (5 MB chunks, retried) so a flaky Wi-Fi drop doesn't restart a
  2 GB upload. Progress bar with percentage. Accepts mp3, m4a, aac, wav, ogg,
  opus, flac, wma, mp4, mov, m4v; ffmpeg handles the rest.
- Max size 4 GB. Friendly rejection for non-audio files.

**Data handling (court audio is sensitive)**

- Audio deleted from the VPS 30 days after transcription (configurable);
  transcripts kept until she deletes them.
- Modal keeps nothing after the function returns; the signed URL expires in
  6 hours and is single-use.
- Nightly encrypted backup of `data/` (SQLite + transcripts, not audio) with
  `restic` to Backblaze B2 or Cloudflare R2.
- No third-party LLM summaries in v1. If we add summaries later, we decide
  explicitly whether sending hearing text to an API is acceptable.

---

## 6. Phases

### Phase 0 — Set up accounts and a stand-in dataset (½ day)

- [ ] Modal account; install CLI; `modal token new`.
- [ ] Hugging Face account; accept licenses for
      `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0`;
      create a read token; store it as a Modal secret.
- [ ] VPS (Hetzner CX22 or similar, Ubuntu 24.04, Docker installed).
- [ ] Domain in Cloudflare; create a tunnel, note the token.
- [ ] Stand-in audio until real samples arrive: a long public Spanish
      multi-speaker recording (a parliamentary session or a public court
      broadcast works well — several speakers, formal register, room mics).
      Keep 2–3 files of 20–60 min in `samples/` (git-ignored).

### Phase 1 — Modal transcription function (1 day)

- [ ] `modal_app.py`: image with ffmpeg, WhisperX, pyannote, weights
      pre-downloaded; `transcribe_hearing(url, options) -> dict`.
- [ ] `transcribe/` package (shared, runs inside Modal and in tests):
      normalization, post-processing into speaker turns, exporters
      (`txt`, `srt`, `docx`).
- [ ] Local dev path: `python -m transcribe path.mp3 --local` runs
      faster-whisper on CPU with `small` for fast iteration on the
      post-processing and exporters without a GPU.
- [ ] CLI: `python -m transcribe path.mp3 --modal` runs the real thing and
      writes `path.docx / .txt / .srt / .json`.
- [ ] Unit tests for turn grouping, speaker renaming/merging, and exporters
      using a fixture JSON.
- [ ] Measure: wall time and cost on the stand-in files; read the output for
      punctuation and legal-term errors; adjust `initial_prompt`.

**Exit criterion:** a 1-hour stand-in file comes back in under 10 minutes with
readable, correctly-punctuated Spanish and plausible speaker turns.

### Phase 2 — Web app (2–3 days)

- [ ] FastAPI app: login/logout, sessions, rate limiting, CSRF on forms.
- [ ] Chunked upload endpoint; `jobs` table; signed download URL endpoint.
- [ ] Worker: claim job → `spawn` on Modal → poll → store result; resilient to
      restarts (re-attach to in-flight Modal calls on boot).
- [ ] Home page, transcript page, speaker sidebar (rename, merge), inline
      edit, audio player with seek, exports.
- [ ] HTMX polling for status; Spanish copy; layout checked at laptop width
      and at 375 px.
- [ ] `docker-compose.yml` with `web`, `worker`, `cloudflared`; shared
      `data/` volume; `restart: unless-stopped`.

### Phase 3 — Deploy (½ day)

- [ ] `.env` on the VPS: `APP_USERNAME`, `APP_PASSWORD_HASH`, `SECRET_KEY`,
      `MODAL_TOKEN_ID/SECRET`, `TUNNEL_TOKEN`, `PUBLIC_BASE_URL`,
      `RETENTION_DAYS`. Never committed; `.env.example` documents them.
- [ ] `docker compose up -d`; verify the tunnel; upload a stand-in file
      end-to-end through the public URL.
- [ ] Retention cron (delete audio > N days), backup cron, `/healthz` +
      free uptime monitor that emails you.
- [ ] Unattended OS security updates on the VPS.

### Phase 4 — Real samples and hand-off (½ day + one sitting with Mom)

- [ ] Run the first real hearing recordings. Compare against the stand-ins:
      audio quality, number of speakers, vocabulary. Tune `initial_prompt`
      and the min/max speaker defaults.
- [ ] Log her in on her laptop; save the password in her browser; bookmark.
- [ ] One-page printed guide in Spanish with screenshots (`docs/guia.md`):
      subir, esperar, renombrar hablantes, descargar Word. Five steps max.
- [ ] Watch her do one hearing end-to-end without help. Fix what confused her
      before adding features.

### Phase 5 — Later, only if she asks

- Search across all transcripts.
- Per-case folders and a "same speakers as last hearing" hint.
- Email when a long transcript finishes.
- Summary / key points (requires an explicit decision on sending court text
  to an external LLM, or running a local one on Modal).
- Record directly in the browser.
- Export with line numbers / legal transcript formatting if she needs a
  specific layout.

---

## 7. Repository layout (target)

```
transcripciones/
├── PLAN.md
├── README.md                 # setup + deploy instructions (for you)
├── docker-compose.yml
├── .env.example
├── Dockerfile                # web + worker image (CPU only, no models)
├── modal_app.py              # GPU function: WhisperX + pyannote
├── app/
│   ├── main.py               # FastAPI routes
│   ├── auth.py               # login, sessions, rate limit
│   ├── db.py                 # SQLite schema + helpers
│   ├── uploads.py            # chunked upload handling
│   ├── worker.py             # job loop: spawn on Modal, poll, store
│   ├── templates/            # Jinja2, Spanish copy
│   └── static/               # CSS, htmx.min.js, player JS
├── transcribe/
│   ├── __init__.py           # Transcriber interface + Transcript dataclasses
│   ├── whisperx_pipeline.py  # runs inside Modal
│   ├── local_cpu.py          # small-model dev path
│   ├── audio.py              # ffmpeg normalization
│   ├── turns.py              # segments → speaker turns; rename/merge
│   └── export.py             # txt / srt / docx
├── tests/
├── scripts/
│   ├── hash_password.py
│   ├── retention.sh
│   └── backup.sh
├── samples/                  # git-ignored stand-in audio
└── docs/
    └── guia.md               # the one-page Spanish guide for Mom
```

---

## 8. Rough monthly cost

| Item | Cost |
|---|---|
| Domain | ~$10/yr |
| Cloudflare tunnel, DNS, HTTPS | $0 |
| VPS (Hetzner CX22-class) | ~€4–8 |
| Modal GPU | ~$0.20–0.40 per 3-hour hearing; free credit likely covers it |
| Backups (B2/R2) | <$1 |

---

## 9. Open questions

1. **Which country's courts?** Drives legal vocabulary in the prompt and the
   speaker role names offered as rename suggestions (Juez / Jueza, Fiscal,
   Letrado vs. Licenciado, Ministerio Público vs. Fiscalía, …).
2. **Typical length and how many per week?** Confirms the VPS size and
   whether Modal's free credit covers it.
3. **What recording device / format?** A courtroom system export, a phone on
   the table, a handheld recorder? Affects audio quality expectations and
   whether stereo channels carry different mics (worth exploiting if so).
4. **Does she need a specific transcript layout** for her work (line numbers,
   Q/A format, header block)? Decides the `.docx` template in phase 2 vs. 5.
5. **Who else may see these transcripts?** If anyone besides her, we add a
   second account and per-transcript sharing; otherwise single-user stays.

---

## 10. Next session

1. Phase 0 accounts (Modal, Hugging Face, VPS, Cloudflare) — you do these.
2. I start phase 1: the Modal function, the `transcribe` package, exporters,
   and tests, using public Spanish audio as stand-in.
3. When real samples arrive, we run them before touching the web app.
