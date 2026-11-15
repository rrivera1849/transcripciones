# Plan: transcription quality fix and "Volver a transcribir"

Status: **planned, not started.** Evidence is in `docs/FINDINGS.md`
(2026-11-15 entry): on 12 clips from a real hearing, removing the fixed prompt
("version B") eliminated prompt sentences leaking into transcripts, produced
13% more words and 21% less missed speech than the current setup. No setting
fixed the misheard legal words, so those get a corrections list.

## Goals

1. Transcribe with version B: no fixed prompt; only the names the user types.
2. Fix the recurring misheard words automatically, visibly and reversibly.
3. A "Volver a transcribir" button, so existing hearings can be redone with the
   new setup and reviewed by the person who uploaded them.

## Decisions

| Question | Decision |
|---|---|
| Prompt | No fixed paragraph. If "Nombres y lugares" is filled, the prompt is just those names. Empty field = no prompt. |
| Where corrections run | On the app host, when a transcript arrives. No Modal deploy needed for rule changes. |
| Re-transcribe target | A **new** transcript next to the original. The original, with all her edits, stays untouched until she deletes it. |
| Re-transcribe settings | Same speaker count and same names as the original job. Owner is the original uploader, so it appears as hers and the "done" email goes to her. |

### Open decisions (defaults in bold)

1. **Speaker count meaning.** Today "¿Cuántas personas hablan?" is sent as a
   *minimum* (`min_speakers`): diarization may find more voices. Re-transcribe
   reuses the same value with the **same meaning**. Alternative: send it as the
   exact count (min = max), which forces unheard voices (alguacil, secretaria)
   into someone else's label.
2. **Role list** (from her email). **Replace "Lcdo./Lcda. de la defensa" with
   "Abogado parte demandante", "Abogada parte demandante", "Abogado parte
   demandada", "Abogada parte demandada"**, matching the Juez/Jueza pattern.
   Keep the defensa entries only if she also does criminal hearings.
3. **Forms of address.** **Leave "Vuestro Honor" / "Su Señoría" as Whisper
   writes them** until she says which capitalization she uses.

## Work items

### 1. Pipeline: version B (needs `modal deploy`)

- `transcribe/prompt.py`: delete `INITIAL_PROMPT`. `build_prompt(vocabulary)`
  returns `None` when empty, else the names joined with ", " and a final period.
- `transcribe/whisperx_pipeline.py`: `initial_prompt` may be `None`;
  `_set_prompt` already swaps in place.
- `transcribe/local_cpu.py`: same prompt handling, so dev runs match.
- Record the setup on each transcript (`Transcript.pipeline = "b-2026-11"`) so
  the app can tell old transcripts from new ones.
- Not done: version C (shorter chunks, looser VAD) and D (sequential retry);
  both lost to B in the test.

### 2. Corrections list (app host only)

New `transcribe/corrections.py` with the rules as data, applied to a
`Transcript` before it is saved. Four tiers:

| Tier | Effect | Rules |
|---|---|---|
| 1. Always | Replace | güey / guey / wey → juez; ex-civil / ex civil → exhibit; exhibi → exhibit; inmitida / inmitido → admitida / admitido; paudal relicto → caudal relicto |
| 2. In context | Replace | "exilio" + number (or "exilio número N") → exhibit; "como exilio" → "como exhibit"; the sentence "Se titula." alone → "Se estipula." |
| 3. Suggest | Highlight only | titula/titulan elsewhere (¿estipula?); "hemos sometido" (¿lo damos por sometido?); "objeto de este descanso" (¿desahucio?); "contrato de excepción/sesión" (¿cesión?); "el exilio" without a number (¿exhibit?) |
| 4. Invented lines | Remove whole segment | "Gracias por ver el video."; segments made only of "..."; "Subtítulos realizados por la comunidad de Amara.org"; "Suscríbete al canal" |

Details:
- Case is preserved ("Güey" → "Juez"). Matching is on whole words only.
- Rules work on the aligned **word list** and rebuild the segment text from it,
  so doubtful-word highlighting and click-to-listen keep working. A changed word
  carries `fixed_from`; a suggested one carries `suggest`.
- In the worker: save the raw transcript, then apply corrections as one edit
  with action "correcciones automáticas". It shows in Historial and Deshacer
  restores the raw text.
- UI: corrected words get a subtle mark with the tooltip "Corregido
  automáticamente: güey → juez"; suggestions use the doubtful-word style with
  "¿Quiso decir «estipula»?". Both follow the existing "Marcar dudosas" toggle,
  relabelled "Marcar dudosas y correcciones".
- Exports (Word, .txt, .srt) contain the corrected text without marks.

### 3. "Volver a transcribir" button

- Shown on the transcript page when the job is `done` and its audio still
  exists. When the audio was already deleted (retention), show a short note
  instead of the button.
- `POST /t/{id}/retranscribir`: confirm dialog in Spanish ("Se creará una
  transcripción nueva con el mismo audio. La actual no se borra."), then:
  - copy the stored audio into a new job folder (copy, not share: retention
    deletes each job's folder independently);
  - new job: title "<título> (nueva transcripción)", same `min_speakers`,
    same `vocabulary`, `created_by` = original uploader, new column
    `source_job_id` = original id (migration);
  - refuse if a re-transcription of the same job is already queued or running,
    so a double click can't start two;
  - redirect to the list, where it shows "En cola" like any upload.
- Speaker names are **not** copied: diarization numbers voices differently each
  run. The role suggestions ("¿Es Juez?…") cover most of it.
- Audio quality: the stored audio is the AAC 96 kbps playback copy (the
  original is deleted after the first transcription). Verify it gives the same
  results as the original before relying on it (step 5).

### 4. Roles (per open decision 2)

- `transcribe/prompt.py` `ROLE_SUGGESTIONS` and `transcribe/roles.py` display
  names; add cues "parte demandante" / "parte demandada" so suggestions can
  name them.

### 5. Verification before deploy

- Unit tests: every rule in tiers 1–4, plus negatives that must stay untouched
  ("documento que se titula Contrato", "titular", "el exilio político",
  "suscrito ante mí"); word list and text stay in sync; Deshacer restores raw.
- App tests: button visibility (done / running / audio deleted); route copies
  audio, speaker count, names, owner and sets `source_job_id`; duplicate click
  refused; email goes to the original uploader.
- Re-run the 12 test clips through the final code path on CPU, both with no
  names and with a names list, and compare against version B's numbers.
- Convert two clips to AAC 96 kbps and check the output matches the FLAC run.
- Browser check of the button, the marks and the toggle.
- `uv run pytest -q -W ignore` and `uv run ruff check .` clean.

### 6. Rollout

1. From the laptop: `uv run modal deploy modal_app.py` (prompt change).
2. On the VPS: `./scripts/deploy.sh`.
3. Logged in as her, press "Volver a transcribir" on the September 22 and
   December 1 hearings. **Deadline:** audio is deleted 30 days after
   transcription (`RETENTION_DAYS`); both were transcribed on 2026-11-14, so
   about 2026-12-14 unless the VPS `.env` sets a different value.
4. She reviews the new versions against her corrected ones and reports what is
   still wrong; new recurring errors become rules.

## Later

- Offer her own find-and-replace choices as new correction rules.
- Apply corrections to existing transcripts without re-transcribing.
- The skip at 1:31:02 of the September hearing survived every setup; revisit
  once she says what was said there.
