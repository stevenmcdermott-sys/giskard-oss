# Giskard Scan UI

A small web app for running a `giskard-scan` vulnerability scan (red teaming, prompt
injection, jailbreaks) from a browser, with separate model configuration for the
**Attacker**, **Target**, and **Judge** roles and live per-scenario progress as the
scan runs.

## What it is

- **Backend** (`backend/`): FastAPI service that wraps `giskard.scan` + `giskard.checks`.
  A single `POST /api/scan` streams progress over Server-Sent Events as each scenario
  finishes, then offers the completed run as a downloadable static HTML report (reusing
  `SuiteResult.to_html()` from `giskard-checks`).
- **Frontend** (`backend/static/`): a dependency-free HTML/CSS/vanilla-JS single page,
  served directly by the FastAPI app. No build step.

API keys are typed into the form for each scan and used only for the duration of that
request — never written to disk, a database, or `localStorage`.

## Important limitation: Attacker vs Judge

`giskard-scan`'s built-in generators don't expose a single point where "attacker model"
and "judge model" are cleanly separable:

- Only the **Adversarial** attack generator accepts an explicit model override.
- **Crescendo** and **GOAT** (the other two LLM-driven attack generators) always call
  `giskard-checks`' process-global default generator internally.
- Every LLM-as-judge check attached to generated scenarios also falls back to that same
  global default unless a generator was explicitly attached at construction time — which
  the scan's built-in generators don't do.

This app sets that shared global default to the **Judge** config for the duration of a
run (since judge correctness drives pass/fail results), and passes the **Attacker**
config explicitly to the Adversarial generator only. In practice: Attacker distinctly
affects the "Adversarial" scenario category; Crescendo, GOAT, and all judge checks use
the Judge model. See `backend/app/scan_runner.py` for the exact wiring.

Because of the shared global state, **one scan runs at a time per server process** — a
second request while one is in flight gets an immediate HTTP 409 rather than being
queued or corrupting the first run.

## Local development

```sh
cd apps/scan-ui/backend
uv sync
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000.

## Deploying to Railway

This app lives inside the `giskard-oss` monorepo and depends on the sibling `libs/*`
packages via local path dependencies, so the Docker build needs the **whole repo** as
its build context, not just `apps/scan-ui/backend/`.

1. Push this repo to GitHub (or use the Railway CLI from a local clone) and create a new
   Railway project from it.
2. Railway auto-detects the root-level `railway.json`, which points at
   `apps/scan-ui/backend/Dockerfile` and keeps the build context at the repo root — no
   manual "Root Directory" configuration needed.
3. Deploy. Railway sets `$PORT` automatically; the Dockerfile's `CMD` binds to it.
4. No environment variables are required — all LLM credentials are supplied per-scan
   through the UI.

## API

- `GET /api/providers` — provider id → display label, for populating the model
  selection dropdowns.
- `POST /api/scan` — body is a scan request (attacker/target/judge configs, target
  system prompt, scan options); response is `text/event-stream` with `scenario`,
  `generated`, `done`, and `error` events.
- `GET /api/scan/{scan_id}/report` — downloadable static HTML report for a completed
  scan (kept in memory for the last 10 completed scans; cleared on restart).
