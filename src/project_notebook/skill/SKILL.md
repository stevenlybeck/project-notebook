---
name: notebook-register
description: Register the current project with the Project Notebook hub server for artifact ingestion
user-invocable: true
allowed-tools: Bash(project-notebook:*)
argument-hint: "[project-name] [ttl-seconds]"
---

# Register Project with Notebook Hub

Register the current project with the Project Notebook hub so the iOS Share
Extension can send artifacts to it. The hub starts automatically if it
isn't already running.

## Arguments

- `$0` — Project name (optional; defaults to the current directory name)
- `$1` — TTL in seconds (optional; defaults to 7200 = 2 hours)

## Task

1. Run `project-notebook register` using the Bash tool. Pass `$0` as the
   project name if provided, and `--ttl $1` if a TTL is provided.
2. Report the result to the user.

## Examples

```bash
# Use current directory name, default TTL
project-notebook register

# Explicit name and TTL
project-notebook register "<name>" --ttl <seconds>
```
