# Dogfood Log

Raw stream-of-friction notes from the 2026-06-03 → 2026-06-17 dogfooding
sprint. See [DOGFOOD.md](DOGFOOD.md) for the plan.

Append entries below as you notice things. One line is fine; a paragraph
is fine. Don't filter, don't pre-categorize. Time-of-day stamps help when
you come back to triage.

Format suggestion (not enforced):

```
### 2026-06-04 09:12 — photo of breadboard
Session took ~6 s to acknowledge. Annotation was decent but called the
chip a "DIP-8 IC" instead of the SX1276 we were actually wiring. Maybe
the conversation context wasn't loud enough about which chip we were
on.
```

---

<!-- Entries below -->

### 2026-06-03 16:06 — `project-notebook pair` failed: hub wouldn't start
First try at dogfooding. Got:

```
% project-notebook pair
Hub did not become healthy within 10.0s; see /Users/stevenlybeck/.project-notebook/hub.log
```

Hub log showed `OSError: [Errno 48] error while attempting to bind on
address ('127.0.0.1', 9877): address already in use`. The web-UI port
9877 is hardcoded — no auto-pick, no persistence. An old hub process
from earlier smoke testing was still running and holding the port, so
every new hub crashed at startup.

**Triage:** **fix-now** (blocks pairing → blocks all dogfooding).
Apply the same auto-pick + persist treatment we did for the phone port
to the web-UI port. Target: 0.1.2.

**Resolved:** v0.1.2 ([125524d](../../commit/125524d),
[release](https://github.com/stevenlybeck/project-notebook/releases/tag/v0.1.2)).
Web port now follows the same env-override → persisted → auto-pick
precedence as the phone port. Two hubs in parallel can coexist;
restarts reuse the persisted port.

### 2026-06-03 ~17:00 — Bundled skill is too eager to act on artifacts

Self-surfaced by the very first real artifact through the live pipe
(the "Mokelumne Ave" voice memo on a walk):

> the skill is creatively interpreted by the particular project that
> is using this … they get really too creative basically. They're
> like, "oh let me dig in and really solve the problems here or solve
> the problem that's not even a problem and get deep into the weeds
> of things."

**Risk surface:** a non-developer end user (Steven's brother is the
named first external tester) shares a photo and watches the registered
session decide *now* is a great moment to debug the hub itself —
writing code, running tests, editing files in a project repo they
don't recognize. Credibility-burner; the share is supposed to feel
like AirDrop, not like surrendering control of the IDE.

**Balance to strike:** the skill should still **offer guidance** —
name what it sees, suggest next steps, ask clarifying questions, do
the annotation pass. What it should *not* do by default is jump
autonomously into "let me fix this for you" code paths. The
conservative posture is **observe → annotate → offer**, not
**observe → diagnose → act**.

**Shape of the fix:**

- Tighten the bundled SKILL.md so reaction-to-artifacts defaults to
  the conservative posture, and the more agentic behavior is opt-in
  ("yes, debug it" from the user).
- Possibly distinguish two registration modes — project-being-built
  vs. project-being-worked-in — but the simpler version is to make
  the conservative posture the default and let the user explicitly
  ask for more.
- Carry this through to how the skill describes itself, so the
  expectation a session sets on first encounter is the right one.

**Triage:** **fix-soon** — real refinement target. Doesn't block this
dogfood sprint but worth resolving before recruiting the first
external tester (brother).

