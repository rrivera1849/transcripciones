# Plan: transcription quality fix

Status: **implemented 2026-11-15; needs `modal deploy` plus the normal deploy.**
Evidence is in `docs/FINDINGS.md`
(2026-11-15 entry): on 12 clips from a real hearing, removing the fixed prompt
("version B") eliminated prompt sentences leaking into transcripts, produced
13% more words and 21% less missed speech than the current setup. No setting
fixed the misheard legal words, so those get a corrections list.

## Goals

1. Transcribe with version B: no prompt at all.
2. Fix the recurring misheard words automatically, visibly and reversibly.
3. The role names from her email in the speaker list.

A "Volver a transcribir" button was considered and dropped: to try the new
setup, the hearing is uploaded again.

## Decisions

| Question | Decision |
|---|---|
| Prompt | None. The plan first kept the user's names as a prompt; tested on the same clips, names alone cost 20% of the words and 50% more missed speech, so Whisper gets no prompt and the "Nombres y lugares" field is gone from the upload form (the column stays for old jobs). |
| Where corrections run | On the app host, when a transcript arrives. No Modal deploy needed for rule changes. |

### Decisions taken on defaults (revisit with her)

1. **Role list** (from her email). **Replaced "Lcdo./Lcda. de la defensa" with
   "Abogado parte demandante", "Abogada parte demandante", "Abogado parte
   demandada", "Abogada parte demandada"**, matching the Juez/Jueza pattern.
   Keep the defensa entries only if she also does criminal hearings.
2. **Forms of address.** **Leave "Vuestro Honor" / "Su Señoría" as Whisper
   writes them** until she says which capitalization she uses.

## Work items

### 1. Pipeline: version B (needs `modal deploy`)

- `transcribe/prompt.py`: `INITIAL_PROMPT` and the names prompt removed.
- `transcribe/whisperx_pipeline.py` and `transcribe/local_cpu.py`:
  `initial_prompt=None`; the `vocabulary` option is gone end to end (form,
  upload route, worker, Modal call).
- Every transcript records its setup: `Transcript.pipeline = "sin-prompt-2026-11"`.
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

### 3. Roles (per open decision 1)

- `transcribe/prompt.py` `ROLE_SUGGESTIONS` and `transcribe/roles.py` display
  names; add cues "parte demandante" / "parte demandada" so suggestions can
  name them.

### 4. Verification (done)

- 26 correction tests: every rule, plus text that must stay untouched
  ("se titula Contrato", "titular", "suscrito ante mí"); words stay in sync
  with text; marks survive storage. App test: a finished job is saved raw, then
  corrected as one Historial entry by "La Transcriptora"; Deshacer brings back
  the raw text; exports carry the corrected text. Role test for both sides.
  Full suite: 79 passed; ruff clean.
- The 12 clips through the final code path give exactly version B's output;
  after corrections: no "güey", no "exilio", no invented lines (FINDINGS).
- Browser: marks, tooltips, toggle in normal and high-contrast mode,
  click-to-listen, Historial entry, role menu, upload without the names field.

### 5. Rollout

1. From the laptop: `uv run modal deploy modal_app.py` (no-prompt change; until
   then new uploads still use the old prompt, but corrections already apply).
2. On the VPS: `./scripts/deploy.sh`.
3. Upload one of the hearings again; she reviews it against her corrected
   version and reports what is still wrong. New recurring errors become rules.

## Later

- Offer her own find-and-replace choices as new correction rules.
- Apply corrections to existing transcripts without uploading again.
- A "Volver a transcribir" button (dropped for now).
- The skip at 1:31:02 of the September hearing survived every setup; revisit
  once she says what was said there.
