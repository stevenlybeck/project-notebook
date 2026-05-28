"""
Project Notebook Hub

Accepts artifact uploads from the iOS Share Extension and delivers them
to registered projects.

API:
  POST /api/register    → Register a project {"project": "name", "path": "/abs/path", "ttl": 3600}
  POST /api/unregister  → Unregister a project {"project": "name"}
  GET  /api/projects    → List registered projects
  POST /api/ingest      → Upload a file (multipart: project, file)
  GET  /                → Web UI
"""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

from aiohttp import web

from . import pairing

# Persistent state directory (override with PROJECT_NOTEBOOK_HOME).
STATE_DIR = Path(os.environ.get("PROJECT_NOTEBOOK_HOME", Path.home() / ".project-notebook"))
STATE_FILE = STATE_DIR / "state.json"
PORT = int(os.environ.get("PROJECT_NOTEBOOK_PORT", "9999"))          # phone API (LAN)
WEB_PORT = int(os.environ.get("PROJECT_NOTEBOOK_WEB_PORT", "9877"))  # web UI (loopback)

# State
projects: dict = {}  # project_name -> {"path": str, "expires": float}
devices: dict = {}    # device_id -> {"token": str, "name": str, "paired_at": float}
# In-memory only (lost on restart, which is fine):
active_uploads: dict = {}    # upload_id -> {"filename": str, "project": str, "received": int, "total": int or None, "status": str}
pending_pairings: dict = {}  # code -> {"token": str, "device_id": str, "expires": float}


def load_state():
    """Load persisted registrations and devices; drop already-expired registrations."""
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[hub] Could not read {STATE_FILE} ({e}); starting empty")
        return
    now = time.time()
    for name, info in data.get("projects", {}).items():
        if info.get("expires", 0) > now:
            projects[name] = info
    devices.update(data.get("devices", {}))
    print(f"[hub] Loaded {len(projects)} project(s), {len(devices)} device(s) from {STATE_FILE}")


def save_state():
    """Persist registrations and devices atomically (temp file + rename)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    tmp.write_text(json.dumps({"projects": projects, "devices": devices}, indent=2))
    tmp.replace(STATE_FILE)


def get_artifacts(project_path: str) -> list:
    """List artifacts in a project's artifacts directory."""
    artifacts_dir = Path(project_path) / "artifacts"
    if not artifacts_dir.exists():
        return []
    files = []
    for f in sorted(artifacts_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.name.startswith("."):
            continue
        stat = f.stat()
        files.append({
            "name": f.name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
    return files


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def prune_expired():
    now = time.time()
    expired = [name for name, info in projects.items() if info["expires"] < now]
    for name in expired:
        del projects[name]
    if expired:
        save_state()


# --- HTTP handlers ---

async def handle_index(request):
    prune_expired()
    return web.Response(text=HTML, content_type="text/html")


async def handle_projects(request):
    prune_expired()
    project_list = [
        {"name": name, "path": info["path"],
         "ttl_remaining": max(0, int(info["expires"] - time.time())),
         "artifacts": get_artifacts(info["path"])}
        for name, info in projects.items()
    ]
    return web.json_response({"projects": project_list})


async def handle_register(request):
    body = await request.json()
    name = body.get("project", "")
    path = body.get("path", "")
    ttl = body.get("ttl", 3600)  # default 1 hour
    if not name or not path:
        return web.Response(status=400, text="Missing project or path")
    projects[name] = {"path": path, "expires": time.time() + ttl}
    save_state()
    print(f"[hub] Registered project: {name} (path={path}, ttl={ttl}s)")
    return web.json_response({"status": "registered", "project": name})


async def handle_unregister(request):
    body = await request.json()
    name = body.get("project", "")
    if name in projects:
        del projects[name]
        save_state()
    return web.json_response({"status": "unregistered", "project": name})


def safe_filename(name: str) -> str:
    """Strip directory components so an upload can't escape the artifacts dir."""
    return Path(name or "").name or "unnamed"


async def handle_ingest(request):
    """Accept a file upload and deliver to the specified project.

    Supports two modes:
    - PUT with query params ?project=X&filename=Y and raw body (from iOS background upload)
    - POST with multipart form data (from curl/testing)
    """
    if request.method == "PUT":
        project_name = request.query.get("project", "")
        filename = safe_filename(request.query.get("filename", "unnamed"))
        upload_id = request.query.get("upload_id", filename)
        content_length = request.content_length

        if not project_name:
            return web.Response(status=400, text="Missing 'project' query param")

        prune_expired()
        if project_name not in projects:
            return web.Response(status=404, text=f"Project '{project_name}' not registered")

        project_path = Path(projects[project_name]["path"])
        artifacts_dir = project_path / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        dest = artifacts_dir / filename
        counter = 1
        while dest.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            dest = artifacts_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        active_uploads[upload_id] = {
            "filename": filename,
            "project": project_name,
            "received": 0,
            "total": content_length,
            "status": "uploading",
        }

        size = 0
        with open(dest, "wb") as f:
            while True:
                chunk = await request.content.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
                active_uploads[upload_id]["received"] = size

        active_uploads[upload_id]["status"] = "completed"
        print(f"[hub] Ingested {filename} ({size} bytes) → {project_name} ({dest})")

    else:
        # Multipart POST (for curl/testing)
        reader = await request.multipart()
        project_name = None
        filename = None
        dest = None

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "project":
                project_name = (await part.text()).strip()
            elif part.name == "file":
                filename = safe_filename(part.filename)

                if not project_name:
                    return web.Response(status=400, text="Missing 'project' field")

                prune_expired()
                if project_name not in projects:
                    return web.Response(status=404, text=f"Project '{project_name}' not registered")

                project_path = Path(projects[project_name]["path"])
                artifacts_dir = project_path / "artifacts"
                artifacts_dir.mkdir(parents=True, exist_ok=True)

                dest = artifacts_dir / filename
                counter = 1
                while dest.exists():
                    stem = Path(filename).stem
                    suffix = Path(filename).suffix
                    dest = artifacts_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                with open(dest, "wb") as f:
                    while True:
                        chunk = await part.read_chunk(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        size += len(chunk)

                print(f"[hub] Ingested {filename} ({size} bytes) → {project_name} ({dest})")

        if not project_name:
            return web.Response(status=400, text="Missing 'project' field")
        if not dest:
            return web.Response(status=400, text="Missing 'file' field")

    subprocess.run([
        "osascript", "-e",
        f'display notification "{filename} ingested to {project_name}" '
        f'with title "Project Notebook"'
    ], capture_output=True)

    return web.json_response({
        "status": "ingested",
        "project": project_name,
        "filename": dest.name,
        "path": str(dest),
    })


HTML = """<!DOCTYPE html>
<html>
<head>
<title>Project Notebook Hub</title>
<style>
  body { font-family: system-ui; max-width: 700px; margin: 40px auto; padding: 0 20px; background: #1a1a1a; color: #e0e0e0; }
  h1 { font-size: 1.4em; }
  .project { background: #2a2a2a; border: 1px solid #444; border-radius: 8px; padding: 16px; margin: 12px 0; }
  .project h2 { margin: 0 0 4px 0; font-size: 1.1em; color: #88ccff; }
  .project .meta { color: #888; font-size: 0.85em; }
  .no-projects { color: #666; font-style: italic; }
  .status { margin-top: 20px; padding: 12px; background: #2a2a2a; border-radius: 8px; border: 1px solid #444; }
  .status h3 { margin: 0 0 8px 0; font-size: 1em; color: #88cc88; }
  .artifacts { margin-top: 10px; }
  .artifacts h3 { font-size: 0.85em; color: #aaa; margin: 8px 0 4px 0; }
  .artifact { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; border-radius: 4px; font-size: 0.85em; }
  .artifact:nth-child(even) { background: #333; }
  .artifact .name { color: #ccc; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .artifact .size { color: #888; margin-left: 12px; white-space: nowrap; }
  .artifact .time { color: #666; margin-left: 12px; white-space: nowrap; }
  .no-artifacts { color: #555; font-size: 0.85em; font-style: italic; padding: 4px 8px; }
</style>
</head>
<body>
<h1>Project Notebook Hub</h1>

<div class="status">
  <h3>Accepting artifacts from iOS Share Extension</h3>
</div>

<div id="projects"></div>

<script>
function formatTime(seconds) {
  if (seconds > 3600) return Math.round(seconds / 3600) + 'h';
  if (seconds > 60) return Math.round(seconds / 60) + 'm';
  return seconds + 's';
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
}

function formatDate(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const diffMs = now - d;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return diffMins + 'm ago';
  if (diffMins < 1440) return Math.floor(diffMins / 60) + 'h ago';
  return d.toLocaleDateString();
}

async function refresh() {
  const res = await fetch('/api/projects');
  const data = await res.json();
  const el = document.getElementById('projects');
  if (data.projects.length === 0) {
    el.innerHTML = '<p class="no-projects">No projects registered.</p>';
    return;
  }
  el.innerHTML = data.projects.map(p => {
    const artifactList = p.artifacts.length === 0
      ? '<div class="no-artifacts">No artifacts yet</div>'
      : p.artifacts.map(a => `
          <div class="artifact">
            <span class="name">${a.name}</span>
            <span class="size">${formatSize(a.size)}</span>
            <span class="time">${formatDate(a.modified)}</span>
          </div>
        `).join('');

    return `
    <div class="project">
      <h2>${p.name}</h2>
      <div class="meta">${p.path} · expires in ${formatTime(p.ttl_remaining)}</div>
      <div class="artifacts">
        <h3>Artifacts (${p.artifacts.length})</h3>
        ${artifactList}
      </div>
    </div>`;
  }).join('');
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


async def handle_uploads(request):
    """Return the status of all active and recently completed uploads."""
    return web.json_response({"uploads": active_uploads})


async def handle_health(request):
    """Liveness probe with a recognizable signature for the CLI."""
    return web.json_response({"service": "project-notebook-hub", "status": "ok"})


async def handle_pair_new(request):
    """Local plane: mint a single-use pairing code + a pending device token."""
    code = pairing.new_code()
    pending_pairings[code] = {
        "token": pairing.new_token(),
        "device_id": pairing.new_device_id(),
        "expires": time.time() + pairing.PAIRING_TTL,
    }
    lan_url = f"http://{pairing.lan_ip()}:{PORT}"
    return web.json_response({"code": code, "lan_url": lan_url, "ttl": pairing.PAIRING_TTL})


async def handle_pair(request):
    """Phone plane: redeem a pairing code for a long-lived device token."""
    body = await request.json()
    code = body.get("code", "")
    name = body.get("device_name") or "device"
    info = pending_pairings.pop(code, None)  # single-use
    if not info or info["expires"] < time.time():
        return web.Response(status=403, text="Invalid or expired pairing code")
    devices[info["device_id"]] = {"token": info["token"], "name": name, "paired_at": time.time()}
    save_state()
    print(f"[hub] Paired device '{name}' ({info['device_id']})")
    return web.json_response({"token": info["token"], "device_id": info["device_id"]})


async def handle_devices(request):
    """Local plane: list paired devices (tokens are never exposed)."""
    return web.json_response({"devices": [
        {"id": did, "name": d["name"], "paired_at": d["paired_at"]}
        for did, d in devices.items()
    ]})


async def handle_devices_revoke(request):
    """Local plane: revoke a device by id."""
    body = await request.json()
    device_id = body.get("device_id", "")
    d = devices.pop(device_id, None)
    if d is None:
        return web.Response(status=404, text=f"No device '{device_id}'")
    save_state()
    return web.json_response({"status": "revoked", "device_id": device_id, "name": d["name"]})


def make_apps():
    """Build the three plane apps. State is shared via module globals.

    - local: Unix-socket plane for CLI commands (register/status/...).
    - phone: LAN plane for device ingest (auth added separately).
    - web:   loopback plane for the read-only web UI.
    """
    local = web.Application()
    local.router.add_get("/api/health", handle_health)
    local.router.add_get("/api/projects", handle_projects)
    local.router.add_get("/api/uploads", handle_uploads)
    local.router.add_post("/api/register", handle_register)
    local.router.add_post("/api/unregister", handle_unregister)
    local.router.add_post("/api/pair/new", handle_pair_new)
    local.router.add_get("/api/devices", handle_devices)
    local.router.add_post("/api/devices/revoke", handle_devices_revoke)

    phone = web.Application(client_max_size=1024 * 1024 * 1024)  # 1GB max upload
    phone.router.add_post("/api/ingest", handle_ingest)
    phone.router.add_put("/api/ingest", handle_ingest)
    phone.router.add_post("/api/pair", handle_pair)

    web_ui = web.Application()
    web_ui.router.add_get("/", handle_index)
    web_ui.router.add_get("/api/projects", handle_projects)
    web_ui.router.add_get("/api/uploads", handle_uploads)

    return local, phone, web_ui


async def _serve():
    load_state()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    local, phone, web_ui = make_apps()

    # Local commands: Unix domain socket, owner-only.
    local_runner = web.AppRunner(local)
    await local_runner.setup()
    sock_path = STATE_DIR / "hub.sock"
    if sock_path.exists():
        sock_path.unlink()
    await web.UnixSite(local_runner, str(sock_path)).start()
    os.chmod(sock_path, 0o600)

    # Phone API: reachable on the LAN.
    phone_runner = web.AppRunner(phone)
    await phone_runner.setup()
    await web.TCPSite(phone_runner, "0.0.0.0", PORT).start()

    # Web UI: loopback only.
    web_runner = web.AppRunner(web_ui)
    await web_runner.setup()
    await web.TCPSite(web_runner, "127.0.0.1", WEB_PORT).start()

    print(f"[hub] local socket: {sock_path}")
    print(f"[hub] phone API:    http://0.0.0.0:{PORT}")
    print(f"[hub] web UI:       http://127.0.0.1:{WEB_PORT}")
    await asyncio.Event().wait()


def run():
    """Start the hub on all three listeners (blocking)."""
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
