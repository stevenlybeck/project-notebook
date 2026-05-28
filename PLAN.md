# Project Notebook — Packaging Plan

## Goal

Make project-notebook installable via pip/uv as a developer tool. The intended install is `uv tool install project-notebook` (or `pipx install project-notebook`); the CLI auto-starts the hub, registers projects, and pairs phones. No native GUI in v1 — a menu-bar icon may ship later as a separate package.

## Distribution shape

This sits in the same convention as Jupyter, Streamlit, and MLflow: a pip-installable Python tool that runs a local HTTP server. The audience is Claude Code users who already have a Python toolchain, so a menu-bar app would be polish, not a prerequisite.

## Architecture

```
uv tool install project-notebook
                  │
                  ▼
         `notebook register`   ← CLI command
                  │
                  ├── Is hub running on :9999?
                  │     No → start it in background (LaunchAgent or detached process)
                  │     Yes → use existing
                  │
                  └── POST /api/register {project, path, ttl}
                        │
                        ▼
                  Project appears in iOS Share Extension
```

## CLI Commands

- `notebook register [name] [--ttl 7200]` — ensures hub is running, registers project
- `notebook hub` — explicitly start the hub (foreground)
- `notebook status` — show registered projects, paired devices, recent uploads
- `notebook unregister` — remove project
- `notebook pair` — print a QR (in the terminal) for the iOS app to scan
- `notebook devices` — list paired devices, revoke tokens
- `notebook install-skill` — copy the bundled Claude skill into `~/.claude/skills/`
- `notebook install-agent` — install the LaunchAgent plist for auto-start on login (opt-in)

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
│       ├── cli.py          # CLI entry point
│       ├── pairing.py      # QR + token mint/verify
│       └── skill/          # bundled Claude skill (copied on install-skill)
├── ios/                    # iOS app (not part of the package)
```

### 2. Hub lifecycle

- `notebook register` checks if :9999 is already responding
- If not, spawns `notebook hub` as a background process (detached, writes PID to `~/.project-notebook/hub.pid`)
- `notebook install-agent` is the opt-in path to a launchd plist for auto-start on login — `pip install` does not write LaunchAgents as a side effect

### 3. Claude skill ships with the package

The skill lives inside the package at `src/project_notebook/skill/`. `notebook install-skill` copies it to `~/.claude/skills/notebook-register/` (or `notebook register` does this on first run). Upgrading the package upgrades the skill. The skill itself is a one-liner that calls `notebook register $0`.

### 4. Secure pairing

LAN-only, bearer-token model — no TLS in v1, threat model is "trusted home network" and documented as such.

- `notebook pair` mints a short-lived pairing code + long-lived device token; renders a QR with `{lan_url, pairing_code}` in the terminal (using `qrcode` or `segno`)
- iOS scans, POSTs the pairing code to `lan_url/api/pair`, receives the device token, stores it in the Keychain
- Every subsequent iOS request carries the device token as a bearer header; hub rejects unknown tokens
- mDNS/Bonjour advertises `_notebook._tcp.local` so the LAN URL doesn't need to bake in an IP that changes
- `notebook devices` lists paired devices and revokes tokens

Pairing sits inside a broader three-plane access model (local commands over a Unix socket, phone API over the LAN, web UI on loopback). See [docs/security.md](docs/security.md) for the full model and rationale.

## Workstream C — Secure pairing + plane separation

Task checklist (build after A+B; depends on B's persisted state for device tokens):

- [ ] **Split listeners** — one process, three aiohttp sites: `UnixSite` (`hub.sock`, mode `0600`) for local commands; `TCPSite` `0.0.0.0:9999` for the phone API; `TCPSite` `127.0.0.1` for the web UI. Move each route onto the plane where it belongs.
- [ ] **Fix path traversal in `ingest`** — destination is currently `artifacts_dir / filename` from client input; use `Path(filename).name` to strip directory components. Live bug today, independent of pairing.
- [ ] **Device registry** — persist device tokens in `~/.project-notebook/` (extends B), with mint/verify/revoke.
- [ ] **`pair` flow** — `pairing.py` mints a single-use, ~60–120s pairing code + long-lived device token; `notebook pair` renders the QR; `/api/pair` exchanges code → token.
- [ ] **Bearer-token middleware** — on the phone-API listener only; reject unknown/revoked tokens.
- [ ] **Host-header check** — on the web-UI listener, reject non-`localhost` Host to block DNS rebinding.
- [ ] **CLI over the socket** — `register`/`status`/etc. talk to `hub.sock` via `aiohttp.UnixConnector` (or `httpx` `uds=`).
- [ ] **mDNS/Bonjour** — advertise `_notebook._tcp.local` for LAN discovery.
- [ ] **iOS** — see section 5.

### 5. iOS app changes

- First-launch flow: scan QR → store device token in Keychain
- All requests to the hub gain an `Authorization: Bearer <token>` header
- Discovery via Bonjour, falling back to a manually entered URL

## Deferred (post-v1)

- **Menu-bar app** — separate `project-notebook-menubar` package, or a native `.app`. Decide when v1 is in use and the pain of "is the hub running?" becomes concrete.
- **HTTPS on LAN** — only worth it if the trusted-LAN threat model stops being adequate.
- **QuickShare ingestion** — investigate using QuickShare (Google's cross-platform Nearby Share) as an alternate transport. Could provide a zero-config "send to Mac" path that bypasses LAN/IP/token plumbing entirely, and would extend reach beyond iOS to Android and ChromeOS. Open questions: does the macOS QuickShare client expose a programmable hook, or would the hub need to watch a drop folder?
- **iOS auto-bump build number** — set `VERSIONING_SYSTEM = "apple-generic"` in pbxproj and add a pre-archive script that sets `CURRENT_PROJECT_VERSION` to either a Unix timestamp (`date +%s`) or `git rev-list --count HEAD`. Apple rejects re-uploads with the same `CFBundleVersion` within a marketing version, so this removes the "remember to bump the build number" tax. Defer until manual bumping in the Xcode UI becomes annoying.
- **In-depth architecture review** — once the core features (workstreams A–D) are implemented, do a holistic pass over the whole system (hub/agent split, content-addressed storage, the three security planes, API surface, CLI ergonomics) for consistency and simplification before the design ossifies. Best done with working code in hand, not up front.
- **Port collision handling** — the default hub port (9999) can already be taken (e.g. DaVinci Resolve's `fuscript` listens there). Decide how the hub chooses a port: pick a less collision-prone default, and/or detect a busy port at startup and either fail clearly or auto-select a free one. Key constraint: whatever the hub binds must be agreed on by the *other planes* — the CLI, the bundled skill, and the iOS app all need to find it — so the chosen port has to be persisted in `~/.project-notebook/` (and surfaced to the phone via mDNS, see workstream C), not just picked ephemerally. `PROJECT_NOTEBOOK_PORT` is the current manual workaround.

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
