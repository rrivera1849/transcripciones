"""CLI.

  python -m transcribe samples/x.m4a --local            # CPU, small model, no speakers
  python -m transcribe samples/x.m4a --modal            # GPU on Modal (after `modal deploy modal_app.py`)
  python -m transcribe samples/x.m4a --local --slice 0:120   # first 2 minutes only
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .audio import normalize, probe, slice_audio
from .export import write_all


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="transcribe")
    ap.add_argument("audio", type=Path)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local", action="store_true", help="CPU faster-whisper, no diarization")
    mode.add_argument("--modal", action="store_true", help="run on Modal GPU (deployed app)")
    ap.add_argument("--model", default="small", help="local model size (default: small)")
    ap.add_argument("--slice", metavar="START:SECONDS", help="only transcribe a slice, e.g. 0:120")
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--min-speakers", type=int)
    ap.add_argument("--max-speakers", type=int)
    args = ap.parse_args(argv)

    src = args.audio
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 2
    info = probe(src)
    print(f"{src.name}: {info['duration']:.0f}s, {info['channels']} ch, {info['codec']}")

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "input.wav"
        if args.slice:
            start, length = (float(x) for x in args.slice.split(":"))
            slice_audio(src, wav, start, length)
        else:
            normalize(src, wav)

        if args.local:
            from .local_cpu import transcribe_file

            transcript = transcribe_file(wav, model_size=args.model)
        else:
            from .modal_client import transcribe_on_modal

            transcript = transcribe_on_modal(
                wav, min_speakers=args.min_speakers, max_speakers=args.max_speakers
            )

    stem = src.stem + (f"_slice{args.slice.replace(':', '-')}" if args.slice else "")
    paths = write_all(transcript, args.out, stem, title=src.stem)
    print(f"segments: {len(transcript.segments)}  speakers: {transcript.speakers()}")
    print(f"timing: {transcript.timing}")
    for k, p in paths.items():
        print(f"  {k}: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
