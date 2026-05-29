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

### 4. Agent notification = a live SSE pipe per session.

A "long-running agent" in the Claude Code reality is *really* a session
in a terminal — alive when the user is interacting, asleep otherwise. So
registration is tied to the session: when a session starts working on a
project it arms a persistent `Monitor` running `project-notebook
register`, which holds an **open SSE pipe** to the hub over the local
socket.

That one pipe does double duty: the project is **registered for exactly
as long as the pipe is open** (no TTL, no staleness), and each artifact
ingested for it is **pushed down the pipe** as it arrives. The Monitor
turns each pushed line into an autonomous mid-conversation notification,
so a shared artifact reanimates the agent loop the instant it lands —
the user doesn't have to type. Closing the pipe (session ends)
deregisters the project automatically.

So "active project" is synonymous with "has a live session," which also
means the phone's picker only ever lists projects you can actually send
to.

### 5. Project-specific extensions via recipes.

A project can register custom processors with the hub
(`POST /api/projects/<project>/recipes`). The hub still owns
execution, caching, and event emission; the project owns the recipe
content. This avoids putting project-specific code on the agent while
letting projects extend the generic processor catalog.

## Data model

| Entity            | Fields                                                                             |
| ----------------- | ---------------------------------------------------------------------------------- |
| **Project**       | name, local path, recipe set (registered only while a session pipe is open — no TTL) |
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
| `GET`   | `/api/session?project=X&path=Y`       | Open a held-open SSE pipe: registers the project while connected, streams its artifact events, deregisters on disconnect |
| `GET`   | `/api/projects`                       | List currently-active projects (those with a live session pipe)         |

### Artifact ingestion

| Method  | Path                                  | Purpose                                                                 |
| ------- | ------------------------------------- | ----------------------------------------------------------------------- |
| `POST`  | `/api/ingest`                         | Multipart upload from any source. `{project, file}` → `{artifact_id}`   |

The hub immediately detects MIME type, dispatches default + project-recipe
processors asynchronously, and emits an `artifact_received` event.

### Agent integration

| Method  | Path                                                              | Purpose                                                              |
| ------- | ----------------------------------------------------------------- | -------------------------------------------------------------------- |
| (SSE)   | events stream over the `/api/session` pipe (above)                | Artifact events are pushed down the open session pipe, not polled    |
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
5. The hub pushes an `artifact_received` event down the project's open
   session pipe (`GET /api/session`, held open by the agent's Monitor).
6. The Monitor surfaces it as an autonomous notification mid-session —
   "New artifact: `<filename>` (`<path>`)" — and the agent reads the file
   and acts, without waiting for the user to type.
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
- **Push vs poll — resolved (push).** A persistent `Monitor` runs
  `project-notebook register`, which holds an open SSE pipe; the hub
  pushes artifact events down it, and registration is connection-bound
  (no TTL/staleness). This superseded the earlier `UserPromptSubmit`-hook
  poll.
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
