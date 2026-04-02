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

import os
import subprocess
import time
from pathlib import Path

from aiohttp import web

# State
projects: dict = {}  # project_name -> {"path": str, "expires": float}
active_uploads: dict = {}  # upload_id -> {"filename": str, "project": str, "received": int, "total": int or None, "status": str}


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
    print(f"[hub] Registered project: {name} (path={path}, ttl={ttl}s)")
    return web.json_response({"status": "registered", "project": name})


async def handle_unregister(request):
    body = await request.json()
    name = body.get("project", "")
    if name in projects:
        del projects[name]
    return web.json_response({"status": "unregistered", "project": name})


async def handle_ingest(request):
    """Accept a file upload and deliver to the specified project.

    Supports two modes:
    - PUT with query params ?project=X&filename=Y and raw body (from iOS background upload)
    - POST with multipart form data (from curl/testing)
    """
    if request.method == "PUT":
        project_name = request.query.get("project", "")
        filename = request.query.get("filename", "unnamed")
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
                filename = part.filename or "unnamed"

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


app = web.Application(client_max_size=1024 * 1024 * 1024)  # 1GB max upload
app.router.add_get("/", handle_index)
app.router.add_get("/api/projects", handle_projects)
app.router.add_get("/api/uploads", handle_uploads)
app.router.add_post("/api/register", handle_register)
app.router.add_post("/api/unregister", handle_unregister)
app.router.add_post("/api/ingest", handle_ingest)
app.router.add_put("/api/ingest", handle_ingest)

if __name__ == "__main__":
    web.run_app(app, port=9999)
