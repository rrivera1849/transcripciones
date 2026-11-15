"""Automatic corrections for words Whisper mishears in Puerto Rico courtrooms."""

from collections import Counter

import pytest

from transcribe import Segment, Transcript, Word
from transcribe.corrections import apply_corrections, correct_segment, describe


def _seg(text: str, start: float = 0.0) -> Segment:
    words = [Word(w, start + i, start + i + 0.5, 0.9, "S0") for i, w in enumerate(text.split())]
    return Segment(start, start + len(words), text, "S0", words)


def _fix(text: str) -> Segment | None:
    out = correct_segment(_seg(text))
    if out is not None:
        assert out.text == " ".join(w.word for w in out.words)  # words stay in sync with text
    return out


@pytest.mark.parametrize("before, after", [
    # her email, verbatim lines from production transcripts
    ("pero es que estáis diciendo que era el Tribunal, güey.", "pero es que estáis diciendo que era el Tribunal, juez."),
    ("Sí, güey, mire.", "Sí, juez, mire."),
    ("Güey, una pregunta.", "Juez, una pregunta."),
    ("No tiene nada ahí, wey.", "No tiene nada ahí, juez."),
    ("Para que se admita como ex-civil.", "Para que se admita como exhibit."),
    ("Que se admita como ex civil.", "Que se admita como exhibit."),
    ("que se incorporó como exhibi, que es", "que se incorporó como exhibit, que es"),
    ("Vamos a referirnos al exilio número cuatro.", "Vamos a referirnos al exhibit número cuatro."),
    ("sería el exilio 3 de la parte demandante", "sería el exhibit 3 de la parte demandante"),
    ("consta en récord Inmitida como exilio.", "consta en récord Admitida como exhibit."),
    ("Me pregunto en relación al paudal relicto.", "Me pregunto en relación al caudal relicto."),
    ("Que no tiene papeles. Se titula. Se titula.", "Que no tiene papeles. Se estipula. Se estipula."),
])
def test_fixes(before, after):
    out = _fix(before)
    assert out.text == after
    fixed = [w for w in out.words if w.fixed_from]
    assert fixed and all(w.fixed_from != w.word for w in fixed)


@pytest.mark.parametrize("text, word, hint", [
    ("No, hemos sometido a vuestro nombre.", "hemos", "lo damos por sometido"),
    ("este documento que se titula Contrato, Sesión y Derecho.", "titula", "estipula"),
    ("este documento que se titula Contrato, Sesión y Derecho.", "Sesión", "cesión"),
    ("la casa que es objeto de este descanso.", "descanso.", "desahucio"),
    ("Es el exilio, el libro de exilio.", "exilio,", "exhibit"),
])
def test_suggestions_mark_but_do_not_change(text, word, hint):
    out = _fix(text)
    assert out.text == text
    assert any(w.word == word and w.suggest == hint for w in out.words)


@pytest.mark.parametrize("text", [
    "el titular de la finca y su titularidad",
    "Suscrito y jurado ante mí, affidávit número tal.",
    "No sé... pero... ya.",
    "Se estipula la prueba.",
    "Buenas tardes, Vuestro Honor.",
])
def test_ordinary_text_is_untouched(text):
    out = _fix(text)
    assert out.text == text and not any(w.fixed_from or w.suggest for w in out.words)


def test_invented_lines_are_dropped():
    assert _fix("Gracias por ver el video.") is None
    assert _fix("... ... ... ... ...") is None
    assert _fix("Subtítulos realizados por la comunidad de Amara.org") is None
    out = _fix("Y entonces dijo que sí. Gracias por ver el video. Ok.")
    assert out.text == "Y entonces dijo que sí. Ok."


def test_a_two_word_fix_keeps_the_timing_of_both():
    out = _fix("Que se admita como ex civil.")
    w = out.words[-1]
    assert w.word == "exhibit." and w.fixed_from == "ex civil." and (w.start, w.end) == (4, 5.5)


def test_unaligned_segment_gets_text_fixes_only():
    seg = Segment(0, 2, "Sí, güey. No hemos sometido.", "S0", [])
    out = correct_segment(seg)
    assert out.text == "Sí, juez. No hemos sometido." and out.words == []


def test_apply_corrections_returns_a_copy_and_counts():
    t = Transcript([_seg("Sí, güey."), _seg("Gracias por ver el video.", 5), _seg("No hemos sometido.", 10)])
    fixed, counts = apply_corrections(t)
    assert t.segments[0].text == "Sí, güey."  # input untouched
    assert [s.text for s in fixed.segments] == ["Sí, juez.", "No hemos sometido."]
    assert counts == Counter(fixed=1, dropped=1, suggested=1)
    assert describe(counts) == ("correcciones automáticas: 1 palabra corregida, 1 sugerencia, "
                                "1 frase inventada quitada")
    back = Transcript.from_dict(fixed.to_dict())  # marks survive storage
    assert back.segments[0].words[1].fixed_from == "güey."
    assert back.segments[1].words[1].suggest == "lo damos por sometido"
