"""transcribe processor: writes transcript.md (and transcript.json) next to
the artifact, using whichever transcription tool the registry resolves to.

Consumes the audio.wav produced by the extract processor. Shells out to the
tool as an external program — no Python imports of optional backends — so
adding/removing a backend is just registry + a small runner function here.

Currently wired: mlx-whisper. Other backends (whisper.cpp, openai-whisper)
can be added by registering them in `tools.py` and adding a runner to the
`_RUNNERS` dispatch below."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .. import tools as _tools
from . import ProcessorResult, register

_DEFAULT_MODEL = os.environ.get(
    "PROJECT_NOTEBOOK_WHISPER_MODEL",
    "mlx-community/whisper-base.en-mlx",
)

_FEATURE_ID = "transcription"


def _format_transcript_md(data: dict, tool_id: str) -> str:
    """Render whisper-shaped JSON (`{text, segments, language}`) as the
    markdown transcript the rest of the system expects: a header, the full
    text, then per-segment timestamps below."""
    full_text = (data.get("text") or "").strip()
    segments = data.get("segments") or []
    lines = [f"# Transcript ({tool_id})", "", full_text or "_(empty)_"]
    if segments:
        lines += ["", "## Segments"]
        for seg in segments:
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or 0)
            text = (seg.get("text") or "").strip()
            lines.append(f"- [{start:.1f}s – {end:.1f}s] {text}")
    return "\n".join(lines) + "\n"


def _run_mlx_whisper(tool: _tools.Tool, audio_path: Path, sidecar_dir: Path) -> ProcessorResult:
    """Invoke mlx_whisper to write transcript.json into sidecar_dir, then
    reformat into transcript.md. Both files are kept — JSON has the segment
    detail for any future consumer; markdown is the readable one."""
    try:
        result = subprocess.run(
            [
                tool.binary,
                str(audio_path),
                "--model", _DEFAULT_MODEL,
                "--output-dir", str(sidecar_dir),
                "--output-format", "json",
                "--output-name", "transcript",
                "--verbose", "False",
            ],
            capture_output=True, text=True, timeout=600, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"outputs": [], "error": f"{tool.id} failed to launch: {e}"}
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip().splitlines()
        last = err[-1] if err else "(no stderr)"
        return {"outputs": [], "error": f"{tool.id} exit {result.returncode}: {last}"}

    json_path = sidecar_dir / "transcript.json"
    if not json_path.exists():
        return {"outputs": [], "error": f"{tool.id} produced no transcript.json"}

    try:
        data = json.loads(json_path.read_text())
    except json.JSONDecodeError as e:
        return {"outputs": [], "error": f"{tool.id}: transcript.json was not valid JSON ({e})"}

    md = _format_transcript_md(data, tool.id)
    (sidecar_dir / "transcript.md").write_text(md)
    return {"outputs": ["transcript.md", "transcript.json"], "error": None}


_RUNNERS = {
    "mlx-whisper": _run_mlx_whisper,
}


@register("video", "audio", name="transcribe")
def process(artifact_path: Path, sidecar_dir: Path) -> ProcessorResult:
    audio_path = sidecar_dir / "audio.wav"
    if not audio_path.exists():
        return {"outputs": [], "error": "no audio.wav (extract didn't run, or no audio track in source)"}

    feature = next(f for f in _tools.FEATURES if f.id == _FEATURE_ID)
    tool = feature.resolve()
    if tool is None:
        recommended = feature.recommended()
        hint = f" — try: {recommended.install_command()}" if recommended else ""
        return {"outputs": [], "error": f"no transcription tool installed (see `project-notebook check`){hint}"}

    runner = _RUNNERS.get(tool.id)
    if runner is None:
        return {"outputs": [], "error": f"no runner wired up for {tool.id} yet"}

    return runner(tool, audio_path, sidecar_dir)
