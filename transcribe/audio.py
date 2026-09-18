"""ffmpeg helpers: probe duration and normalise any input to 16 kHz mono WAV."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ACCEPTED_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac", ".wma",
    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".amr", ".3gp",
}


def probe(path: str | Path) -> dict:
    """Return ffprobe format info (duration, channels, codec) as a dict."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    info = json.loads(out)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "duration": float(info.get("format", {}).get("duration", 0) or 0),
        "channels": int(audio.get("channels", 0) or 0),
        "sample_rate": int(audio.get("sample_rate", 0) or 0),
        "codec": audio.get("codec_name"),
    }


def normalize(src: str | Path, dst: str | Path) -> Path:
    """Decode `src` to 16 kHz mono 16-bit PCM WAV at `dst` (what Whisper wants)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst),
        ],
        check=True,
    )
    return dst


def slice_audio(src: str | Path, dst: str | Path, start: float, length: float) -> Path:
    """Cut `length` seconds starting at `start` (used for quick dev runs)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(length),
            "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst),
        ],
        check=True,
    )
    return dst
