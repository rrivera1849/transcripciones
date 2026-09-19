"""Puerto Rican courtroom vocabulary used to steer Whisper.

The initial prompt is the closest thing Whisper has to a custom vocabulary:
it conditions the decoder on the register, punctuation style and terms it
should expect. Tune this against real hearings, not by intuition.
"""

LANGUAGE = "es"

INITIAL_PROMPT = (
    "Vista en el Tribunal de Primera Instancia de Puerto Rico. "
    "Intervienen la Honorable Jueza, el Fiscal del Ministerio Público, "
    "el Licenciado de la defensa, el acusado, los testigos, el perito y el alguacil. "
    "Con la venia del Tribunal. Objeción. Ha lugar. No ha lugar. "
    "Se declara con lugar la moción. Que conste en récord. "
    "Tenemos ante nuestra consideración una petición de orden de protección "
    "al amparo de la Ley 121. Se expide la orden y se cita a las partes a una vista. "
    "La finca de cuatro cuerdas. Fueron al cuartel de la policía y a la sala de emergencias."
)


def build_prompt(vocabulary: list[str] | str | None = None) -> str:
    """Append per-hearing vocabulary (party names, municipality, case-specific terms).

    Whisper only sees roughly the last 200 tokens of the prompt, so keep the
    extra list short: names of the parties, the town, a few key terms.
    """
    if not vocabulary:
        return INITIAL_PROMPT
    if isinstance(vocabulary, str):
        vocabulary = [v.strip() for v in vocabulary.replace("\n", ",").split(",")]
    extra = ", ".join(v for v in vocabulary if v)
    return f"{INITIAL_PROMPT} {extra}." if extra else INITIAL_PROMPT

# Offered in the UI's speaker rename menu; free text is always allowed.
ROLE_SUGGESTIONS = [
    "Juez",
    "Jueza",
    "Fiscal",
    "Lcdo. de la defensa",
    "Lcda. de la defensa",
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
