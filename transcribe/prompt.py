"""Language setting and the speaker-role menu.

Whisper is given no "initial prompt". A fixed paragraph of courtroom phrases
used to live here, and later just the names the user typed for a hearing.
Tested on real hearings, both made Whisper skip speech, and the paragraph was
copied into transcripts word for word (docs/FINDINGS.md, 2026-11-15).
Recurring misheard words are fixed afterwards by transcribe.corrections.
"""

LANGUAGE = "es"


# Offered in the UI's speaker rename menu; free text is always allowed.
ROLE_SUGGESTIONS = [
    "Juez",
    "Jueza",
    "Fiscal",
    "Abogado parte demandante",
    "Abogada parte demandante",
    "Abogado parte demandada",
    "Abogada parte demandada",
    "Acusado",
    "Acusada",
    "Peticionaria",
    "Peticionado",
    "Testigo",
    "Perito",
    "Alguacil",
    "Intérprete",
    "Secretaria",
]


def default_speaker_name(index: int) -> str:
    """Display name for the n-th speaker (0-based) before the user renames it."""
    return f"Hablante {index + 1}"
