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

