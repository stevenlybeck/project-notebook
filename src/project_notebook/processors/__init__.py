"""Generic processors that run on each ingested artifact and write sidecars
into the artifact's `<filename>.d/` directory.

Processors register themselves against a MIME family (e.g. "video", "audio") at
import time via the `register` decorator below. The hub calls `run_for_artifact`
on each new ingest, which dispatches all matching processors in registration
order — so a processor that depends on a previous one's output (e.g. Whisper
needs the WAV that ffmpeg extracts) can rely on the order.

Each processor is a sync function `(artifact_path: Path, sidecar_dir: Path) ->
ProcessorResult`. They run in a worker thread (`asyncio.to_thread`) so the
hub's event loop is never blocked by ffmpeg/Whisper. A callback fires after
every processor with the result so it can be pushed down session pipes as an
`artifact_processed` event.
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Callable, TypedDict


class ProcessorResult(TypedDict, total=False):
    outputs: list[str]      # filenames written into sidecar_dir
    error: str | None       # human-readable failure reason, if any


ProcessorFn = Callable[[Path, Path], ProcessorResult]

# MIME family ("video" / "audio" / "image" / "*") -> list of (name, fn) in
# registration order.
_registry: dict[str, list[tuple[str, ProcessorFn]]] = {}


def register(*mime_families: str, name: str | None = None):
    """Decorator: register a processor for one or more MIME families."""
    def decorator(fn: ProcessorFn) -> ProcessorFn:
        for family in mime_families:
            _registry.setdefault(family, []).append((name or fn.__name__, fn))
        return fn
    return decorator


def processors_for(mime: str | None) -> list[tuple[str, ProcessorFn]]:
    family = mime.split("/", 1)[0] if mime else ""
    return _registry.get(family, []) + _registry.get("*", [])


async def run_for_artifact(
    artifact_path: Path,
    on_result: Callable[[str, ProcessorResult], None],
) -> None:
    """Run every applicable processor for `artifact_path` in registration order,
    calling `on_result(processor_name, result)` after each completes."""
    mime, _ = mimetypes.guess_type(artifact_path.name)
    sidecar_dir = artifact_path.parent
    for proc_name, fn in processors_for(mime):
        try:
            result: ProcessorResult = await asyncio.to_thread(fn, artifact_path, sidecar_dir)
        except Exception as e:
            result = {"outputs": [], "error": f"{type(e).__name__}: {e}"}
        on_result(proc_name, result)


# Import processor modules so their @register decorators fire.
from . import ffmpeg  # noqa: E402, F401
from . import whisper  # noqa: E402, F401
