from transcribe import Segment, Transcript
from transcribe.roles import suggest_roles


def _t(lines: list[tuple[str, str]]) -> Transcript:
    return Transcript(
        segments=[Segment(i * 2.0, i * 2.0 + 1.5, text, sp) for i, (sp, text) in enumerate(lines)]
    )


def test_judge_attorneys_and_witness_are_suggested():
    t = _t([
        ("S0", "Se abre la sesión. Adelante, licenciado."),
        ("S1", "Con la venia del Tribunal, señoría. El Pueblo está listo."),
        ("S2", "Con la venia, señoría. Mi representado se declara no culpable."),
        ("S0", "Ha lugar. Que conste en récord. Puede continuar."),
        ("S3", "Sí."),
        ("S3", "No recuerdo."),
        ("S3", "Yo estaba en la casa."),
        ("S3", "No, señor."),
        ("S1", "Objeción, señoría."),
        ("S0", "No ha lugar. Adelante."),
        ("S4", "La jueza dijo que sí."),
    ])
    got = suggest_roles(t)
    assert got["S0"].name == "Jueza" and "ha lugar" in got["S0"].reason
    assert got["S1"].name == "Fiscal" and got["S2"].name == "Lcdo./a. de la defensa"
    assert got["S3"].name == "Testigo"
    assert "S4" not in got  # one stray mention is not a signal


def test_no_suggestion_when_two_voices_tie():
    t = _t([("A", "Ha lugar."), ("B", "Ha lugar."), ("A", "Adelante."), ("B", "Adelante.")])
    assert suggest_roles(t) == {}


def test_a_voice_gets_at_most_one_role():
    t = _t([("A", "Ha lugar. Adelante."), ("A", "No ha lugar."), ("A", "Todos de pie.")])
    got = suggest_roles(t)
    assert list(got) == ["A"] and got["A"].name in ("Juez", "Juez/a")
