---
name: startup
description: Use when a drive workflow needs to initialize a fresh project — the orchestrator invokes this before spawning the analyze phase agent when .drive/<plan_dir>/ does not yet exist. Also auto-starts drive-trace server (live browser-viewable trace) unless live_trace=false. Not user-invocable.
user-invocable: false
allowed-tools: Bash(python3 *init_planning.py*), Bash(python3 *discover_inputs.py*), Bash(nohup python3 *serve.py*), Bash(kill *)
---

## Parameters

- `intent` (required)
- `auto` (default `false`)
- `work_dir` (default `.`)
- `live_trace` (default `true`) — whether to auto-start drive-trace server for browser-viewable trace

## Procedure

```
- [ ] 1. Resolve plan-name (see below)
- [ ] 2. Run init_planning.py to build skeleton
- [ ] 3. Run discover_inputs.py
- [ ] 4. Start drive-trace server (if live_trace=true)
- [ ] 5. Return envelope (includes trace_pid + trace_url when live_trace started)
```

### 1. Resolve plan-name

Priority (mutually exclusive):

1. `${CLAUDE_SKILL_ARGS}` / `$0`
2. git branch (only when in a git worktree, kebab-case, not starting with `.`)
3. AskUserQuestion (examples: `add-user-auth`, `fix-import-deadlock`)

Constraints: `[a-z0-9-]`, 1-64 chars, no leading/trailing `-`, not `.` / `..`.

### 2. Build skeleton

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/init_planning.py" \
  --work-dir <work_dir> \
  --plan-name <plan_name> \
  [--intent "<intent>"] [--auto]
```

Read `data.plan_dir` from stdout. `active_stage` defaults to `None`.

### 3. Scan inputs

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/discover_inputs.py" --work-dir <work_dir>
```

### 4. Start drive-trace server

If `live_trace=true` (default), start drive-trace as background daemon. The orchestrator will then use `chrome-devtools navigate_page(trace_url)` to auto-open a browser tab (if chrome-devtools MCP is available).

```bash
nohup python3 "${CLAUDE_PLUGIN_ROOT}/skills/drive-trace/scripts/serve.py" \
  --plan-dir <plan_dir> \
  --port 8080 \
  --mode phase \
  > .drive-trace.log 2>&1 &
TRACE_PID=$!
```

Capture `TRACE_PID` and a candidate port (8080, or fall back to 8081 / 8082 if taken).

**Why nohup + &**: drive-trace must survive if startup's Bash session exits. nohup detaches from terminal; `&` backgrounds.

**Failure mode**: If port unavailable, try 8081, 8082, etc. If start still fails, log warning to envelope and continue (drive doesn't fail because trace is unavailable — degrades gracefully).

### 5. Return envelope

```json
{"ok": true, "data": {"plan_name": "<plan_name>", "plan_dir": "<plan_dir>", "intent": "<intent>", "auto_mode": false, "trace_pid": 1216164, "trace_url": "http://127.0.0.1:8080/"}}
{"ok": false, "reason": "REASON_*", "details": {...}}
```

When `trace_pid` / `trace_url` are set, the orchestrator (or subsequent Claude invocation) should:
- Use `chrome-devtools navigate_page(trace_url)` if chrome-devtools MCP is available, to auto-open browser tab
- Otherwise pass `trace_url` to user via chat so they can open it manually

## Cleanup (called by orchestrator on drive completion)

```bash
kill <trace_pid> 2>/dev/null
```

drive-trace `serve.py` handles SIGTERM cleanly (shuts down HTTPServer, exits 0).