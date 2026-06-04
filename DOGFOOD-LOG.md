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

### 2026-06-03 evening — Permission prompts during artifact processing

From the electronics project dogfood: as artifacts arrive, the session
gets repeatedly prompted to approve reads from
`~/.project-notebook/artifacts/<project>/<file>.d/`, runs of
conversion tools, etc. — at exactly the moment the user wants the
experience to feel transparent and AirDrop-like. Each prompt is a
small jolt out of flow.

No clear resolution yet. Claude Code's per-directory permission model
is the right design for safety in general, but the artifact directory
is structurally *outside* the user's project tree, so the session has
no pre-existing trust relationship with it.

Directions worth thinking about (not committing to one yet):

- `install-claude-code-skill` writes a permission rule for
  `~/.project-notebook/` into `~/.claude/settings.json` on install,
  so the trust is granted once at install time.
- The skill installer prompts for the artifact-dir permission and
  shows the user what it's doing.
- The skill SKILL.md instructs the session to ask the user *once* per
  session for blanket access to the artifact dir, then proceed.
- Just document the "approve with 'always allow' for this path" UX
  so users flip the bit themselves and stop being prompted.

**Triage:** **open**. Needs more dogfooding data on how often this
fires, which specific tools trigger it, and how disruptive it feels
before picking a direction.

### 2026-06-03 evening — `register` named the project after a subdirectory

The session running on the electronics project was in a subdirectory
when it ran `project-notebook register` (no explicit name). The CLI
defaults the project name to `Path.cwd().name`, so the hub got the
*subdirectory's* name as the project — not the project root the user
intuitively means.

Real correctness bug. The "project" the user thinks they're
registering is the repo / working tree root, not wherever they happen
to be sitting in the tree when they invoke the skill.

**Shape of the fix:** walk up from `cwd` looking for a project-root
marker — `.git` is the universal one, `pyproject.toml` /
`package.json` / `.hg` are fallbacks — and use the directory that
contains it as the project. Fall back to `cwd` only if no marker is
found. Also print the resolved name **and path** prominently when
registration succeeds so a mis-registered case is immediately
visible.

In the meantime: `cd` to the project root before running `register`,
or pass the project name explicitly (`/notebook-register anova-oven`
on the skill side, or `project-notebook register anova-oven` on the
CLI side).

**Triage:** **fix-soon**. Clean fix, real bug, affects correctness of
every multi-directory project — which is most of them.

### 2026-06-03 evening — Session wrote `notes.md` instead of using `project-notebook annotate`

Asked to annotate the photos and videos coming in, the session in the
electronics project rolled its own and wrote a `notes.md` file
directly into the artifact directory. Steven had to interrupt it,
delete the file, and explicitly direct it at `project-notebook
annotate`.

Specific instance of the earlier "skills get too creative" pattern,
but sharper: the right tool already exists (`annotate`), is documented
in SKILL.md, and is the contract the rest of the system reads from —
ad-hoc `notes.md` files in the artifact dir don't surface anywhere.

**Shape of the fix:**

- Restructure SKILL.md so `project-notebook annotate` is presented as
  **the** way to annotate, not "an option." The JSON payload schema is
  the contract; sessions write through that, not around it.
- Add an explicit guardrail in SKILL.md: *do not write your own files
  into the artifact directory*. The sidecar dir is hub-managed; the
  contract is `annotations` on `meta.yaml`.
- Cross-reference: this is the same parent as the [17:00 entry on
  skill over-eagerness](#2026-06-03-1700-bundled-skill-is-too-eager-to-act-on-artifacts).

**Triage:** **fix-soon**. Same parent as the 17:00 entry. Could ship
as a SKILL.md-only update — installs through `project-notebook
install-claude-code-skill`, doesn't strictly need a version bump,
but cleanest bundled with the next release.

