# Findings log

Running notes from real runs. Newest first.

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
