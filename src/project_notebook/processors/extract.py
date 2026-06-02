"""extract processor: writes meta.yaml + audio.wav + poster.jpg next to the
artifact, using the `ffmpeg` tool (and its sibling `ffprobe`). The mono 16 kHz
audio.wav is the input the `transcribe` processor consumes — registering
before it ensures the right run order. Reports cleanly if ffmpeg is missing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import tools as _tools
from . import ProcessorResult, register


def _ffmpeg_available() -> bool:
    """Ask the tool registry whether the `extract` feature has a backing tool.

    Single source of truth for "is ffmpeg here?" — same answer `check` reports.
    """
    feature = next(f for f in _tools.FEATURES if f.id == "media_extract")
    return feature.is_on()


def _probe(path: Path) -> dict:
    """Return ffprobe JSON metadata or {} on failure."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return {}


def _meta_from_probe(probe: dict, filename: str) -> dict:
    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    meta: dict = {
        "filename": filename,
        "format": fmt.get("format_name"),
        "duration_seconds": float(fmt["duration"]) if fmt.get("duration") else None,
        "size_bytes": int(fmt["size"]) if fmt.get("size") else None,
        "bitrate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        "has_audio": audio is not None,
        "has_video": video is not None,
    }
    if video:
        meta["video"] = {
            "codec": video.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
        }
    if audio:
        meta["audio"] = {
            "codec": audio.get("codec_name"),
            "channels": audio.get("channels"),
            "sample_rate": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
        }
    return meta


@register("video", "audio", name="extract")
def process(artifact_path: Path, sidecar_dir: Path) -> ProcessorResult:
    if not _ffmpeg_available():
        return {"outputs": [], "error": "ffmpeg not on PATH (try `brew install ffmpeg`; see `project-notebook check`)"}

    outputs: list[str] = []

    # 1. Probe + meta.yaml
    probe = _probe(artifact_path)
    if probe:
        import yaml
        meta = _meta_from_probe(probe, artifact_path.name)
        (sidecar_dir / "meta.yaml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
        outputs.append("meta.yaml")

    # 2. Audio extraction (mono 16 kHz WAV — transcribe processor's preferred input)
    if probe and any(s.get("codec_type") == "audio" for s in probe.get("streams", [])):
        audio_path = sidecar_dir / "audio.wav"
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(artifact_path),
             "-vn", "-ac", "1", "-ar", "16000", str(audio_path)],
            capture_output=True, timeout=600, check=False,
        )
        if result.returncode == 0 and audio_path.exists():
            outputs.append("audio.wav")

    # 3. Poster (mid-duration keyframe, video only)
    if probe and any(s.get("codec_type") == "video" for s in probe.get("streams", [])):
        duration = float(probe.get("format", {}).get("duration", 0) or 0)
        poster_time = max(0.5, duration / 2)
        poster_path = sidecar_dir / "poster.jpg"
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{poster_time:.2f}", "-i", str(artifact_path),
             "-frames:v", "1", "-q:v", "3", str(poster_path)],
            capture_output=True, timeout=30, check=False,
        )
        if result.returncode == 0 and poster_path.exists():
            outputs.append("poster.jpg")

    return {"outputs": outputs, "error": None}
