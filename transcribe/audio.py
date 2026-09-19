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
    fmt = info.get("format", {})
    return {
        "duration": float(fmt.get("duration", 0) or 0),
        "channels": int(audio.get("channels", 0) or 0),
        "sample_rate": int(audio.get("sample_rate", 0) or 0),
        "codec": audio.get("codec_name"),
        "bit_rate": int(audio.get("bit_rate") or fmt.get("bit_rate") or 0),
        "has_video": any(s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1
                         for s in info.get("streams", [])),
    }


PLAYBACK_BITRATE = 96_000          # AAC mono, transparent for speech
PLAYBACK_KEEP_BELOW = 112_000      # already-AAC files at or under this are kept as they are


def needs_playback_copy(info: dict) -> bool:
    """True unless the file is already compact mono/stereo AAC audio without video."""
    return not (
        info.get("codec") == "aac"
        and 0 < info.get("bit_rate", 0) <= PLAYBACK_KEEP_BELOW
        and not info.get("has_video")
    )


def make_playback_copy(src: str | Path, dst: str | Path) -> Path:
    """Re-encode to 96 kbps mono AAC in .m4a: small, and every browser plays it."""
    dst = Path(dst)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
            "-c:a", "aac", "-b:a", str(PLAYBACK_BITRATE), "-movflags", "+faststart", str(dst),
        ],
        check=True,
    )
    return dst


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
