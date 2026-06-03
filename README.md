# Project Notebook

> Like AirDrop, but it lands in your Claude Code session.

A local bridge from your phone's share sheet into the Claude Code session
you're already in. Photos, voice memos, videos, screenshots — whatever just
happened off-screen, brought back in. The session writes down what you were
thinking when each artifact arrived, attached to the file. A month later,
the photo still means something.

**Landing page (with diagrams and the story):**
<https://stevenlybeck.com/project-notebook/>

## What it does

- **Phone → Mac → session.** An iOS Share Extension uploads to a small
  hub running on your Mac, which notifies your active Claude Code
  session over a live pipe.
- **Per-project library, automatic.** Each artifact lands in
  `~/.project-notebook/artifacts/<project>/`, sidecared with extracted
  metadata, audio, a preview frame, and a transcript.
- **Session context becomes annotations.** Claude reads each artifact
  as it arrives and writes a note back capturing what was happening
  when you shared it.

## Install

```sh
uv tool install project-notebook
project-notebook install-claude-code-skill
project-notebook check    # see which features are on; install hints for the rest
```

Project Notebook itself has no optional features — the core hub, CLI,
skill, and pairing are always available. Audio transcription and
video-metadata extraction are backed by external tools you install
separately. `check` tells you what's on and how to turn on the rest.

On Apple Silicon for transcription:

```sh
uv tool install mlx-whisper
```

For video metadata and preview frames:

```sh
brew install ffmpeg
```

## Pair your phone

```sh
project-notebook pair    # prints a QR; scan it with the Project Notebook iOS app
```

The iOS app currently ships through private TestFlight. See
[docs/ios.md](docs/ios.md) for the build/distribution state.

## Open a session

In any Claude Code session:

```
/notebook-register
```

The skill holds a live pipe to the hub for the lifetime of the session —
no TTLs, no staleness. Anything you share from your phone shows up as
a notification in the conversation within seconds.

## For alpha testers

If Steven sent you here to test the thing — the Mac setup is above
(Install → Pair → Open a session). What's specific to you:

**iPhone setup.** The iOS app ships through private TestFlight while
we're in alpha.

1. Install **TestFlight** from the App Store if you don't already
   have it.
2. Steven will send you a TestFlight invite link. Tap it, accept,
   install **Project Notebook**.
3. Open the app once and grant **local-network** permission when iOS
   asks — without it, the share extension can't reach the hub.
4. Tap **Pair Hub** and scan the QR code from `project-notebook pair`
   on the Mac. Once per phone.

**Worth trying.** Share a few different things from your phone —
photo, video, voice memo, screenshot, generic file — and watch what
your Claude Code session does with each. Try a longer video (>30s)
to exercise the transcription path. Try registering two sessions in
two different projects and make sure shares land in the one you pick.

**Worth reporting back to Steven.**

- Anything that failed silently — you shared something and nothing
  showed up in the session.
- Anything that took noticeably longer than felt right.
- Anything in this README that was confusing or needed Zoom to get
  past. If you got stuck, that step's broken.

**Where things live when you need to poke.**

- Hub log: `~/.project-notebook/hub.log`
- Hub state (paired devices, port): `~/.project-notebook/`
- Artifacts: `~/.project-notebook/artifacts/<project>/`

```sh
project-notebook status     # what's the hub doing
project-notebook devices    # paired phones
project-notebook stop       # graceful stop
project-notebook restart    # stop + start
```

**If you get stuck, send Steven:**

1. What you were trying to do.
2. The output of `project-notebook check`.
3. The last ~20 lines of `~/.project-notebook/hub.log`.
4. Anything the iOS app showed (screenshot is fine).

That's almost always enough to triangulate.

## Architecture

- [Landing page](https://stevenlybeck.com/project-notebook/) —
  diagrams and the why
- [docs/architecture.md](docs/architecture.md) — the artifact pipeline,
  plane by plane
- [docs/security.md](docs/security.md) — three-plane access model (Unix
  socket, LAN, loopback)
- [docs/ios.md](docs/ios.md) — iOS app + share extension
- [docs/development.md](docs/development.md) — running from source

## Status

Personal tool, alpha. The end-to-end loop works on Apple Silicon Macs
with an iOS phone on the same LAN (or Tailscale). Cross-platform
support and additional transcription backends are
[planned](PLAN.md) but not yet wired up.

## License

[MIT](LICENSE) © Steven Lybeck
