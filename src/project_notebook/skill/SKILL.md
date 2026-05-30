---
name: notebook-register
description: Open a live Project Notebook session — register the current project and stream artifacts shared from your phone into this conversation
user-invocable: true
argument-hint: "[project-name]"
---

# Open a Project Notebook session

Register the current project with the Project Notebook hub and stream artifacts
shared from your phone directly into this conversation as they arrive. The
project is registered for exactly as long as this session's pipe is open — no
TTLs, no staleness.

## Arguments

- `$0` — Project name (optional; defaults to the current directory name)

## Task

Start a **persistent Monitor** running the registration pipe:

- **command:** `project-notebook register "$0"` — omit the argument to use
  the current directory's name. Assumes `project-notebook` is on PATH (i.e.
  `uv tool install project-notebook[whisper]`); if you're running ad-hoc from
  a local wheel, substitute `uvx --from /path/to/wheel project-notebook register "$0"`.
- **persistent:** `true`
- **description:** `artifacts shared to <project>`

The command holds an open pipe to the hub: the project stays registered while
it runs, and it prints lines of two kinds:

- **`New artifact: <filename>  (<path>)`** — a file just arrived from the
  phone. The path points inside a per-artifact subdirectory in the hub's
  store: `~/.project-notebook/artifacts/<project>/<filename>.d/<filename>`.
  The artifact and all its sidecars live together there; your project repo
  isn't touched.
- **`Processed: <filename> via <processor> -> <output1>, <output2>, … (in <sidecar_dir>)`** —
  a processor finished writing sidecars next to that file. Common sidecars are
  `meta.yaml` (format/duration/dimensions), `audio.wav` (extracted audio),
  `poster.jpg` (mid-frame for video), `transcript.md` (Whisper transcription
  with timestamps).

## When a notification arrives

Don't wait to be asked — that's the point.

1. On **`New artifact`**: read the file at the given path so you have its raw
   content. Note the sidecar directory (the parent of the path) — more will
   often arrive there.
2. On **`Processed`**: read each named sidecar file. `meta.yaml` tells you what
   the artifact *is*; `transcript.md` is usually the most useful for
   audio/video and lets you answer questions about what was said; `poster.jpg`
   is a single still that's quick to look at.
3. Use everything you have to react in the context of what we're working on —
   for example, a photo of a breadboard during an I²C debugging session,
   a voice memo describing a bug, a screenshot of a stack trace.

The session and its pipe close when the Monitor is stopped or the session
ends; the hub deregisters the project automatically.
