"""External tool registry: which command-line tools each feature uses, how to
detect them, and how to install them per-platform.

Processors will (post-refactor) shell out to the tools listed here rather than
importing optional Python libraries. `project-notebook check` reports on
what's installed without doing any work — it's the passive view that
`project-notebook setup` will later build on.

Two concepts:
- **Tool**: an external binary on PATH. May require helper binaries (ffmpeg
  comes with ffprobe — both needed for the same job, declared as one tool).
- **Feature**: a user-facing capability backed by one or more interchangeable
  tools. The first installed compatible tool (by priority) is what gets used.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from typing import Optional


def detect_platform() -> str:
    """Return e.g. 'darwin-arm64', 'darwin-x86_64', 'linux-x86_64'.

    Used to filter tools that only make sense on certain hardware
    (mlx-whisper, for example, is Apple Silicon only).
    """
    sys_name = platform.system().lower()
    mach = platform.machine().lower()
    # Normalize the common machine-name aliases so platform constraints can
    # be written in one canonical form regardless of how Python's host reports.
    if mach == "aarch64":
        mach = "arm64"
    if mach == "amd64":
        mach = "x86_64"
    return f"{sys_name}-{mach}"


def os_family() -> str:
    """Just 'darwin' / 'linux' / 'windows'; used to pick per-OS install hints."""
    return platform.system().lower()


@dataclass
class Tool:
    """An external command-line program a processor can shell out to.

    A tool is considered installed iff `binary` (and every entry in
    `extra_binaries`, if any) is on the user's PATH. Multi-binary tools
    (ffmpeg ships with ffprobe; both are needed for the extract job) belong
    in one `Tool` so the feature machinery can treat the suite as a unit.
    """

    id: str
    binary: str
    install_hint: str | dict[str, str]
    platforms: Optional[tuple[str, ...]] = None  # None = compatible everywhere
    priority: int = 5                             # higher wins among alternates
    extra_binaries: tuple[str, ...] = ()
    notes: str = ""

    def supported_here(self) -> bool:
        return self.platforms is None or detect_platform() in self.platforms

    def installed(self) -> bool:
        if shutil.which(self.binary) is None:
            return False
        return all(shutil.which(b) is not None for b in self.extra_binaries)

    def install_command(self) -> str:
        """Return the install hint for the current platform, or '' if none."""
        if isinstance(self.install_hint, str):
            return self.install_hint
        return self.install_hint.get(os_family(), "")


@dataclass
class Feature:
    """A user-visible capability. Tools within a feature are alternates:
    any one being installed turns the feature on. `resolve()` picks the
    highest-priority installed compatible tool — what the processor would
    use at runtime."""

    id: str
    name: str
    description: str
    tools: tuple[Tool, ...]

    def compatible_tools(self) -> list[Tool]:
        return [t for t in self.tools if t.supported_here()]

    def installed_tools(self) -> list[Tool]:
        return [t for t in self.compatible_tools() if t.installed()]

    def resolve(self) -> Optional[Tool]:
        installed = sorted(self.installed_tools(), key=lambda t: -t.priority)
        return installed[0] if installed else None

    def recommended(self) -> Optional[Tool]:
        compat = sorted(self.compatible_tools(), key=lambda t: -t.priority)
        return compat[0] if compat else None

    def is_on(self) -> bool:
        return self.resolve() is not None


# ============================================================================
# Tool registry
# ============================================================================

FFMPEG = Tool(
    id="ffmpeg",
    binary="ffmpeg",
    extra_binaries=("ffprobe",),
    install_hint={
        "darwin": "brew install ffmpeg",
        "linux": "apt install ffmpeg   # or your distro's equivalent",
    },
    priority=10,
    notes="extracts metadata, audio, and a preview frame from media files",
)

MLX_WHISPER = Tool(
    id="mlx-whisper",
    binary="mlx_whisper",
    install_hint="uv tool install mlx-whisper",
    platforms=("darwin-arm64",),
    priority=10,
    notes="fast on Apple Silicon",
)

WHISPER_CPP = Tool(
    id="whisper-cpp",
    binary="whisper-cli",
    install_hint={
        "darwin": "brew install whisper-cpp",
        "linux": "build from https://github.com/ggml-org/whisper.cpp",
    },
    priority=7,
    notes="cross-platform native binary",
)

OPENAI_WHISPER = Tool(
    id="openai-whisper",
    binary="whisper",
    install_hint="uv tool install openai-whisper",
    priority=4,
    notes="pure Python; slow but runs anywhere",
)


# ============================================================================
# Feature registry
# ============================================================================

FEATURES: tuple[Feature, ...] = (
    Feature(
        id="media_extract",
        name="Video metadata & preview frames",
        description="Pulls metadata, a preview frame, and the audio track from media files.",
        tools=(FFMPEG,),
    ),
    Feature(
        id="transcription",
        name="Audio transcription",
        description="Transcribes voice memos and the audio in videos.",
        tools=(MLX_WHISPER, WHISPER_CPP, OPENAI_WHISPER),
    ),
)
