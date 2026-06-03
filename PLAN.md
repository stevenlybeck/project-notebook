# Project Notebook — Plan

The roadmap and decision log. README is the install/use front door; this is
"what we're working on and why."

**Current release:** [v0.1.1](https://github.com/stevenlybeck/project-notebook/releases)
on PyPI. End-to-end loop is alive: phone → hub → session → annotated
per-project library. Status: personal-tool alpha; iOS app in private
TestFlight; dogfooding now (see [DOGFOOD.md](DOGFOOD.md)).

## Done

### Core delivery
- **Package + CLI** as a uv-installable tool. `uv tool install project-notebook`.
- **Three-plane hub** — Unix socket for local commands, TCP for the phone API,
  TCP loopback for the web UI. Bearer-token middleware on the phone plane;
  host-header guard on the web plane. See [docs/security.md](docs/security.md).
- **iOS app + Share Extension** with QR pairing, Keychain-stored device token,
  Bonjour discovery, multi-URL pairing for overlay networks (Tailscale).
- **SSE session pipe** — `register` holds an open pipe; the project is
  registered exactly as long as the session is. Notifications flow live
  into the Claude Code session via the bundled skill.
- **Per-project artifact library** at `~/.project-notebook/artifacts/<project>/<file>.d/`,
  each artifact in its own subdir with sidecars.

### Processing
- **`extract` processor** (ffmpeg/ffprobe) — `meta.yaml`, `audio.wav`, `poster.jpg`.
- **`transcribe` processor** — subprocess to whichever transcription tool the
  registry resolves to (currently mlx-whisper). `transcript.md` + `transcript.json`.
- **Annotation pass** — `project-notebook annotate` lets the live session
  write structured session-context annotations into `meta.yaml`.

### Install & Setup
- **`check`** — passive feature reporter. Reads the tool registry, prints
  what's on, what's off, and the install hint for what's missing. Exits
  non-zero when anything's off; supports `--json`.
- **Tool / Feature registry** — clean separation: processor is the *job*
  (extract, transcribe); tool is the *external executable* (ffmpeg,
  mlx-whisper). Adding a tool is a registry entry + a small runner.
- **`stop` / `restart`** — graceful shutdown via the local-plane
  `/api/shutdown` endpoint; clean socket cleanup.
- **Port auto-pick + persistence** — no more port collisions; iOS's stored
  hubURL stays valid across hub restarts.
- **`[whisper]` extra dropped** — transcription is an external tool, not
  a Python extra. `pyproject.toml` ships with no optional dependencies.

### Distribution
- **MIT licensed**, **PyPI v0.1.1**, **GitHub Releases** tagged.
- **Landing page** at <https://stevenlybeck.com/project-notebook/>.
- **README** with install + use + "For alpha testers" walkthrough.

## In flight / next

Priorities will get reshuffled by what dogfooding surfaces.

- **Dogfood for 1–2 weeks** — see [DOGFOOD.md](DOGFOOD.md). Real use sets
  the next priorities; without it, the work below is best-guess.
- **`setup` command** — interactive companion to `check`. Same registry;
  walks missing tools and runs the recommended install hints. Natural
  completion of the install-and-setup work.
- **Config persistence** at `~/.project-notebook/config.toml` — user's
  chosen transcription tool preference vs. live auto-resolution.
- **Recruit a tester or two** — once the friction log is clean enough that
  we're not asking them to live with known annoyances.

## Deferred (post-v1)

- **`setup` for cross-platform tooling** — `brew` on macOS when present;
  `apt`/`dnf`/`pacman` snippets printed (not invoked) on Linux. No
  `sudo` on the user's behalf.
- **More transcription tools** — `whisper.cpp` (cross-platform binary),
  `openai-whisper` (slow but anywhere). Same model as ffmpeg — declare in
  registry, add a runner, done. We deliberately shipped mlx-whisper only
  for v0.1; broaden when there's user demand.
- **Search across artifacts** — SQLite FTS5 over transcripts + annotations.
  The thing that makes the annotation work *pay off*. Skills like
  `/search [query]` build on this. Probably the highest-leverage feature
  after dogfooding shapes priorities.
- **Web UI** — three routes wired, mostly empty. Decide whether v1 needs
  a real UI or "good enough for now" wins. Defer until use shows what's
  missing.
- **Menu-bar app** — separate `project-notebook-menubar` package, or a
  native `.app`. Decide once the pain of "is the hub running?" becomes
  concrete.
- **HTTPS on LAN** — current trust model is bearer device token + trusted
  network (LAN or paired-end overlay like Tailscale). Two pressures could
  change this:
  - **Plaintext on an untrusted network without an overlay** — bearer
    tokens leak. Workaround today: use Tailscale. Pairing encodes every
    reachable address and the phone tries each.
  - **App Store review pushes back on `NSAllowsArbitraryLoads`** — the
    current ATS exception is required because Tailscale's CGNAT isn't in
    iOS's `NSAllowsLocalNetworking` allowlist, and the two keys are
    mutually exclusive on iOS 10+ (see the note in
    `ios/ProjectNotebook/ProjectNotebook/Info.plist`). The "companion app
    to a user-controlled local server" justification usually clears
    review; HTTPS + cert pinning is the fallback.
  - **Shape of the work:** hub mints a self-signed cert on first run;
    iOS pins the fingerprint via `URLSessionDelegate`; pairing carries the
    fingerprint in the QR alongside the URLs; mDNS TXT can also publish it.
- **QuickShare ingestion** — Google's cross-platform Nearby Share as an
  alternate transport. Would extend reach to Android/ChromeOS and avoid
  the LAN-discovery/pairing plumbing entirely. Open: does the macOS
  QuickShare client expose a programmable hook, or do we watch a drop
  folder?
- **iOS auto-bump build number** — set `VERSIONING_SYSTEM = "apple-generic"`
  in pbxproj and add a pre-archive script that derives `CURRENT_PROJECT_VERSION`
  from a Unix timestamp or `git rev-list --count HEAD`. Defer until manual
  bumping in Xcode becomes annoying.
- **Notify on upload *start*, not completion** — the PUT handler already
  populates `active_uploads` when the upload *begins*; emitting the
  session-pipe event then would hide transfer latency. (The push pipe
  itself is now implemented; see `docs/architecture.md` §4.)
- **Accurate Swift LSP diagnostics** — set up
  [`xcode-build-server`](https://github.com/SolaWing/xcode-build-server)
  so sourcekit-lsp sees Xcode's real compile flags. Local dev-experience
  improvement; no effect on the Xcode build.
- **Holistic architecture review** — once dogfooding ends and we know
  what's solid and what isn't, do a pass over hub/agent split, the three
  security planes, storage layout, CLI ergonomics. Done with working code,
  not up front.

## Resolved decisions

- **Package name**: `project-notebook` (with `notebook` as a CLI alias).
- **Hub persistence**: detached background process; no PID file (health
  check via socket). LaunchAgent deferred.
- **Skill distribution**: bundled in the package; `install-claude-code-skill`
  copies it to `~/.claude/skills/`. Upgrading the package upgrades the skill.
- **Tool installation model**: external system tools (`brew install`,
  `uv tool install <sibling>`) rather than Python extras of this package.
  Side-steps the `uv tool install --reinstall --with` lifecycle question
  entirely. Clean separation between us and the tools we shell out to.
- **Port handling**: ephemeral auto-pick on first run, persisted to
  `~/.project-notebook/port`, reused on every restart. `PROJECT_NOTEBOOK_PORT`
  overrides verbatim.
- **Session lifetime**: connection-bound (SSE pipe). No TTLs, no staleness.
- **Annotation authorship**: the live Claude Code session itself, via
  `project-notebook annotate`. Not a server-side processor that imports
  the Claude API.

## Documentation
- **README.md** — install, use, alpha-tester walkthrough
- **docs/architecture.md** — hub ↔ agent pipeline
- **docs/security.md** — three-plane access model
- **docs/ios.md** — iOS app + share extension
- **docs/development.md** — running from source
- **docs/index.html** — landing page with diagrams
- **DOGFOOD.md** — the current dogfooding sprint
