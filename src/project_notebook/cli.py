"""Project Notebook CLI.

Local interaction with the hub goes through these subcommands; the
subcommands that touch hub state are thin clients that call the hub's
HTTP API over loopback, so the hub remains the single source of truth.
"""

import argparse
import importlib.resources as resources
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _port() -> int:
    return int(os.environ.get("PROJECT_NOTEBOOK_PORT", "9999"))


def _base() -> str:
    return f"http://127.0.0.1:{_port()}"


def _get(path: str, timeout: float = 5.0):
    with urllib.request.urlopen(_base() + path, timeout=timeout) as r:
        return json.loads(r.read())


def _post(path: str, payload: dict, timeout: float = 5.0):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        _base() + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _hub_alive() -> bool:
    try:
        return _get("/api/health", timeout=0.5).get("service") == "project-notebook-hub"
    except Exception:
        return False


def _ensure_hub_running(timeout: float = 10.0):
    """Reuse a running hub (health probe); otherwise spawn one detached."""
    if _hub_alive():
        return
    state_dir = Path(os.environ.get("PROJECT_NOTEBOOK_HOME", Path.home() / ".project-notebook"))
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

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Hub returned {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach hub at {_base()}: {e.reason}")
