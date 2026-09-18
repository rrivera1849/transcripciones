import json
from pathlib import Path

from docx import Document

from transcribe import Transcript
from transcribe.export import to_docx, to_srt, to_txt, write_all

FIX = Path(__file__).parent / "fixtures" / "sample.json"


def load():
    return Transcript.from_dict(json.loads(FIX.read_text(encoding="utf-8")))


def test_txt_has_one_line_per_turn_with_names():
    txt = to_txt(load(), {"SPEAKER_00": "Jueza"})
    lines = [l for l in txt.splitlines() if l.strip()]
    assert lines[0] == "[00:00:00] Jueza: Se abre la sesión. Licenciado, tiene la palabra."
    assert lines[1].startswith("[00:00:05] Hablante 2: ")
    assert len(lines) == 5


def test_srt_is_per_segment_and_skips_blank():
    srt = to_srt(load())
    blocks = [b for b in srt.strip().split("\n\n") if b]
    assert len(blocks) == 7  # 8 segments minus the blank one
    assert blocks[0].splitlines() == [
        "1", "00:00:00,000 --> 00:00:02,500", "Hablante 1: Se abre la sesión."
    ]


def test_docx_written_with_speaker_runs(tmp_path):
    p = to_docx(load(), tmp_path / "t.docx", {"SPEAKER_00": "Jueza"}, title="Vista")
    doc = Document(str(p))
    texts = [para.text for para in doc.paragraphs]
    assert texts[0] == "Vista"
    body = [t for t in texts if "Se abre la sesión" in t]
    assert body and body[0].startswith("Jueza  [00:00:00]  ")


def test_write_all_roundtrip(tmp_path):
    paths = write_all(load(), tmp_path, "x", title="X")
    assert set(paths) == {"json", "txt", "srt", "docx"}
    back = Transcript.from_dict(json.loads(paths["json"].read_text(encoding="utf-8")))
    assert len(back.segments) == 8 and back.duration == 30.0
