"""Whisper processor: transcribes audio.wav (produced by the ffmpeg processor)
to transcript.md. Uses mlx-whisper for fast Apple Silicon inference; the model
is downloaded from HuggingFace on first use (~150 MB for `base.en`).

Reports cleanly if mlx-whisper isn't installed (e.g. Intel Mac) or if no
audio.wav exists (image, text, ffmpeg unavailable, source has no audio track)."""

from __future__ import annotations

import os
from pathlib import Path

from . import ProcessorResult, register

_DEFAULT_MODEL = os.environ.get(
    "PROJECT_NOTEBOOK_WHISPER_MODEL",
    "mlx-community/whisper-base.en-mlx",
)


@register("video", "audio", name="whisper")
def process(artifact_path: Path, sidecar_dir: Path) -> ProcessorResult:
    audio_path = sidecar_dir / "audio.wav"
    if not audio_path.exists():
        return {"outputs": [], "error": "no audio.wav (ffmpeg didn't run, or no audio track)"}

    try:
        import mlx_whisper  # type: ignore
    except ImportError:
        return {"outputs": [], "error": "mlx-whisper not installed (Apple Silicon only)"}

    try:
        result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=_DEFAULT_MODEL)
    except Exception as e:
        return {"outputs": [], "error": f"whisper failed: {type(e).__name__}: {e}"}

    full_text = (result.get("text") or "").strip()
    segments = result.get("segments") or []
    lines = [f"# Transcript ({_DEFAULT_MODEL.split('/')[-1]})", "", full_text or "_(empty)_"]
    if segments:
        lines += ["", "## Segments"]
        for seg in segments:
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or 0)
            text = (seg.get("text") or "").strip()
            lines.append(f"- [{start:.1f}s – {end:.1f}s] {text}")

    transcript_path = sidecar_dir / "transcript.md"
    transcript_path.write_text("\n".join(lines) + "\n")
    return {"outputs": ["transcript.md"], "error": None}
