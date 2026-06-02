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
  `uv tool install project-notebook`); if you're running ad-hoc from a local
  wheel, substitute `uvx --from /path/to/wheel project-notebook register "$0"`.
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
4. Once you've absorbed what just arrived, write annotations back — see the
   next section.

## Annotation pass

Extraction (ffmpeg, Whisper) writes the mechanical facts into `meta.yaml`:
codec, duration, dimensions, transcript. *You* — with this conversation's
context — write what it **means**. That's what makes an artifact discoverable
later. Without your pass, `meta.yaml` is just dimensions.

Run `project-notebook annotate <sidecar_dir>` and pipe a JSON object on stdin:

```bash
project-notebook annotate ~/.project-notebook/artifacts/myproj/IMG_8150.MOV.d <<'JSON'
{
  "summary": "voice memo walking through the I²C pull-up swap",
  "relevance": "captures the exact reasoning behind dropping 4.7kΩ to 2.2kΩ — relevant to the BME280 sensor work we've been on this session",
  "session_context": "We were debugging dropped reads at 400kHz; this memo records the hypothesis and the resistor swap that fixed it.",
  "key_moments": [
    {"time": 12.4, "label": "logic analyzer trace settling after the swap"},
    {"time": 28.0, "label": "soldering iron close-up on the new pull-up"}
  ],
  "tags": ["i2c", "bme280", "debugging"]
}
JSON
```

Fields (all optional, include what's useful):

- `summary` — one line: what *is* this artifact?
- `relevance` — how it relates to what we're working on right now
- `session_context` — paragraph capturing the moment in our work that this
  artifact dropped into
- `key_moments` — list of `{"time": <seconds>, "label": "..."}` for video and
  audio; omit for images
- `tags` — short keywords for later search

**When to annotate:**

- **Image** (no `Processed` events expected): annotate right after `New artifact`.
- **Video / audio**: annotate after the `Processed: … via transcribe …`
  event — that's when you have the transcript to ground the annotations.

Re-running overwrites the `annotations` key, so it's safe to revise later in
the session if you learn something new.

The session and its pipe close when the Monitor is stopped or the session
ends; the hub deregisters the project automatically.
