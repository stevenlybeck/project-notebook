# Project Notebook — Dogfooding Sprint

Two weeks of real use to find friction before we build more features. The
product was built on a hypothesis (artifacts from the bench, captured
alongside session context, become useful later). This is where the
hypothesis meets the actual bench.

- **Start:** 2026-06-03
- **Mid-review:** 2026-06-10
- **End / triage:** 2026-06-17

## Goal

Surface what's actually broken vs. what feels fine, **before** committing
engineering time to follow-ups. The list under "In flight / next" in
PLAN.md is best-guess; real use turns it into a real priority list.

## Use it for what it was built for

The original motivating case is the breadboard / electronics work — that's
the highest-signal place to use it.

- **Open a session for whatever project you're actually working on**
  (`/notebook-register`) at the start of any bench session.
- **Use the share sheet at least once per session.** Photo of the bench,
  voice memo on a hypothesis, screenshot from the oscilloscope, whatever's
  natural. Forcing function so we see real volume rather than ceremonial
  shares.

## Deliberately exercise these once each over the two weeks

These are the corners we haven't stress-tested:

- [ ] Long video (>30 s) — exercises the full ffmpeg → audio → transcribe path
- [ ] Long voice memo (>1 min) — exercises long-form transcription
- [ ] Two registered sessions in parallel, share to each, confirm the right
  one receives
- [ ] Share while no session is open — what's the user experience? Does
  anything queue or get lost?
- [ ] Share over Tailscale (Wi-Fi off on the phone) — overlay-network path
- [ ] Mac reboot mid-flow — does the next share Just Work after, or do
  you have to do something?
- [ ] Share an unusual file type (PDF, plain text, anything weird)
- [ ] Skill-flow check: does Claude actually run the annotation, or do
  you have to nudge it?

## Capture friction as you go

Append entries to [DOGFOOD-LOG.md](DOGFOOD-LOG.md). Don't filter, don't
pre-categorize. The raw stream is the data. Examples of what's worth
writing down:

- "Took 8 seconds for the session to acknowledge — felt slow."
- "Whisper rendered 'I²C' as 'I square C'."
- "60s video timed out twice in a row on home Wi-Fi."
- "Annotation called the breadboard a 'circuit prototype' — generic; I
  wanted it to know we were on the level-shifter specifically."
- "Couldn't remember whether the hub was running."
- "Wanted to find every photo from 'pull-up resistor' work. Couldn't."

Anything you'd say out loud while using it. Time-of-day stamps are
useful; full sentences aren't.

## Review cadence

### 2026-06-10 — mid-sprint skim

Read DOGFOOD-LOG.md top to bottom. For each entry, tag it:

- **fix-now** — blocking real use
- **fix-soon** — annoying but workable
- **feature** — not a bug; it's the next thing to build
- **non-issue** — turned out to be fine on reflection

If there are any **fix-now** items, address them. Don't let them
contaminate week 2's signal.

### 2026-06-17 — end-of-sprint triage

Same pass over week 2 entries. Plus a 1-paragraph reflection at the
bottom of DOGFOOD-LOG.md: **"would I use this if it weren't mine?"**

- If **yes** and friction is concentrated in 2–3 specific places: those
  become the next sprint, in priority order.
- If **no**: figure out *why* before building more. The honest read
  matters more than shipping more code.

Move the verdict + the next-sprint list into PLAN.md's "In flight /
next" section.

## What we're explicitly NOT doing during dogfooding

- Building `setup`, search, web UI, more transcription tools, web work,
  or anything else from "Deferred". All of that waits for real-use
  signal.
- Recruiting more testers. Get our own data first; recruit when we have
  a clean story about what's working.
- Tweaking the landing page or README based on hypothetical concerns.
  Concrete-only.

If we *do* end up making a code change during dogfooding, it should be
to fix something that blocks the day's use — not because we thought of
something nice while looking at the code.
