# Findings log

Running notes from real runs. Newest first.

## 2026-09-19 — CUDA out-of-memory on the second job in a warm container

Second hearing through the web app failed in WhisperX ASR with "CUDA failed
with error out of memory" on an A10G (24 GB). Root cause in our code: a job
with a different `vocabulary` discarded the Whisper pipeline and loaded a
second copy onto the GPU while the first was still resident; nothing ever
called `torch.cuda.empty_cache()`; and batch size 16 had no fallback.

Fixes (`transcribe/whisperx_pipeline.py`): the prompt is now swapped in
place on the pipeline's options dataclass (no reload, ever); the CUDA cache
is released at job start and between ASR, alignment and diarization; ASR
retries on OOM with the batch halved down to 2; default batch is 8; GPU
memory is logged at start and end of each job. Verified against the real
whisperx classes on CPU. Requires `modal deploy`.

## 2026-09-18 — Phase 2 web app, first browser run

Built the FastAPI + HTMX app and drove it headless with Playwright against
the real 2-minute clip (CPU backend) and the GPU transcript of the full
hearing (seeded). Everything in the phase-2 checklist works: login and
lockout, chunked upload with progress, queue → worker → transcript, speaker
rename that propagates to every turn, per-turn reassignment, merge, inline
text edit, Word/txt/srt downloads, audio with HTTP range requests, delete.

Notes:

- Headless Chromium here cannot decode AAC, so the player shows 0:00 in the
  screenshots; real Chrome, Edge and Safari play m4a natively. Worth a check
  on Mom's laptop; if her browser balks, the worker can add an mp3 copy.
- The speaker sidebar is sticky on desktop; on phone widths it must be
  static or it covers the text (fixed).
- The CPU backend has no diarization, so a 2-minute clip becomes two long
  paragraphs; expected, and not representative of the Modal path.

## 2026-09-18 — First GPU run (Modal A10G, large-v3, full 26-minute hearing)

Run from the laptop with `--min-speakers 3`. Outputs reviewed in full.

**Speed**: transcribe 33 s, align 16 s, diarize 32 s, total 81 s for 1568 s
of audio (≈19× realtime). A 3-hour hearing ≈ 10 min ≈ $0.20 on an A10G.

**Transcript quality (large-v3)**: clearly better than turbo on CPU. Legal
register, dates, amounts, the oath and most names are right. Errors seen,
now folded into the prompt or the per-job vocabulary:

| Heard | Should be | Fix |
|---|---|---|
| "en nuestra licitación" / "a un saludo de la ley 121" | "ante nuestra consideración" / "al amparo de la Ley 121" | phrase added to prompt |
| "cuatro puertas y media" (later correctly "cuerdas") | "cuerdas" (PR land unit) | prompt |
| "cuartero", "cuarteto" | "cuartel" (police station) | prompt |
| "Salemencia" | "sala de emergencias" | prompt |
| "despedir" | "de expedir" (la orden) | prompt |
| "Morovi", "Norocovi", "Orocovi" | Morovis, Orocovis (municipalities) | per-job vocabulary field |
| "Elvin" / "Elvis" / "Edwin" (same person) | one spelling | per-job vocabulary (party names) |
| "la fecha y hora de la víctima" | "de la vista" | prompt has "vista" already; watch |

**Hallucination loops** (classic Whisper on cross-talk): "Yo no llegué a
leer nada." ×9 at 14:46 and "no, no, no…" ×22 at 04:21. Now collapsed in
post-processing (`turns.clean_segments`): at most 2 identical consecutive
segments and at most 3 repeated tokens in a row.

**Diarization (community-1, min_speakers=3)**: found 4 speakers, and this
time the split is usable as a draft.

| Label | Seconds | Segments | Who (by content) |
|---|---|---|---|
| SPEAKER_03 → Hablante 1 | 556 | 218 | the judge |
| SPEAKER_01 → Hablante 2 | 396 | 141 | one daughter (the one who witnessed the incident) |
| SPEAKER_02 → Hablante 4 | 333 | 115 | the other daughter |
| SPEAKER_00 → Hablante 3 | 32 | 16 | Don Juan (the father) |

Remaining errors: short answers ("Sí", "Correcto", "Juro") absorbed into the
judge's turns; a few judge questions inside a daughter's long turn and vice
versa. 73 of 490 segments carry more than one word-level speaker, but the
word labels flip too noisily to split on them automatically. Manual fix-up
in the UI stays necessary; it will be a matter of minutes per hearing, not
a rewrite.

**Readability**: same-speaker turns now also break at the next pause ≥ 1 s
once they exceed 60 s, so paragraphs stay scannable.

**New option**: `vocabulary` (comma-separated party names, town, key terms)
appended to the Whisper prompt per job. CLI: `--vocabulary "Morovis, Ciales,
Elvin Omar Negrón"`. The UI will expose it on the upload form.

## 2026-09-18 — Phase 1 CPU validation on the first real hearing (Sala 5)

Environment: Claude Code remote session, 4 vCPU, no GPU. Model
`large-v3-turbo` int8 (not the production `large-v3`), first 180 s of a
26-minute mono AAC courtroom export.

**Speed (CPU, 3 min of audio)**

| Stage | Seconds |
|---|---|
| ASR (turbo, int8, batch 4) | 33 |
| Alignment (wav2vec2 voxpopuli es) | 7 |
| Diarization (pyannote community-1) | 103 |

On an A10G expect the whole thing to be 10–20× faster.

**Transcript quality**: good. Legal register, "Ley 121", oath wording and
names came out right. Errors seen: the opening phrase ("Tenemos que
necesitar…" for what is probably "Tenemos ante nuestra consideración…") and
one municipality name. Both are candidates for the `initial_prompt`; verify
on `large-v3` first.

**Diarization quality**: weak on this audio. The courtroom feed is a single
mono mix dominated by the judge's microphone; petitioners are far-field and
mostly give one-word answers.

| Config | Speakers found | Segments per speaker | Verdict |
|---|---|---|---|
| community-1, no hints | 2 (132 s / 13 s) | all 53 → one speaker after word assignment | unusable |
| 3.1, no hints | 2 (114 s / 31 s) | 45 / 8 | poor |
| 3.1, `min_speakers=3` | 3 | 43 / 8 / 2 | poor |
| community-1, `min_speakers=3` | 3 (27 / 76 / 42 s) | 26 / 19 / 8 | partly right |
| community-1, `num_speakers=4` | 4 | 24 / 14 / 8 / 7 | partly right |

With `min_speakers=3` the split is plausible but still mixes: some of the
judge's own sentences land on a second label, and short replies ("Sí",
"Juro") get absorbed into the judge's turn.

**Decisions**

1. Keep community-1; always pass a speaker-count hint. The UI will ask
   "¿Cuántas personas hablan?" (default 3 for a hearing) and send it as
   `min_speakers`.
2. Speaker labels are a starting point, not a result. The transcript page's
   rename / merge / reassign-turn controls are core scope (they already were).
3. Re-run on GPU with `large-v3` on the full 26 minutes before tuning
   anything else; longer audio gives the clustering more to work with.
4. Later experiments if still weak: lower the clustering threshold for
   community-1; try NVIDIA NeMo Sortformer diarization as an alternative
   backend behind the same interface.

**Bugs fixed along the way** (all in the Modal image too): whisperx pinned
to 3.8.6 for pyannote.audio 4 (`token=` instead of `use_auth_token=`),
`omegaconf` added, NLTK `punkt_tab` pre-downloaded for alignment,
`pyannote/speaker-diarization-community-1` license required in addition to
3.1 and segmentation-3.0, and a truncated torchaudio checkpoint download
(re-fetch and verify the zip).
