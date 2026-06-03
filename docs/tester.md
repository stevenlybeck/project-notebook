# Trying out Project Notebook

A minimal walkthrough for testers. Two halves: setup on your Mac, setup on
your iPhone. Then a tiny "did it work?" check.

If anything's confusing, that's the bug — tell Steven what tripped you up.

## What you need

- A Mac (Apple Silicon strongly preferred — transcription is fastest there).
- An iPhone on the same Wi-Fi as the Mac (or both on Tailscale).
- [`uv`](https://docs.astral.sh/uv/) installed. If you don't have it:
  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- A Claude Code session you're already using. Project Notebook plugs into
  it; it doesn't replace it.

## 1. Install on your Mac

```sh
uv tool install project-notebook
project-notebook install-claude-code-skill
project-notebook check
```

`check` will tell you which features are on and how to turn on the rest.
On a typical Apple Silicon Mac you'll want both of these for the full
experience:

```sh
brew install ffmpeg          # video metadata + preview frames + audio extraction
uv tool install mlx-whisper  # on-device audio transcription
```

Re-run `project-notebook check` until you see everything ✓.

## 2. Install on your iPhone

The iOS app ships through private TestFlight while we're in alpha.

1. Install **TestFlight** from the App Store if you don't already have it.
2. Steven will send you a TestFlight invite link. Tap it, accept, install
   **Project Notebook**.
3. Open the app once. iOS will ask permission to talk to devices on your
   local network — say yes. (Without it, the share extension can't reach
   the hub.)

## 3. Pair the phone with the Mac

On your Mac:

```sh
project-notebook pair
```

A QR code prints in the terminal. In the Project Notebook iOS app, tap
**Pair Hub** (or whatever the button is called) and point the camera at
the QR. You should see the app confirm it's paired.

Pairing is once-per-device. You don't need to do this again on the same
phone.

## 4. Open a Claude Code session

In a Claude Code session at the project you want to capture artifacts for,
run the skill:

```
/notebook-register
```

You should see something like `Registered '<project>' — watching for
artifacts`. Leave that session open. The pipe is live as long as the
session is.

## 5. Share something from your phone

Open any app on your phone — Photos, Camera, Notes, Voice Memos, anything
with a share button.

- Hit the **Share** button.
- Pick **Project Notebook** from the share sheet (may be under "More…" the
  first time).
- Pick the project you registered in step 4.
- Send it.

Within a few seconds, your Claude Code session should print one or more
lines starting with `New artifact:` and `Processed:` — and Claude will
read what arrived without you asking.

## What to try / what to report

Things worth testing:

- **Various media types** — photo, video, voice memo, screenshot, a
  random file (PDF, text). Anything weird? Tell Steven.
- **Big files** — try a longer video (>30 s). Did transcription finish
  in a reasonable time? Did the session reflect it?
- **Multiple projects** — register two sessions in different projects;
  make sure shares go to the one you picked, not the other.
- **The annotation step** — after a video or voice memo arrives, does
  Claude write a useful note tying it to what you were chatting about?

Things worth reporting:

- Anything that **failed silently** (you shared something, nothing
  happened in the session).
- Anything that took **way longer than felt right**.
- Anything **confusing** in this doc. If you needed Steven on Zoom to
  get past a step, that step's broken.

## Where things live, when you need to poke

- Hub logs: `~/.project-notebook/hub.log`
- Hub state (paired devices, port): `~/.project-notebook/`
- Artifacts you've received: `~/.project-notebook/artifacts/<project>/`

Useful commands:

```sh
project-notebook status     # what's the hub doing right now
project-notebook devices    # what phones are paired
project-notebook stop       # gracefully stop the hub
project-notebook restart    # stop + start
```

The hub runs in the background automatically — you usually don't need to
think about it. `stop` and `restart` are there for when you do.

## If you get stuck

Send Steven:
1. What you were trying to do.
2. The output of `project-notebook check`.
3. The last ~20 lines of `~/.project-notebook/hub.log`.
4. (If iOS was involved) anything the app showed you.

That's almost always enough to triangulate.
