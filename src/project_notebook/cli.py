"""Project Notebook CLI.

Local interaction with the hub goes through these subcommands; the
subcommands that touch hub state are thin clients that call the hub's
HTTP API over loopback, so the hub remains the single source of truth.
"""

import argparse
import asyncio
import importlib.resources as resources
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

import aiohttp


def _state_dir() -> Path:
    return Path(os.environ.get("PROJECT_NOTEBOOK_HOME", Path.home() / ".project-notebook"))


def _sock_path() -> Path:
    return _state_dir() / "hub.sock"


# Local CLI talks to the hub over a Unix domain socket. With aiohttp's
# UnixConnector the transport IS the socket; the URL's host/port are ignored
# at the wire level (HTTP requires *some* host, so we use this placeholder).
# The aiohttp docs cover the connector but not URL construction — see:
#   https://docs.aiohttp.org/en/stable/client_advanced.html
#   https://github.com/aio-libs/aiohttp/issues/11324  (open issue asking for
#     better docs / base_url support for exactly this case)
_HUB_URL_BASE = "http://localhost"


async def _request(method: str, path: str, payload: dict | None = None, timeout: float = 5.0):
    conn = aiohttp.UnixConnector(path=str(_sock_path()))
    async with aiohttp.ClientSession(
        connector=conn, timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.request(method, _HUB_URL_BASE + path, json=payload) as r:
            r.raise_for_status()
            return await r.json()


def _get(path: str, timeout: float = 5.0):
    return asyncio.run(_request("GET", path, timeout=timeout))


def _post(path: str, payload: dict, timeout: float = 5.0):
    return asyncio.run(_request("POST", path, payload=payload, timeout=timeout))


def _hub_alive() -> bool:
    try:
        return _get("/api/health", timeout=0.5).get("service") == "project-notebook-hub"
    except Exception:
        return False


def _ensure_hub_running(timeout: float = 10.0):
    """Reuse a running hub (health probe over the socket); otherwise spawn one detached."""
    if _hub_alive():
        return
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    log = open(state_dir / "hub.log", "a")
    subprocess.Popen(
        [sys.executable, "-m", "project_notebook.hub"],
        stdout=log, stderr=log, start_new_session=True,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _hub_alive():
            return
        time.sleep(0.2)
    raise SystemExit(f"Hub did not become healthy within {timeout}s; see {state_dir / 'hub.log'}")


def cmd_hub(args):
    from . import hub
    hub.run()


def cmd_register(args):
    _ensure_hub_running()  # synchronous; must happen before entering an event loop
    name = args.name or Path.cwd().name
    path = str(Path.cwd())
    asyncio.run(_stream_session(name, path))


async def _stream_session(name: str, path: str):
    """Hold an SSE pipe to the hub: the project is registered while connected,
    and each artifact prints one stdout line (a Monitor event). Reconnects with
    backoff if the connection drops; runs until the process is killed."""
    url = f"{_HUB_URL_BASE}/api/session?project={quote(name)}&path={quote(path)}"
    while True:
        try:
            conn = aiohttp.UnixConnector(path=str(_sock_path()))
            async with aiohttp.ClientSession(connector=conn) as session:
                async with session.get(url) as resp:
                    print(f"Registered '{name}' — watching for artifacts", file=sys.stderr, flush=True)
                    async for raw in resp.content:
                        line = raw.decode(errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[len("data:"):].strip())
                        except json.JSONDecodeError:
                            continue
                        etype = event.get("type")
                        if etype == "artifact_received":
                            print(f"New artifact: {event.get('filename', '?')}  ({event.get('path', '')})", flush=True)
                        elif etype == "artifact_processed":
                            proc = event.get("processor", "?")
                            outs = event.get("outputs") or []
                            err = event.get("error")
                            name = event.get("filename", "?")
                            sidecar = event.get("sidecar_dir", "")
                            if outs:
                                print(f"Processed: {name} via {proc} -> {', '.join(outs)} (in {sidecar})", flush=True)
                            elif err:
                                print(f"Processed: {name} via {proc} skipped: {err}", flush=True)
        except (aiohttp.ClientError, OSError):
            pass  # connection dropped — reconnect with backoff
        await asyncio.sleep(2)


def cmd_status(args):
    if not _hub_alive():
        print("Hub is not running.")
        return
    projects = _get("/api/projects")["projects"]
    if not projects:
        print("Hub running. No active sessions.")
        return
    print("Hub running. Active sessions:")
    for p in projects:
        print(f"  {p['name']}  ({p['path']})  artifacts: {len(p['artifacts'])}")


def cmd_install_claude_code_skill(args):
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    dest = config_dir / "skills" / "notebook-register"
    dest.mkdir(parents=True, exist_ok=True)
    src = resources.files("project_notebook") / "skill"
    count = 0
    for item in src.iterdir():
        (dest / item.name).write_bytes(item.read_bytes())
        count += 1
    print(f"Installed {count} skill file(s) to {dest}")


def cmd_pair(args):
    from . import pairing
    _ensure_hub_running()
    resp = _post("/api/pair/new", {})
    if args.address:
        # Override: encode just the given host (keeping the hub's chosen port).
        u = urlparse(resp["lan_url"])
        netloc = f"{args.address}:{u.port}" if u.port else args.address
        urls = [urlunparse(u._replace(netloc=netloc))]
    else:
        urls = resp.get("lan_urls") or [resp["lan_url"]]
    # Encode every candidate so the phone can try each — repeated ?url= keys are
    # legal per RFC 3986 and parsed as a list by URLComponents on iOS.
    query = "&".join(f"url={quote(u, safe='')}" for u in urls) + f"&code={quote(resp['code'])}"
    deep_link = f"projectnotebook://pair?{query}"
    print(pairing.render_qr(deep_link))
    print("Hub address(es) encoded (phone will try each):")
    for u in urls:
        print(f"  {u}")
    print(f"Link: {deep_link}")
    print(f"Scan within {resp['ttl']}s.")


def cmd_devices(args):
    _ensure_hub_running()
    if args.revoke:
        resp = _post("/api/devices/revoke", {"device_id": args.revoke})
        print(f"Revoked '{resp['name']}' ({resp['device_id']})")
        return
    devs = _get("/api/devices")["devices"]
    if not devs:
        print("No paired devices.")
        return
    print("Paired devices:")
    for d in devs:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["paired_at"]))
        print(f"  {d['id']}  {d['name']}  (paired {when})")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="project-notebook", description="Project Notebook hub + CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("hub", help="Run the hub server (foreground)")
    p.set_defaults(func=cmd_hub)

    p = sub.add_parser("register", help="Open a session pipe: register this project and stream its artifacts (run via Monitor)")
    p.add_argument("name", nargs="?", help="Project name (default: current directory name)")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("status", help="Show the hub and active sessions")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("install-claude-code-skill", help="Install the Claude Code skill into ~/.claude/skills")
    p.set_defaults(func=cmd_install_claude_code_skill)

    p = sub.add_parser("pair", help="Pair a phone by printing a QR code to scan")
    p.add_argument("--address", metavar="HOST", help="Override the hub host in the QR (e.g. your Tailscale IP, when mDNS/LAN is blocked)")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("devices", help="List or revoke paired devices")
    p.add_argument("--revoke", metavar="ID", help="Revoke the device with this id")
    p.set_defaults(func=cmd_devices)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except aiohttp.ClientResponseError as e:
        raise SystemExit(f"Hub returned {e.status}: {e.message}")
    except aiohttp.ClientError as e:
        raise SystemExit(f"Could not reach hub over {_sock_path()}: {e}")
