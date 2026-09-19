import json
from pathlib import Path

from transcribe import Transcript
from transcribe.turns import fmt_ts, group_turns, merge_speakers, rename_speaker, speaker_names

FIX = Path(__file__).parent / "fixtures" / "sample.json"


def load():
    return Transcript.from_dict(json.loads(FIX.read_text(encoding="utf-8")))


def test_speakers_in_order_of_appearance():
    assert load().speakers() == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]


def test_group_turns_merges_same_speaker_and_drops_noise():
    turns = group_turns(load().segments)
    # 00 (2 segs) | 01 (tiny "eh" dropped) | 02 | 00 | 00 after 7 s gap -> new turn | blank dropped
    assert [t.speaker for t in turns] == [
        "SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_00", "SPEAKER_00"
    ]
    assert turns[0].text == "Se abre la sesión. Licenciado, tiene la palabra."
    assert turns[0].start == 0.0 and turns[0].end == 5.0
    assert turns[1].text == "Con la venia del Tribunal, señoría."


def test_default_names_and_overrides():
    t = load()
    assert speaker_names(t) == {
        "SPEAKER_00": "Hablante 1", "SPEAKER_01": "Hablante 2", "SPEAKER_02": "Hablante 3"
    }
    ov = rename_speaker({}, "SPEAKER_00", " Jueza ")
    assert speaker_names(t, ov)["SPEAKER_00"] == "Jueza"
    assert speaker_names(t, ov)["SPEAKER_01"] == "Hablante 2"


def test_merge_speakers_relabels_segments():
    t = merge_speakers(load(), keep="SPEAKER_01", absorb="SPEAKER_02")
    assert t.speakers() == ["SPEAKER_00", "SPEAKER_01"]
    turns = group_turns(t.segments)
    assert turns[1].text == "Con la venia del Tribunal, señoría. Objeción."


def test_fmt_ts():
    assert fmt_ts(0) == "00:00:00"
    assert fmt_ts(3725.4) == "01:02:05"
    assert fmt_ts(61.25, with_ms=True) == "00:01:01,250"


def test_clean_segments_collapses_repetition_loops():
    from transcribe import Segment
    from transcribe.turns import clean_segments, collapse_token_runs

    segs = [Segment(i * 1.0, i * 1.0 + 0.9, "Yo no llegué a leer nada.", "S1") for i in range(9)]
    segs.append(Segment(10.0, 12.0, "Nos entrevistó.", "S1"))
    out = clean_segments(segs)
    assert [s.text for s in out] == ["Yo no llegué a leer nada."] * 2 + ["Nos entrevistó."]
    assert out[1].end == 8.9  # the collapsed run keeps the span
    assert collapse_token_runs("No, no, no, no, no, no, no.") == "No, no, no."
    assert collapse_token_runs("Sí, sí, gracias.") == "Sí, sí, gracias."


def test_long_turn_breaks_at_a_pause():
    from transcribe import Segment
    from transcribe.turns import group_turns

    segs = [Segment(t, t + 9.5, f"frase {t}", "S1") for t in range(0, 100, 10)]  # 0.5 s gaps
    assert len(group_turns(segs)) == 1  # no pause long enough to break
    segs[7] = Segment(72.0, 79.5, "frase 72", "S1")  # 2.5 s pause before it, past 60 s
    assert len(group_turns(segs)) == 2


def test_build_prompt_appends_vocabulary():
    from transcribe.prompt import INITIAL_PROMPT, build_prompt

    assert build_prompt(None) == INITIAL_PROMPT
    p = build_prompt("Morovis, Ciales, Lcda. Torres")
    assert p.startswith(INITIAL_PROMPT) and p.endswith("Morovis, Ciales, Lcda. Torres.")


def test_pipeline_output_is_plain_python():
    """The Modal result is unpickled on a host without numpy: no numpy scalars allowed."""
    import json

    from transcribe.whisperx_pipeline import _num, _str

    class FakeFloat64(float):  # stands in for numpy.float64 (a float subclass)
        pass

    assert type(_num(FakeFloat64(1.5))) is float and _num(None) is None
    assert _num(float("nan")) is None and _num("x") is None
    assert _str(float("nan")) is None and _str("SPEAKER_01") == "SPEAKER_01"
    json.dumps({"a": _num(FakeFloat64(2.0)), "b": _str(None)})


def test_merge_turns_collapses_adjacent_same_speaker_turns():
    from transcribe.turns import merge_turns

    t = load()
    turns = group_turns(t.segments)
    # turns 3 and 4 are both SPEAKER_00 ("Ha lugar." then, after a 7 s gap, "Continúe, licenciado.")
    assert turns[3].speaker == turns[4].speaker == "SPEAKER_00"
    segs = merge_turns(t.segments, turns[3], turns[4])
    merged = group_turns(segs)
    assert len(merged) == len(turns) - 1
    assert merged[3].text == "Ha lugar. Continúe, licenciado."
    assert merged[3].start == 12.1 and merged[3].end == 24.0
    import pytest

    with pytest.raises(ValueError):
        merge_turns(t.segments, turns[0], turns[2])
