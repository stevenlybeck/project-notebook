# Project Notebook

A local hub plus CLI for ingesting artifacts (photos, video, audio, files)
from your phone into the project you're actively working on.

```
uv tool install project-notebook
project-notebook install-claude-code-skill   # register the Claude Code skill
project-notebook register                    # claim the current project; starts the hub if needed
```

Then share to your project from any app on your phone via the Project
Notebook Share Extension.

- `docs/architecture.md` — the artifact pipeline (hub ↔ agent).
- `docs/security.md` — the hub's three-plane access model.
- `docs/ios.md` — the iOS app's build/distribution state.
- `PLAN.md` — packaging and roadmap.
