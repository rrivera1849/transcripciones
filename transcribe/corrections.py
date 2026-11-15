"""Fix words Whisper reliably mishears in Puerto Rico courtrooms.

Applied on the app host when a transcript arrives (and by the CLI), never on
the GPU, so rules can change without a Modal deploy. Four kinds of rule, from
most to least certain:

  DROPS     whole sentences Whisper invents on silence ("Gracias por ver el video.")
  FIXES     words never right in court, or only wrong in a clear context; replaced
  SUGGEST   likely mistakes that are sometimes right; only marked for the reader

Rules match the segment's words joined by single spaces, case-insensitively.
A rule may name the part to change with a group called `w`; the rest of the
match is context. Changes are made on the aligned word list, so timestamps,
doubtful-word marks and click-to-listen keep working. A fixed word remembers
its original text in `Word.fixed_from`; a suggestion goes in `Word.suggest`.

Evidence for every rule: docs/FINDINGS.md (2026-11-15).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace

from . import Segment, Transcript, Word

_NUM = r"(?:\d+|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)"
# A whole sentence: starts the segment or follows sentence punctuation + space,
# and ends at a space or the end of the segment.
_SENT_START = r"(?:^|(?<=[.?!…] ))"
_SENT_END = r"(?=\s|$)"

DROPS: list[str] = [
    _SENT_START + r"gracias por ver el v[ií]deo[.!]?" + _SENT_END,
    _SENT_START + r"¡?suscr[ií]bete al canal[.!]?" + _SENT_END,
    _SENT_START + r"subt[ií]tulos realizados por la comunidad de amara\.org\.?" + _SENT_END,
    # three or more "..." in a row with nothing else
    r"(?:^|(?<= ))(?:\.\.\.|…)(?: (?:\.\.\.|…)){2,}" + _SENT_END,
]

FIXES: list[tuple[str, str]] = [
    # Puerto Rican "juez" (final s aspirated) heard as Mexican slang.
    (r"\b(?P<w>g[üu]ey|wey)\b", "juez"),
    # The English loanword "exhibit".
    (r"\b(?P<w>ex[- ]civil|excivil)\b", "exhibit"),
    (r"\b(?P<w>exhibi)\b", "exhibit"),
    (rf"\b(?P<w>exilio)(?= (?:n[úu]mero |n[úu]m\. ?|no\. ?)?{_NUM}\b)", "exhibit"),
    (r"(?<=\bcomo )(?P<w>exilio)\b", "exhibit"),
    (r"\b(?P<w>inmitid)(?=[oa]s?\b)", "admitid"),
    (r"\b(?P<w>paudal)(?= relicto\b)", "caudal"),
    # "Se titula." alone is meaningless; it is "Se estipula." with the "es" swallowed.
    (_SENT_START + r"se (?P<w>titula)(?=\.(?:\s|$))", "estipula"),
]

SUGGEST: list[tuple[str, str]] = [
    (r"\b(?P<w>titula|titulan)\b", "estipula"),
    (r"\b(?P<w>hemos sometido)\b", "lo damos por sometido"),
    (r"\bobjeto de este (?P<w>descanso)\b", "desahucio"),
    (r"\bcontratos?,? (?:de )?(?P<w>excepci[oó]n(?:es)?|sesi[oó]n(?:es)?)\b", "cesión"),
    (r"\b(?P<w>exilio)\b", "exhibit"),
]

_DROPS = [re.compile(p, re.IGNORECASE) for p in DROPS]
_FIXES = [(re.compile(p, re.IGNORECASE), r) for p, r in FIXES]
_SUGGEST = [(re.compile(p, re.IGNORECASE), r) for p, r in SUGGEST]


def _match_case(original: str, new: str) -> str:
    if len(original) > 1 and original.isupper():
        return new.upper()
    if original[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def _spans(pat: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    out = []
    for m in pat.finditer(text):
        a, b = m.span("w") if "w" in pat.groupindex else m.span()
        if b > a:
            out.append((a, b))
    return out


def _apply(tokens: list[Word], pat: re.Pattern[str], kind: str, value: str = "") -> tuple[list[Word], int]:
    """Apply one rule to a token list. Returns (new tokens, number of matches)."""
    text = " ".join(t.word for t in tokens)
    spans = _spans(pat, text)
    if not spans:
        return tokens, 0
    starts, ends, pos = [], [], 0
    for t in tokens:
        starts.append(pos)
        ends.append(pos + len(t.word))
        pos += len(t.word) + 1
    tokens = list(tokens)
    for a, b in reversed(spans):  # right to left keeps earlier offsets valid
        i = next(k for k in range(len(tokens)) if ends[k] > a)
        j = max(k for k in range(len(tokens)) if starts[k] < b)
        if kind == "suggest":
            for k in range(i, j + 1):
                if not tokens[k].fixed_from and not tokens[k].suggest:
                    tokens[k] = replace(tokens[k], suggest=value)
            continue
        new_text = text[starts[i]:a] + (_match_case(text[a:b], value) if value else "") + text[b:ends[j]]
        if not new_text.strip():
            del tokens[i:j + 1]
            continue
        first, last = tokens[i], tokens[j]
        scores = [t.score for t in tokens[i:j + 1] if t.score is not None]
        original = first.fixed_from if i == j and first.fixed_from else text[starts[i]:ends[j]]
        tokens[i:j + 1] = [replace(first, word=new_text.strip(), end=last.end,
                                   score=min(scores) if scores else None, fixed_from=original)]
    return tokens, len(spans)


def _aligned(seg: Segment) -> bool:
    return bool(seg.words) and " ".join(w.word for w in seg.words) == seg.text


def correct_segment(seg: Segment, counts: Counter | None = None) -> Segment | None:
    """Return the corrected segment, or None when nothing is left of it."""
    counts = counts if counts is not None else Counter()
    aligned = _aligned(seg)
    tokens = list(seg.words) if aligned else [Word(w) for w in seg.text.split()]
    for pat in _DROPS:
        tokens, n = _apply(tokens, pat, "drop")
        counts["dropped"] += n
    for pat, value in _FIXES:
        tokens, n = _apply(tokens, pat, "fix", value)
        counts["fixed"] += n
    if aligned:  # suggestions are marks on words; text-only segments can't show them
        for pat, value in _SUGGEST:
            tokens, n = _apply(tokens, pat, "suggest", value)
            counts["suggested"] += n
    if not tokens:
        return None
    text = " ".join(t.word for t in tokens)
    if aligned:
        return replace(seg, text=text, words=tokens)
    return replace(seg, text=text)


def apply_corrections(transcript: Transcript) -> tuple[Transcript, Counter]:
    """Corrected copy of the transcript (the input is not modified) and what changed."""
    counts: Counter = Counter()
    segments = [s for s in (correct_segment(seg, counts) for seg in transcript.segments) if s]
    return replace(transcript, segments=segments), counts


def describe(counts: Counter) -> str:
    """Spanish summary for the revision history, e.g. "correcciones automáticas: 3 palabras"."""
    parts = []
    if counts["fixed"]:
        parts.append(f"{counts['fixed']} {'palabra corregida' if counts['fixed'] == 1 else 'palabras corregidas'}")
    if counts["suggested"]:
        parts.append(f"{counts['suggested']} {'sugerencia' if counts['suggested'] == 1 else 'sugerencias'}")
    if counts["dropped"]:
        parts.append(f"{counts['dropped']} {'frase inventada quitada' if counts['dropped'] == 1 else 'frases inventadas quitadas'}")
    return "correcciones automáticas: " + ", ".join(parts) if parts else "correcciones automáticas"
