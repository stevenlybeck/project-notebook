---
name: notebook-register
description: Register the current project with the Project Notebook hub server for artifact ingestion
user-invocable: true
allowed-tools: Bash(curl:*)
argument-hint: "[project-name] [ttl-seconds]"
---

# Register Project with Notebook Hub

Register the current project with the hub server so the iOS Share Extension can send artifacts to it.

## Arguments

- `$0` — Project name (optional, defaults to current directory name)
- `$1` — TTL in seconds (optional, defaults to 7200 = 2 hours)

## Current state

- Hub server: http://localhost:9999

## Task

1. Use the project name from `$0`, or fall back to the name of the current working directory.
2. Use the TTL from `$1`, or default to 7200 seconds (2 hours).
3. Use the Bash tool to POST to `http://localhost:9999/api/register` with JSON body containing `project` (name), `path` (current working directory), and `ttl`.
4. Report the result to the user.

## Example

```bash
curl -s -X POST http://localhost:9999/api/register \
  -H "Content-Type: application/json" \
  -d '{"project": "<name>", "path": "<pwd>", "ttl": <ttl>}'
```
