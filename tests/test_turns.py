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
