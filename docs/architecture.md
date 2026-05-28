# Project Notebook — Architecture

> Give your coding assistant the rest of your sensory bandwidth.

This is the architecture of the artifact pipeline: how files travel from
your phone (or any other source) through the hub and into the active
project's coding-assistant conversation, *with appropriate context
attached*.

`PLAN.md` covers packaging/distribution (CLI, pip install, hub
daemonization). This doc covers what the system *does* once it's running.

## Three components

```
┌────────────────────┐       ┌────────────────────┐       ┌────────────────────┐
│ iOS Share          │       │ Hub                │       │ Project Agent      │
│ Extension          │       │ (long-running      │       │ (Claude Code       │
│ (or any source     │ POST  │  service)          │  poll │  session, IDE      │
│  that POSTs to     ├──────►│  • storage         │◄──────┤  plugin, MCP       │
│  /api/ingest)      │       │  • generic         │       │  client, etc.)     │
│                    │       │    processing      │       │  • injects new     │
│                    │       │  • events          │  POST │    artifacts as    │
│                    │       │  • annotations     │◄──────┤    context         │
└────────────────────┘       └────────────────────┘       │  • interprets in   │
                                                           │    project context │
                                                           │  • posts back      │
                                                           │    annotations     │
                                                           └────────────────────┘
```

## Core design decisions

### 1. Hub does *generic* processing; agent does *contextual* interpretation.

The hub runs everything that produces the same output regardless of
which project asked: format normalisation, transcription, OCR, frame
sampling, embedding, metadata extraction, etc. The agent does
everything that needs to know what the project is trying to accomplish:
"what does this transcript imply for the bug we're debugging," "is this
schematic the second iteration or a different one," etc.

The split keeps the agent's working environment minimal (it doesn't
need ffmpeg, Whisper, libheif, etc. installed locally), enables hub
caching by content hash across artifacts and projects, lets the hub
move to a beefier machine if needed, and makes processing async with
respect to the agent's wakefulness.

| Layer | What                                                                          | Where |
| ----- | ----------------------------------------------------------------------------- | ----- |
| 0     | Raw bytes                                                                     | Hub   |
| 1     | Format normalisation (HEIC→JPEG, MOV→MP4, audio extraction)                   | Hub   |
| 2     | Feature extraction (Whisper transcript, OCR text, frame samples, embeddings, metadata) | Hub   |
| 3     | Project-aware interpretation                                                  | Agent |

**Decision rule for any new processor:** *default to hub; only put
something on the agent if it genuinely requires project intent to
produce its output.*

### 2. The hub is the archive — not an inbox.

Artifacts arrive on the hub and stay on the hub. They accumulate
processed outputs, agent annotations, and project assignments over
their lifetime. There is no separate "archive" location, because there
is no inbox→archive transition; nothing is in transit. Retention is
indefinite by default.

### 3. Annotations, not archive.

When an agent processes an artifact in conversation, it can post the
relevant turns and any conclusions back to the hub as an *annotation*.
Annotations become part of the artifact's permanent record on the hub.
This is the only contextual data the hub stores; the artifact and its
processed outputs are otherwise project-agnostic.

### 4. Agent notification = polling on user action, for now.

A "long-running agent" in the Claude Code reality is *really* a
session in a terminal somewhere — alive when the user is interacting,
asleep otherwise. Live push notifications matter only during active
sessions; while the session is asleep, processing happens on the hub
regardless and is ready when the agent next wakes.

The simplest mechanism that fits this model: the agent uses a
`UserPromptSubmit` hook to poll the hub on every prompt for new
artifacts. The injection becomes part of the user's next turn. Push
mechanisms (SSE, MCP push) are upgrades for later.

### 5. Project-specific extensions via recipes.

A project can register custom processors with the hub
(`POST /api/projects/<project>/recipes`). The hub still owns
execution, caching, and event emission; the project owns the recipe
content. This avoids putting project-specific code on the agent while
letting projects extend the generic processor catalog.

## Data model

| Entity            | Fields                                                                             |
| ----------------- | ---------------------------------------------------------------------------------- |
| **Project**       | name, local path, registered-at, ttl, recipe set                                   |
| **Artifact**      | id (sha256), original filename, mime type, size, source, projects[], received-at, processing-status |
| **ProcessedOutput** | artifact-id, processor name, version, output path(s), produced-at, status        |
| **Annotation**    | artifact-id, agent-id, session-id, kind (e.g. "context", "conclusion"), content (markdown), turns[], created-at |
| **Event**         | id, type ("artifact_ready", "processing_progress", "annotation_added"), artifact-id, project, timestamp, payload |

The same artifact (identified by content hash) can belong to multiple
projects without duplication. Each project's view of an artifact is a
*pointer* into the shared store plus its own annotations.

## Storage layout (on the hub host)

```
<hub_root>/
├── projects/
│   └── <project-name>/
│       ├── manifest.json              # registration, recipes, retention policy
│       └── artifacts/<sha256>          # symlinks/pointers to shared store
└── artifacts/
    └── <sha256-prefix>/<sha256>/
        ├── original.<ext>
        ├── metadata.json              # source, MIME, received-at, projects[]
        ├── processed/
        │   ├── transcript.md
        │   ├── thumbnail.jpg
        │   ├── frames/
        │   └── …
        └── annotations/
            └── <timestamp>__<session-id>.md
```

Storage is content-addressed: identical files share one entry on disk;
project membership is a pointer.

## API surface

### Registration & lifecycle

| Method  | Path                                  | Purpose                                                                 |
| ------- | ------------------------------------- | ----------------------------------------------------------------------- |
| `POST`  | `/api/register`                       | Register a project. `{project, path, ttl}` → `{status, project}`        |
| `POST`  | `/api/unregister`                     | Remove a project registration                                           |
| `GET`   | `/api/projects`                       | List registered projects                                                |

### Artifact ingestion

| Method  | Path                                  | Purpose                                                                 |
| ------- | ------------------------------------- | ----------------------------------------------------------------------- |
| `POST`  | `/api/ingest`                         | Multipart upload from any source. `{project, file}` → `{artifact_id}`   |

The hub immediately detects MIME type, dispatches default + project-recipe
processors asynchronously, and emits an `artifact_received` event.

### Agent integration

| Method  | Path                                                              | Purpose                                                              |
| ------- | ----------------------------------------------------------------- | -------------------------------------------------------------------- |
| `GET`   | `/api/events?project=X&since=<timestamp>`                         | Poll for events since a timestamp. Returns artifacts with processing status. |
| `GET`   | `/api/artifact/<id>`                                              | Artifact metadata + list of processed outputs + annotations          |
| `GET`   | `/api/artifact/<id>/original`                                     | Download original                                                    |
| `GET`   | `/api/artifact/<id>/processed/<kind>`                             | Download a specific processed output (e.g. `transcript.md`)          |
| `POST`  | `/api/artifact/<id>/annotate`                                     | Attach a contextual annotation. `{kind, content, turns, session_id}` |

### Project-specific extension

| Method  | Path                                                              | Purpose                                                              |
| ------- | ----------------------------------------------------------------- | -------------------------------------------------------------------- |
| `POST`  | `/api/projects/<project>/recipes`                                 | Register a custom processor for this project                         |

## Default generic processors

| MIME family    | Processors                                                                                       |
| -------------- | ------------------------------------------------------------------------------------------------ |
| `audio/*`      | Whisper transcript, waveform sample, audio metadata                                              |
| `video/*`      | h.265 transcode, audio extraction (→ audio pipeline), evenly-spaced frame samples, video metadata |
| `image/heic`   | HEIC→JPEG normalize, then dispatch as `image/jpeg`                                               |
| `image/*`      | OCR (tesseract), thumbnail, image embedding, EXIF metadata                                       |
| `application/pdf` | text extraction, per-page render                                                              |
| `text/*`       | encoding detection, plain-text copy, line-count metadata                                         |
| `*` (fallback) | metadata only                                                                                    |

Processors are registered as named functions; each takes `(artifact_path,
output_dir)` and returns the produced output paths plus a status. Each
processor declares its dependencies (ffmpeg, whisper model, etc.) so
the hub can fail loudly on missing tools rather than silently skipping.

## Lifecycle: artifact arrival end-to-end

1. Some source (iOS extension, CLI, scheduled job) `POST`s to
   `/api/ingest` with a project name and the file.
2. Hub computes content hash. If the artifact is already in the shared
   store, it just adds a pointer for this project. Otherwise it stores
   the original and writes `metadata.json`.
3. Hub looks up `mime` → list of default processors, plus the project's
   recipes. Schedules each as a job. Emits `artifact_received` event.
4. Each processor runs asynchronously, writes to `processed/<kind>`,
   emits a `processing_progress` event on completion (or failure).
5. When the project agent next wakes, its `UserPromptSubmit` hook
   polls `GET /api/events?project=X&since=<last-poll>` and gets the
   list of new artifacts plus their current processing status.
6. The hook injects a system-reminder block into the next user turn:
   "An artifact arrived: `<filename>`. Processed outputs available:
   `[transcript.md, thumbnail.jpg, ...]`. Path: `<api endpoint>`."
7. The agent fetches whichever processed outputs are useful, discusses
   them with the user in the conversation, and proposes
   project-specific actions (edits, summaries, tasks).
8. When the agent reaches a conclusion worth keeping, it
   `POST`s to `/api/artifact/<id>/annotate` with the relevant turns and
   the conclusion. The annotation becomes part of the artifact's
   permanent record on the hub.

## Open questions

- **Multiple agents per project.** If two Claude Code sessions are
  registered for the same project, who owns a given artifact? My
  current bias: the most-recently-active session sees it first; others
  see a "this was already handled in <session>" note next turn. Not
  yet final.
- **Annotation deduplication.** If the same artifact is discussed in
  multiple sessions, the hub accumulates many annotations. Worth
  surfacing a "summary of all annotations" view, eventually.
- **Push vs poll.** This doc assumes the agent polls. The
  infrastructure for SSE / MCP push exists in principle and would lower
  latency; defer until the polling experience proves insufficient.
- **Privacy when the hub leaves localhost.** Today the hub is local.
  An eventual cloud-offload mode raises real privacy concerns
  (Whisper-as-a-service is sending your audio to someone). Keep
  cloud-offload opt-in per project, never the default.
- **Retention policy.** Indefinite is fine for personal use; if the hub
  ever has shared/disk-constrained backends, a per-project policy
  (size cap, age cap) becomes load-bearing.

## What this replaces in the current code

- Per-project `artifacts/` directories under each project's repo →
  shared content-addressed store on the hub host.
- Manual "drop into folder, process later" workflow → hub-side async
  processing pipeline triggered by ingest.
- The retroactive session-log context-extraction idea →
  agent-pushed annotations during the live conversation.
- The notion of an explicit "archive" step → there isn't one.
