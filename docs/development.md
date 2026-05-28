# Project Notebook — Development

How to run and test the hub/CLI locally.

## Run the hub from source

```bash
uv run project-notebook hub        # foreground, current source
```

This starts all three listeners (see [security.md](security.md)): the
local Unix socket, the phone API on `PROJECT_NOTEBOOK_PORT`, and the web
UI on `PROJECT_NOTEBOOK_WEB_PORT`. In another shell, drive it with
`uv run project-notebook register` / `status` / `pair` / `devices`.

`register` also auto-spawns the hub if one isn't already running, so for
most iteration you can just run `uv run project-notebook register`.

## Iterate with `uv run`, not `uvx` — uvx caches by version

For day-to-day iteration use `uv run` (an editable install that always
reflects current source). **Do not** iterate with `uvx --from dist/*.whl`:
uvx caches its ephemeral environment keyed by package **version**, so
rebuilding the same `0.1.0` wheel does *not* invalidate the cache and uvx
silently runs stale code.

This is not hypothetical — it bit us once: the bearer-auth middleware
appeared absent (ingest returned 200 with no token) purely because uvx
served a pre-middleware build. The source was correct.

If you must re-test a rebuilt same-version wheel via uvx, bump the
version or pass `--refresh` / `--reinstall`.

## Environment overrides

Useful for running an isolated instance that won't touch your real state,
skills, or ports:

| Variable | Controls | Default |
| -------- | -------- | ------- |
| `PROJECT_NOTEBOOK_HOME` | state dir (`hub.sock`, `state.json`, `hub.log`) | `~/.project-notebook` |
| `PROJECT_NOTEBOOK_PORT` | phone API (LAN) port | `9999` |
| `PROJECT_NOTEBOOK_WEB_PORT` | web UI (loopback) port | `9877` |
| `CLAUDE_CONFIG_DIR` | where `install-claude-code-skill` writes | `~/.claude` |

Note: `9999` collides with DaVinci Resolve's `fuscript` on some machines;
set `PROJECT_NOTEBOOK_PORT` when testing (see the port-collision item in
[PLAN.md](../PLAN.md)).

## Isolated test pattern

```bash
export PROJECT_NOTEBOOK_HOME=$(mktemp -d)
export PROJECT_NOTEBOOK_PORT=9876 PROJECT_NOTEBOOK_WEB_PORT=9878
SOCK="$PROJECT_NOTEBOOK_HOME/hub.sock"

uv run project-notebook hub >/dev/null 2>&1 &      # background hub
until [ -S "$SOCK" ]; do sleep 0.2; done           # wait for the socket

# local plane (Unix socket)
curl --unix-socket "$SOCK" -X POST http://localhost/api/pair/new

# phone plane (LAN port) — ingest requires a device token
curl -H "Authorization: Bearer <token>" \
  -X POST http://127.0.0.1:9876/api/ingest -F project=<name> -F file=@some.txt

lsof -ti tcp:9876 | xargs kill                      # stop the hub
```

## Validate the built artifact

The editable install can hide packaging bugs (e.g. a bundled file that
isn't declared as package data). Before publishing, prove the wheel is
complete:

```bash
uv build
unzip -l dist/*.whl | grep skill        # confirm bundled data is present
uvx --from dist/*.whl project-notebook --help
```
