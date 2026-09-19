"""Guess courtroom roles from what each voice says.

Diarization only tells us "voice 3"; the phrases a voice uses tell us whether
it is the judge ("ha lugar", "este tribunal"), an attorney ("con la venia",
"objeción"), the bailiff ("todos de pie") or a witness (short answers, "no
recuerdo"). Suggestions are conservative: a role is proposed only when one
voice clearly outscores the others, and the user always confirms.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from . import Transcript

JUDGE, ATTORNEY, FISCAL, DEFENSE, WITNESS, BAILIFF, INTERPRETER = (
    "juez", "abogado", "fiscal", "defensa", "testigo", "alguacil", "intérprete",
)

# (role, weight, human label, regex on the lower-cased segment text)
CUES: list[tuple[str, float, str, re.Pattern[str]]] = [
    (JUDGE, 3, "ha lugar", re.compile(r"\b(no )?ha lugar\b")),
    (JUDGE, 2, "se declara", re.compile(r"\bse declara\b")),
    (JUDGE, 2, "se cita / se expide / se ordena", re.compile(r"\bse (cita|expide|ordena|señala|reserva)\b")),
    (JUDGE, 1.5, "este tribunal", re.compile(r"\b(este|el) tribunal\b")),
    (JUDGE, 2, "puede continuar / retirarse", re.compile(r"\bpuede (continuar|proceder|retirarse|sentarse|pasar)\b")),
    (JUDGE, 1, "adelante", re.compile(r"\badelante\b")),
    (JUDGE, 1, "receso", re.compile(r"\breceso\b")),
    (JUDGE, 1.5, "vayan preparados", re.compile(r"\bvayan? preparad")),
    (JUDGE, 1, "que conste", re.compile(r"\bque conste\b")),
    (ATTORNEY, 2, "con la venia", re.compile(r"\bcon la venia\b")),
    (ATTORNEY, 2, "objeción", re.compile(r"\bobjeci[oó]n\b")),
    (ATTORNEY, 1, "señoría", re.compile(r"\bse[ñn]or[ií]a\b")),
    (ATTORNEY, 1, "honorable", re.compile(r"\bhonorable\b")),
    (FISCAL, 2, "el Pueblo", re.compile(r"\bel pueblo\b")),
    (FISCAL, 2, "Ministerio Público", re.compile(r"\bministerio p[uú]blico\b")),
    (FISCAL, 1, "la fiscalía", re.compile(r"\bla fiscal[ií]a\b")),
    (DEFENSE, 3, "mi representado", re.compile(r"\bmi (representad[oa]|cliente)\b")),
    (DEFENSE, 1, "la defensa", re.compile(r"\bla defensa\b")),
    (WITNESS, 1, "sí / no", re.compile(r"^(s[ií]|no)[,.]?(\s+(se[ñn]or[a]?|licenciad[oa]))?[.]?$")),
    (WITNESS, 1, "no recuerdo", re.compile(r"\bno (recuerdo|me acuerdo|s[eé])\b")),
    (WITNESS, 1, "yo estaba / yo vi", re.compile(r"\byo (estaba|fui|vi|le dije|llegu[eé]|me fui)\b")),
    (BAILIFF, 3, "todos de pie", re.compile(r"\btodos de pie\b")),
    (BAILIFF, 3, "se abre la sesión", re.compile(r"\bse (abre|reanuda|levanta) la sesi[oó]n\b")),
    (BAILIFF, 3, "jura decir la verdad", re.compile(r"\b(jura|afirma)\b.*\bverdad\b")),
    (BAILIFF, 2, "levante la mano", re.compile(r"\blevante la mano\b")),
    (INTERPRETER, 3, "el testigo dice", re.compile(r"\b(el|la) testigo (dice|indica|responde|contesta)\b")),
]

MIN_SCORE = {JUDGE: 3, ATTORNEY: 3, FISCAL: 2, DEFENSE: 2, WITNESS: 4, BAILIFF: 3, INTERPRETER: 3}
# Roles that at most one voice can hold.
SINGLETON = (JUDGE, FISCAL, DEFENSE, BAILIFF, INTERPRETER, ATTORNEY)


@dataclass
class RoleSuggestion:
    name: str  # display name to propose, e.g. "Jueza"
    reason: str  # Spanish, e.g. "dice «ha lugar» 6 veces"


def _judge_name(transcript: Transcript) -> str:
    text = " ".join(s.text.lower() for s in transcript.segments)
    fem = len(re.findall(r"\bjueza\b", text))
    masc = len(re.findall(r"\bjuez\b", text))
    if fem > masc:
        return "Jueza"
    if masc > fem:
        return "Juez"
    return "Juez/a"


def _display(role: str, transcript: Transcript) -> str:
    return {
        JUDGE: _judge_name(transcript),
        ATTORNEY: "Licenciado/a",
        FISCAL: "Fiscal",
        DEFENSE: "Lcdo./a. de la defensa",
        WITNESS: "Testigo",
        BAILIFF: "Alguacil",
        INTERPRETER: "Intérprete",
    }[role]


def _reason(label: str, n: int) -> str:
    return f"dice «{label}» {n} {'vez' if n == 1 else 'veces'}"


def suggest_roles(transcript: Transcript) -> dict[str, RoleSuggestion]:
    """Map speaker id -> suggestion, only for voices with a clear signal."""
    score: dict[str, Counter] = defaultdict(Counter)  # speaker -> role -> points
    hits: dict[tuple[str, str], Counter] = defaultdict(Counter)  # (speaker, role) -> label -> n
    points: dict[tuple[str, str], Counter] = defaultdict(Counter)  # same, weighted
    for seg in transcript.segments:
        if not seg.speaker:
            continue
        text = seg.text.strip().lower()
        for role, weight, label, pat in CUES:
            n = len(pat.findall(text))
            if n:
                score[seg.speaker][role] += weight * n
                hits[(seg.speaker, role)][label] += n
                points[(seg.speaker, role)][label] += weight * n
    # Attorney cues support both the fiscal and the defense; specific cues decide.
    for roles in score.values():
        for specific in (FISCAL, DEFENSE):
            if roles[specific]:
                roles[specific] += roles[ATTORNEY]

    out: dict[str, RoleSuggestion] = {}
    taken: set[str] = set()

    def best(role: str) -> str | None:
        ranked = sorted(
            ((score[sp][role], sp) for sp in score if sp not in taken and score[sp][role] >= MIN_SCORE[role]),
            reverse=True,
        )
        if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
            return None
        return ranked[0][1]

    def assign(sp: str, role: str) -> None:
        # Explain with the strongest cue, e.g. «ha lugar» over «adelante».
        key = (sp, role) if points[(sp, role)] else (sp, ATTORNEY)
        label = points[key].most_common(1)[0][0]
        out[sp] = RoleSuggestion(_display(role, transcript), _reason(label, hits[key][label]))
        taken.add(sp)

    for role in (JUDGE, BAILIFF, INTERPRETER, DEFENSE, FISCAL, ATTORNEY):
        sp = best(role)
        if sp:
            assign(sp, role)
    for sp in score:
        if sp not in taken and score[sp][WITNESS] >= MIN_SCORE[WITNESS]:
            assign(sp, WITNESS)
    return out
