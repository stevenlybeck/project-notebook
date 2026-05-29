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

- **command:** `uvx project-notebook register "$0"` — omit the argument to use
  the current directory's name.
- **persistent:** `true`
- **description:** `artifacts shared to <project>`

The command holds an open pipe to the hub: the project stays registered while it
runs, and it prints one line per shared artifact — `New artifact: <filename>
(<path>)`. Each line arrives as a notification.

**When an artifact notification arrives:** read the file at the given path and
use it in the context of whatever we're working on (e.g. a screenshot of a bug,
a photo of hardware, a voice memo). Don't wait to be asked — that's the point.

When the Monitor is stopped or the session ends, the pipe closes and the hub
deregisters the project automatically.
