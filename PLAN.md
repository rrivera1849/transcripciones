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
| Jurisdiction | **Puerto Rico** courts | Puerto Rican legal Spanish in the prompt and role names; expect some English code-switching. |
| Recording device | Unknown | Accept anything; downmix to mono by default; revisit if the real files turn out to be multi-channel. |
| Transcript layout | None required yet | Ship a clean default `.docx`; a specific legal layout waits for a real request. |
| Who sees transcripts | Mom + possibly one other person | Two accounts sharing one workspace; no per-transcript permissions. |
| Build order | **Local first** | The app runs on a laptop at localhost with Modal doing the GPU work. VPS, domain and Cloudflare come only in phase 3. |

---

## 2. Goals and non-goals

**Goals**

- One user (Mom) uploads a hearing recording and gets back a transcript with
  timestamps and speaker labels ("Hablante 1", "Hablante 2", …) that she can
  rename to "Jueza", "Fiscal", "Lcdo. de la defensa", "Testigo", etc.
- Spanish-only, high accuracy, good punctuation, correct legal terms.
- Zero technical steps for her: open a link, log in once, drag a file, wait,
  read / copy / download a Word document.
- Open-source models on infrastructure we control; no per-minute API vendor.
- Password-protected, HTTPS, audio deleted automatically after a retention
  window.

**Non-goals (v1)**

- Public sign-up, billing, per-transcript permissions. (Two fixed accounts
  sharing one workspace are in scope; see §5.)
- Real-time / live transcription during the hearing.
- Automatic identification of *who* a speaker is by name (she renames them).
- Certified / legally admissible transcripts. This is a working aid; the
  output must be reviewed by a human before any official use.

---

## 3. Architecture

```
 Browser                      App host (laptop now, VPS later)                 Modal (GPU, pay per second)
 ┌──────────┐   HTTP(S)  ┌─────────────────────────────────────┐              ┌──────────────────────────┐
 │ upload   │ ─────────► │ web (FastAPI+HTMX)                  │              │ Transcriber.run()        │
 │ 2 GB ok  │            │   │  SQLite + data/                 │  1. put file │  reads from Volume       │
 └──────────┘            │ worker ─────────────────────────────┼────────────► │  ffmpeg normalize        │
                         │   │         Modal Volume "audio-in" │  2. spawn    │  WhisperX large-v3 (es)  │
                         │   │◄────────────────────────────────┼── 3. result ─│  wav2vec2 es alignment   │
                         │   │         poll                    │              │  pyannote 3.1 diarize    │
                         └───┴─────────────────────────────────┘              │  → JSON, deletes input   │
                                                                              └──────────────────────────┘
 In phase 3 the same stack moves to a VPS and a `cloudflared` container is
 added in front of `web`. Nothing else changes.
```

**Flow for one file**

1. Browser uploads in chunks (`/upload`); the app stores the file under
   `data/audio/{job_id}/` and inserts a `jobs` row (`queued`).
2. The worker picks up the job and streams the file into a Modal **Volume**
   (`audio-in`) under `{job_id}/input.<ext>`, then calls
   `Transcriber.run.spawn(job_id, path, options)`. It stores the Modal call id
   and marks the job `running`.
3. The Modal function reads the file from the mounted volume, normalizes it
   with ffmpeg, runs WhisperX (transcribe → align → diarize), deletes its
   input from the volume, and returns JSON: segments with start, end, text,
   speaker, and word timings.
4. The worker polls the call id every 30 s, writes the result into
   `transcripts`, groups segments into speaker turns, and marks the job `done`
   (or `error` with a readable message).
5. The page polls every 5 s via HTMX and flips to "Listo".

Why a Volume instead of a signed URL: it works identically from a laptop on
localhost and from a VPS, never requires an inbound endpoint, and has no
request-size ceiling for multi-GB hearings. Why `spawn` + poll instead of a
blocking call: a 3-hour hearing can take 15–30 minutes; the worker must
survive restarts and never hold an HTTP connection that long.

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
| Diarization | `pyannote/speaker-diarization-community-1` | pyannote's current pipeline (pyannote.audio 4). Requires a Hugging Face token and accepting the model licenses once. Free. |
| Post-processing | ours | Merge consecutive same-speaker segments into turns; drop segments shorter than 0.3 s; normalize whitespace. |

Whisper settings for courtroom Spanish:

```python
asr_options = {
    "beam_size": 5,
    "condition_on_previous_text": False,   # avoid repeated-phrase loops on long files
    "initial_prompt": (
        "Vista en el Tribunal de Primera Instancia de Puerto Rico. "
        "Intervienen la Honorable Jueza, el Fiscal del Ministerio Público, "
        "el Licenciado de la defensa, el acusado, los testigos, el perito y el alguacil. "
        "Con la venia del Tribunal. Objeción. Ha lugar. No ha lugar. "
        "Se declara con lugar la moción. Que conste en récord."
    ),
}
language = "es"        # never auto-detect
vad = True             # skip silence, fewer hallucinations
min_speakers / max_speakers = None  # let pyannote decide; expose as an optional field later
```

The `initial_prompt` is our "custom vocabulary", written in Puerto Rican
legal Spanish: *Licenciado/a* rather than *letrado*, *Ministerio Público* and
*Fiscalía*, *Tribunal de Primera Instancia*, *Ha lugar / No ha lugar*,
*alguacil*, *récord*. It also nudges the model toward the formal register and
frequent short exchanges ("Objeción." "Ha lugar.") typical of a hearing.

**Puerto Rico specifics to watch on real samples**

- Code-switching: English words and phrases ("el discovery", "hearsay",
  "probable cause") appear in PR court speech. With `language="es"` fixed,
  Whisper usually keeps them as English words, but it sometimes translates
  or garbles them. We keep `language="es"` (auto-detect is worse) and check
  the first real transcripts for this specifically.
- Names and case numbers: Whisper spells Spanish surnames well but can drop
  accents. The inline editor covers the rest.
- Suggested speaker roles offered in the rename menu: Juez / Jueza, Fiscal,
  Lcdo. / Lcda. de la defensa, Acusado / Acusada, Testigo, Perito, Alguacil,
  Intérprete, Secretaria. Free text is always allowed.

**Recording device is unknown.** The pipeline downmixes everything to 16 kHz
mono. If the real files turn out to be multi-channel with one mic per party
(some courtroom systems do this), we split channels and diarize per channel
instead, which is far more accurate. This is a phase 4 check.

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
SQLite (also used as the job queue), one background worker process. Runs
locally with `uv run` / `uvicorn` on `localhost:8000`; Docker Compose
(`web`, `worker`, and in phase 3 `cloudflared`) for deployment.

**Auth:** a `users` table with up to a handful of accounts (Mom, and one other
person), each with their own username and bcrypt password; created by you
with `scripts/add_user.py`, no sign-up page. Everyone sees the same shared
list of hearings (one workspace); each hearing records who uploaded it and
who last edited it. Signed session cookie lasting 90 days; login rate-limited
(5 failures → 15-minute lockout). In phase 3 Cloudflare Tunnel provides
HTTPS and hides the VPS. Cloudflare Access is optional and skipped by default
to keep her experience simple.

Sharing one workspace is deliberately simpler than per-transcript permissions.
If the second person should only see *some* hearings, that becomes a phase 5
item ("compartir con…").

**Pages (all copy in Spanish):**

1. `/login` — Usuario / Contraseña / Entrar.
2. `/` — big dashed drop zone ("Arrastra la grabación aquí o haz clic para
   elegirla"), then the list of hearings newest-first: name, date, duration,
   status chip (Subiendo 63 % → En cola → Transcribiendo… → Listo / Error).
   She can rename a hearing ("Caso 2026-0142, vista 2"). The upload form
   asks "¿Cuántas personas hablan?" (default 3); it is passed to pyannote as
   `min_speakers` and matters a lot on courtroom audio (see FINDINGS). A
   second optional field, "Nombres y lugares" (parties, town, key terms),
   is appended to the Whisper prompt as per-job vocabulary.
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
  Built with `python-docx`. No specific legal layout is required yet, so this
  clean default ships in phase 2; a formal transcript layout (numbered lines,
  caption header, certification page) is a phase 5 item if she asks.
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
- Modal keeps nothing after the function returns: the input is deleted from
  the volume at the end of the run, and a daily sweep removes anything older
  than 24 h in case a run crashed.
- Nightly encrypted backup of `data/` (SQLite + transcripts, not audio) with
  `restic` to Backblaze B2 or Cloudflare R2.
- No third-party LLM summaries in v1. If we add summaries later, we decide
  explicitly whether sending hearing text to an API is acceptable.

---

## 6. Phases

### Phase 0 — Accounts and a stand-in dataset (½ day)

Local-first: only Modal and Hugging Face are needed to start. See
`docs/SETUP.md` for click-by-click steps.

- [ ] Modal account; install CLI; `modal setup`; billing method on file.
- [ ] Hugging Face account; accept licenses for
      `pyannote/speaker-diarization-community-1`, `pyannote/speaker-diarization-3.1`
      and `pyannote/segmentation-3.0`;
      create a read token; store it as the Modal secret `huggingface`.
- [ ] Stand-in audio until real samples arrive: 2–3 public Puerto Rican
      multi-speaker recordings in a formal register (Legislatura de Puerto
      Rico sessions, Tribunal Supremo de PR oral arguments), 20–60 min each,
      kept in `samples/` (git-ignored).
- [ ] (Deferred to phase 3) VPS, domain, Cloudflare tunnel.

### Phase 1 — Modal transcription function (1 day)

- [ ] `modal_app.py`: image with ffmpeg, WhisperX, pyannote, weights
      pre-downloaded; Volume `audio-in`; `Transcriber.run(job_id, path, options)
      -> dict`; daily sweep of stale inputs.
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

**Status 2026-09-18:** pipeline validated on CPU with the first real hearing
(see `docs/FINDINGS.md`). GPU run on the full file done: 81 s for 26 min,
4 speakers, usable draft. Transcript quality good; diarization needs a
speaker-count hint and manual correction in the UI. **Phase 1 exit criterion
met.**

### Phase 2 — Web app (2–3 days)

- [ ] FastAPI app: `users` table, login/logout, sessions, rate limiting,
      CSRF on forms.
- [ ] Chunked upload endpoint; `jobs` table.
- [ ] Worker: claim job → upload to Volume → `spawn` on Modal → poll → store
      result; resilient to restarts (re-attach to in-flight Modal calls on
      boot).
- [ ] Home page, transcript page, speaker sidebar (rename, merge), inline
      edit, audio player with seek, exports.
- [ ] HTMX polling for status; Spanish copy; layout checked at laptop width
      and at 375 px.
- [ ] Runs end-to-end on a laptop: `uv run app` at `localhost:8000`, Modal
      doing the GPU work, transcripts stored in local `data/`.
- [ ] `docker-compose.yml` with `web` and `worker`; shared `data/` volume;
      `restart: unless-stopped`. `cloudflared` is added in phase 3.

**Exit criterion:** you upload a stand-in file at `localhost:8000`, wait, and
download a speaker-labelled `.docx`, all from your laptop.

### Phase 3 — Deploy (½ day)

Now the infrastructure: VPS, domain, Cloudflare tunnel (`docs/SETUP.md`
§3–4). The app code does not change; only `.env` and one Compose service.

- [ ] Add the `cloudflared` service to `docker-compose.yml`.
- [ ] `.env` on the VPS: `SECRET_KEY`,
      `MODAL_TOKEN_ID/SECRET`, `TUNNEL_TOKEN`, `PUBLIC_BASE_URL`,
      `RETENTION_DAYS`. Never committed; `.env.example` documents them.
- [ ] `docker compose up -d`; create the two accounts with
      `scripts/add_user.py`; verify the tunnel; upload a stand-in file
      end-to-end through the public URL.
- [ ] Retention cron (delete audio > N days), backup cron, `/healthz` +
      free uptime monitor that emails you.
- [ ] Unattended OS security updates on the VPS.

### Phase 4 — Real samples and hand-off (½ day + one sitting with Mom)

- [ ] Run the first real hearing recordings. Compare against the stand-ins:
      audio quality, mono vs. multi-channel, number of speakers, vocabulary,
      how English code-switching came out. Tune `initial_prompt` and the
      min/max speaker defaults.
- [ ] Log her in on her laptop; save the password in her browser; bookmark.
      Same for the second person, if they need access from day one.
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
│   ├── add_user.py
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

1. **Typical length and how many per week?** Confirms the VPS size and
   whether Modal's free credit covers it.
2. **Recording device / format** — still unknown. Resolved when the first
   real file arrives (phase 4); the pipeline handles either case.
3. **Does the second person need access from day one**, and should they see
   everything or only selected hearings? Default: everything, shared
   workspace.
4. **Transcript layout** — none required now. Revisit only if she asks for a
   formal court-transcript format.

Answered so far: Puerto Rico courts; files come from a laptop; speaker labels
required; hosting is VPS + Modal.

---

## 10. Next session

1. Phase 0 (Modal, Hugging Face, stand-in audio links) — you.
2. Phase 1 — Claude: the Modal function, the `transcribe` package,
   exporters, tests; run on the stand-in audio and report timing, cost, and
   quality.
3. Phase 2 — the local web app. You use it on your laptop.
4. Real samples arrive → run them, tune.
5. Only then phase 3: VPS + Cloudflare.
