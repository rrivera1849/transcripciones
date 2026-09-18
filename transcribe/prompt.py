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
    "Se declara con lugar la moción. Que conste en récord."
)

# Offered in the UI's speaker rename menu; free text is always allowed.
ROLE_SUGGESTIONS = [
    "Juez",
    "Jueza",
    "Fiscal",
    "Lcdo. de la defensa",
    "Lcda. de la defensa",
    "Acusado",
    "Acusada",
    "Testigo",
    "Perito",
    "Alguacil",
    "Intérprete",
    "Secretaria",
]


def default_speaker_name(index: int) -> str:
    """Display name for the n-th speaker (0-based) before the user renames it."""
    return f"Hablante {index + 1}"
