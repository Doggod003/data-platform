# Architecture Notes

## Why this layout

- **src layout** prevents accidental imports of uninstalled code and keeps the
  package boundary clean.
- **pipelines/** — each data/automation job is an isolated module with
  `extract() / transform() / load() / run()`. Easy to test, easy to schedule.
- **integrations/** — reusable clients (APIs, databases) shared across pipelines,
  so no pipeline talks to an external service directly.
- **config.py** — one place for settings, driven by environment variables via
  pydantic-settings. Nothing secret lives in code.

## Decisions log

| Date | Decision | Why |
|------|----------|-----|
| 2026-07-20 | src layout + hatchling + ruff + pytest | Modern defaults, minimal config |
