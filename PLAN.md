# Project Notebook — Packaging Plan

## Goal

Make project-notebook installable via pip/uv with a CLI that auto-starts the hub and registers projects. The Claude skill becomes: "install this Python library and use it to claim a project name."

## Architecture

```
pip/uv install project-notebook
                  │
                  ▼
         `notebook register`   ← CLI command
                  │
                  ├── Is hub running on :9999?
                  │     No → start it in background (daemonize)
                  │     Yes → use existing
                  │
                  └── POST /api/register {project, path, ttl}
                        │
                        ▼
                  Project appears in iOS Share Extension
```

## CLI Commands

- `notebook register [name] [--ttl 7200]` — ensures hub is running, registers project
- `notebook hub` — explicitly start the hub
- `notebook status` — show registered projects and active uploads
- `notebook unregister` — remove project

## What Needs to Change

### 1. Package structure

Move hub.py into a proper package with CLI entry points:

```
project-notebook/
├── pyproject.toml          # package metadata + [project.scripts]
├── src/
│   └── project_notebook/
│       ├── __init__.py
│       ├── hub.py          # the server (moved here)
│       └── cli.py          # CLI entry point
├── ios/                    # iOS app (not part of the package)
└── .claude/
    └── skills/
        └── notebook-register/  # skill just calls `notebook register`
```

### 2. Hub lifecycle

- `notebook register` checks if :9999 is already responding
- If not, spawns `notebook hub` as a background process (detached, writes PID to `~/.project-notebook/hub.pid`)
- Hub stays alive until explicitly stopped or machine restarts
- Could also install as a launchd service for auto-start on login

### 3. Claude skill simplifies

The skill becomes a one-liner that runs `notebook register $0`. The CLI handles everything (hub startup, registration, error handling).

### 4. iOS app unchanged

Already fetches project list from hub at configured URL. No changes needed.

## Artifact Processing

When an artifact arrives, the system should extract information and annotate it using the context of the active session.

### Extraction pipeline

Each artifact type has a set of extraction skills:

- **Video**: Whisper transcription (word-level timestamps), keyframe extraction at scene changes
- **Audio**: Whisper transcription (word-level timestamps)
- **Image**: No extraction needed (the file is the content)

### Annotation

After extraction, the artifact and its extracted data get annotated using Claude vision/text:

- **What's in this artifact?** — structured description of what's visible/audible
- **How does it relate to the project?** — using the conversation context from the active session
- **Key moments** (video/audio) — timestamps of important points linked to transcript

The key insight: the active Claude Code session has the project context. When an artifact arrives, the session knows "we're debugging I2C pull-ups" and can annotate a breadboard photo accordingly, rather than just seeing "a breadboard with wires."

### Processing flow

```
Artifact arrives at hub
        │
        ▼
Hub notifies the session (via /api/uploads polling or notification)
        │
        ▼
Session runs extraction skills:
  - whisper for audio/video → transcript + timestamps
  - ffmpeg for video → keyframes
        │
        ▼
Session annotates using Claude vision + conversation context:
  - "This photo shows the BME280 sensor with 2.2kΩ pull-ups
     we just swapped in for the I2C fix"
        │
        ▼
Metadata written as sidecar YAML:
  artifacts/
    IMG_4521.mp4
    IMG_4521.meta.yaml    ← transcript, annotations, context
    IMG_4521.keyframes/   ← extracted frames
```

### Sidecar metadata format

```yaml
id: 2026-04-01-001
source_file: IMG_4521.mp4
project: esp32-sensor-array
ingested: 2026-04-01T14:30:00Z
type: video
duration: 273.5

transcript:
  - time: 0.0
    text: "Okay so the issue was the pull-up resistors..."
    end_time: 2.3
  - time: 2.3
    text: "I swapped the 4.7k for 2.2k and now it's stable"
    end_time: 5.1

annotations:
  - time: 3.2
    label: "BME280 breakout board with new 2.2kΩ pull-ups"
    context: "Part of I2C debugging session — replaced pull-ups to fix 400kHz communication"
  - time: 8.0
    label: "Logic analyzer showing clean I2C waveform"

session_context: >
  Debugging I2C communication between ESP32 and BME280 sensor.
  Previous 4.7kΩ pull-ups caused signal integrity issues at 400kHz.
  Swapped to 2.2kΩ, which resolved the problem.

tags: [debugging, i2c, hardware, bme280]
```

### Skills to build

- `/ingest [file]` — run the full extraction + annotation pipeline on an artifact
- `/transcribe [file]` — just run Whisper transcription
- `/annotate [file]` — just run vision annotation with session context
- `/search [query]` — search across all artifact transcripts and annotations (SQLite FTS5)

### Dependencies

- `mlx-whisper` or `whisper.cpp` — local transcription on Apple Silicon
- `ffmpeg` — keyframe extraction, audio extraction from video
- Claude API — vision annotation (or use the active session itself)

## Open Questions

- **Package name**: `project-notebook`? `notebook`? Something else?
- **Hub persistence**: background process with PID file vs launchd plist for auto-start on login?
- **Skill distribution**: bundled in the package (installed to `~/.claude/skills/`) or stay project-local?
