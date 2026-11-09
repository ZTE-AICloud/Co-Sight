---
name: drive-trace
description: Use when drive execution needs a live browser-viewable trace. Started by startup skill at /drive initialization as a background HTTP server; each request renders fresh HTML from .drive/<plan_dir>/ state. Not user-invocable.
user-invocable: false
disable-model-invocation: false
allowed-tools: []
---

# drive-trace

Live HTTP server that re-renders trace HTML on each request.

## Invocation

Drive orchestrator (specifically: startup skill) runs the server in background:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/serve.py \
    --plan-dir /path/to/.drive/<plan_dir> \
    [--port 8080] [--mode phase|dag]
```

Server binds to `127.0.0.1:<port>` by default. Returns HTML on every GET request, reading latest `executeState.json` + `run-log.jsonl` + workflow.yaml at request time.

Caller-side pattern: when orchestrator (startup) starts the server, it should also navigate a browser to the URL via `chrome-devtools navigate_page`. The page contains `<meta http-equiv="refresh" content="2">` so the browser polls every 2s.

## Lifecycle

- **Start**: `startup` skill spawns `serve.py` via `Bash(...)` as background process (use shell `&` or `nohup ... &`). Capture the PID.
- **Stop**: orchestrator on `/drive` completion sends `kill <PID>` (or SIGTERM via `Bash`). `serve.py` handles SIGTERM cleanly.

## Outputs

The HTML page renders:
- Status bar (current stage, elapsed, wave progress)
- Gate banner (when `pending_confirmation` is set)
- Trace stream (one card per agent invocation + gate card + queued stubs)
- All using drive-viz tokens (CSS variables from `drive-viz/scripts/tokens.py`)

`render.py` (this skill's, imported by serve.py) — pure HTML generation function. Tests can call `render_html(load_data(plan_dir), mode)` directly with mocked data.

## Errors

- `executeState.json` not yet created → page shows `"<active_session>"` placeholder, refresh picks up state once startup writes it
- `run-log.jsonl` missing → empty event list (page still works, just less data)
- Permission denied on port → startup should pick a different port (future enhancement)
- Plan dir doesn't exist → startup should NOT spawn server (startup checks first)

## Boundaries

- Does not write to `.drive/<plan_dir>/` (read-only observation)
- Does not spawn agents (passive observer)
- Does not parse `workflow.yaml` deeply (just stage → agent mapping for phase mode)
- Does not handle DAG-mode complex topologies (Q1=A2 ships phase first)