"""Project Notebook CLI.

Local interaction with the hub goes through these subcommands; the
subcommands that touch hub state are thin clients that call the hub's
HTTP API over loopback, so the hub remains the single source of truth.
"""

import argparse
import asyncio
import importlib.resources as resources
import os
import subprocess
import sys
import time
from pathlib import Path

import aiohttp


def _state_dir() -> Path:
    return Path(os.environ.get("PROJECT_NOTEBOOK_HOME", Path.home() / ".project-notebook"))


def _sock_path() -> Path:
    return _state_dir() / "hub.sock"


async def _request(method: str, path: str, payload: dict | None = None, timeout: float = 5.0):
    conn = aiohttp.UnixConnector(path=str(_sock_path()))
    async with aiohttp.ClientSession(
        connector=conn, timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.request(method, "http://localhost" + path, json=payload) as r:
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
    _ensure_hub_running()
    name = args.name or Path.cwd().name
    path = str(Path.cwd())
    resp = _post("/api/register", {"project": name, "path": path, "ttl": args.ttl})
    print(f"Registered '{resp['project']}' (path={path}, ttl={args.ttl}s)")


def cmd_unregister(args):
    _ensure_hub_running()
    name = args.name or Path.cwd().name
    _post("/api/unregister", {"project": name})
    print(f"Unregistered '{name}'")


def cmd_status(args):
    if not _hub_alive():
        print("Hub is not running.")
        return
    projects = _get("/api/projects")["projects"]
    if not projects:
        print("Hub running. No projects registered.")
        return
    print("Hub running. Registered projects:")
    for p in projects:
        print(f"  {p['name']}  ({p['path']})  expires in {p['ttl_remaining']}s  artifacts: {len(p['artifacts'])}")


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
    deep_link = f"projectnotebook://pair?url={resp['lan_url']}&code={resp['code']}"
    print(pairing.render_qr(deep_link))
    print(f"Scan within {resp['ttl']}s to pair. Hub: {resp['lan_url']}")


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

    p = sub.add_parser("register", help="Register the current project with the hub")
    p.add_argument("name", nargs="?", help="Project name (default: current directory name)")
    p.add_argument("--ttl", type=int, default=7200, help="Registration TTL in seconds (default 7200)")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("unregister", help="Unregister a project")
    p.add_argument("name", nargs="?", help="Project name (default: current directory name)")
    p.set_defaults(func=cmd_unregister)

    p = sub.add_parser("status", help="Show hub status and registered projects")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("install-claude-code-skill", help="Install the Claude Code skill into ~/.claude/skills")
    p.set_defaults(func=cmd_install_claude_code_skill)

    p = sub.add_parser("pair", help="Pair a phone by printing a QR code to scan")
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
