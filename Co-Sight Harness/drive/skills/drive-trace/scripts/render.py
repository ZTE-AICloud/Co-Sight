#!/usr/bin/env python3
"""drive-trace render: generate live trace HTML from plan_dir data.

Pure HTML generation function — no HTTP, no I/O orchestration. Tests use this
directly with mocked data dict.

Output protocol:
- Self-contained HTML with inline drive-viz tokens CSS + meta-refresh (2s)
- Reads from .drive/<plan_dir>/ via load_data()
- Renders: phase-tag → status-bar → gate-banner (if pending) → trace stream
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_ts(s: str) -> str:
    return parse_ts(s).strftime("%H:%M:%S")


def fmt_dur(start: datetime, end: datetime) -> str:
    s = int((end - start).total_seconds())
    if s < 0:
        return "—"
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{sec:02d}s"


def load_data(plan_dir: Path, mode: str = "phase") -> dict:
    """Load all relevant data from plan_dir into a dict.

    plan_dir: Path to .drive/<plan_dir>/
    mode: "phase" or "dag" (UI hint only; actual data is the same)

    Returns dict with: plan_name, mode, plan_dir_path, run_meta, state, events, workflow_yaml
    """
    plan_dir = Path(plan_dir)
    data = {
        "plan_name": plan_dir.name,
        "mode": mode,
        "plan_dir_path": str(plan_dir),
        "run_meta": {},
        "state": {},
        "events": [],
        "workflow_yaml": None,
    }

    run_meta_path = plan_dir / "run-meta.json"
    if run_meta_path.exists():
        try:
            data["run_meta"] = json.loads(run_meta_path.read_text())
            data["plan_name"] = data["run_meta"].get("plan_name", plan_dir.name)
        except Exception:
            pass

    state_path = plan_dir / "executeState.json"
    if state_path.exists():
        try:
            data["state"] = json.loads(state_path.read_text())
        except Exception:
            pass

    log_path = plan_dir / "run-log.jsonl"
    if log_path.exists():
        events = []
        for line in log_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass
        data["events"] = events

    # workflow.yaml is one level up
    workflow_path = plan_dir.parent.parent / "workflow.yaml"
    if workflow_path.exists():
        try:
            data["workflow_yaml"] = workflow_path.read_text()
        except Exception:
            pass

    return data


def _get_tokens_css(mode: str) -> str:
    """Read drive-viz tokens via the skill's CLI (per SKILL.md protocol).

    drive-trace is a sibling skill to drive-viz under 03-drive-core/skills/.
    Invocation per drive-viz/SKILL.md: run scripts/tokens.py [mode], capture stdout.
    """
    import subprocess
    drive_viz_dir = Path(__file__).parent.parent.parent / "drive-viz"
    result = subprocess.run(
        ["python3", str(drive_viz_dir / "scripts/tokens.py"), mode],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def render_html(data: dict, mode: str = "phase") -> str:
    """Render the live trace HTML.

    Args:
        data: dict from load_data()
        mode: drive-trace's UI mode — "phase" or "dag". UI rendering is the
              same for both; we pass drive-viz its own theme (dark for trace
              view, matching the 02-runtime prototype).

    Returns: HTML string starting with <!DOCTYPE html>
    """
    try:
        css = _get_tokens_css("dark")  # drive-trace view is always dark
    except Exception:
        css = ":root { --c-analyze: #3b82f6; }"  # minimal fallback

    plan_name = data.get("plan_name", "drive-trace")
    state = data.get("state", {})
    events = data.get("events", [])

    status_bar = _render_status_bar(data)
    gate_banner = _render_gate_banner(data)
    stream = _render_trace_stream(data, mode)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="2">
<title>drive-trace · {plan_name}</title>
<style>
{css}
/* === drive-trace component CSS (using drive-viz tokens) === */
body {{ margin: 0; padding: 24px; font: 14px/1.5 -apple-system, "Segoe UI", system-ui, "PingFang SC", sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
.phase-tag {{ display: inline-flex; align-items: center; gap: 6px; font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); background: var(--card-2); padding: 4px 10px; border-radius: 999px; margin-bottom: 16px; font-weight: 600; border: 1px solid var(--border-light); }}
.phase-tag::before {{ content: "▸"; color: var(--c-running); }}
.status-bar {{ display: flex; align-items: center; padding: 16px 24px; background: var(--card); border: 1px solid var(--border-light); border-radius: 12px; gap: 32px; margin-bottom: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.2); }}
.status-pill {{ display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 13px; letter-spacing: 0.08em; color: var(--c-amber); }}
.led {{ width: 12px; height: 12px; border-radius: 50%; background: var(--c-amber); box-shadow: 0 0 16px var(--c-amber); animation: pulse 1.4s ease-in-out infinite; }}
@keyframes pulse {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.5; transform: scale(0.85); }} }}
.status-meta {{ display: flex; gap: 36px; flex: 1; font-family: var(--mono); }}
.status-meta .kv {{ display: flex; flex-direction: column; gap: 3px; }}
.status-meta .k {{ font-size: 9.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; font-family: -apple-system, sans-serif; font-weight: 600; }}
.status-meta .v {{ color: var(--text); font-weight: 600; font-size: 14px; }}
.status-meta .v.amber {{ color: var(--c-amber); }}
.gate-banner {{ display: flex; align-items: center; gap: 16px; padding: 16px 24px; background: linear-gradient(90deg, rgba(251,191,36,0.14), rgba(251,191,36,0.04) 70%, transparent); border: 1px solid rgba(251,191,36,0.35); border-radius: 10px; margin-bottom: 16px; position: relative; overflow: hidden; }}
.gate-banner::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--c-amber); }}
.gate-banner .icon {{ font-size: 22px; }}
.gate-banner .text {{ flex: 1; }}
.gate-banner strong {{ color: var(--c-amber); display: block; font-size: 13px; letter-spacing: 0.06em; margin-bottom: 2px; }}
.gate-banner span {{ color: var(--muted); font-size: 12.5px; }}
.gate-banner .countdown {{ font-family: var(--mono); font-size: 12px; color: var(--c-amber); background: rgba(251,191,36,0.1); padding: 4px 10px; border-radius: 4px; }}
.stream-hint {{ display: flex; align-items: center; gap: 10px; padding: 4px 4px 0; font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); font-weight: 700; }}
.stream-hint::before, .stream-hint::after {{ content: ""; flex: 1; height: 1px; background: var(--border); }}
.stream-hint.past {{ color: var(--c-success); opacity: 0.6; }}
.stream-hint.now {{ color: var(--c-amber); }}
.stream-hint.future {{ color: var(--muted); }}
.trace-card {{ background: var(--card); border: 1px solid var(--border-light); border-radius: 10px; overflow: hidden; margin-bottom: 8px; }}
details.trace-card[open] {{ background: var(--card-2); }}
.trace-card > summary {{ list-style: none; cursor: pointer; padding: 12px 18px; display: flex; align-items: center; gap: 12px; user-select: none; outline: none; }}
.trace-card > summary::-webkit-details-marker {{ display: none; }}
.trace-card .icon {{ width: 18px; text-align: center; font-family: var(--mono); font-size: 14px; }}
.trace-card .name {{ font-weight: 600; }}
.trace-card .name .agent-id {{ font-weight: 400; color: var(--muted); font-family: var(--mono); font-size: 11px; margin-left: 6px; }}
.trace-card .badge {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; padding: 2px 8px; border-radius: 4px; font-weight: 700; }}
.trace-card .summary-meta {{ margin-left: auto; display: flex; align-items: center; gap: 10px; font-family: var(--mono); font-size: 12px; color: var(--muted); }}
.trace-card .toggle {{ color: var(--muted); font-size: 11px; }}
details.trace-card[open] > summary .toggle {{ transform: rotate(90deg); display: inline-block; transition: transform 0.2s; }}
.trace-card.done {{ opacity: 0.68; }}
.trace-card.done > summary {{ padding: 9px 18px; }}
.trace-card.done .icon {{ color: var(--c-success); }}
.trace-card.done .name {{ font-weight: 500; }}
.trace-card.done .badge {{ background: rgba(16, 185, 129, 0.14); color: var(--c-success); }}
.trace-card.done[open] {{ opacity: 1; }}
.trace-card.running {{ border-color: rgba(96, 165, 250, 0.5); }}
.trace-card.running .icon {{ color: var(--c-amber); animation: pulse 1.4s ease-in-out infinite; }}
.trace-card.running .badge {{ background: rgba(251, 191, 36, 0.2); color: var(--c-amber); }}
.trace-card.gate {{ border-color: rgba(251, 191, 36, 0.55); box-shadow: 0 0 0 1px rgba(251, 191, 36, 0.2); }}
.trace-card.gate > summary {{ background: linear-gradient(90deg, rgba(251, 191, 36, 0.12), transparent); }}
.trace-card.gate .icon {{ color: var(--c-amber); }}
.trace-card.gate .badge {{ background: rgba(251, 191, 36, 0.22); color: var(--c-amber); }}
.trace-card.queued {{ opacity: 0.4; }}
.trace-card.queued > summary {{ padding: 9px 18px; cursor: default; }}
.trace-card.queued > summary:hover {{ background: transparent; }}
.trace-card.queued .icon {{ color: var(--muted); }}
.trace-card.queued .name {{ color: var(--muted); font-weight: 500; }}
.trace-card.queued .badge {{ background: rgba(71, 85, 105, 0.3); color: var(--muted); }}
.trace-card.queued .toggle {{ display: none; }}
.trace-body {{ padding: 8px 18px 14px; border-top: 1px solid var(--border); }}
.kv-line {{ display: flex; justify-content: space-between; font-size: 12.5px; padding: 3px 0; font-family: var(--mono); }}
.kv-line .k {{ color: var(--muted); }}
.kv-line .v {{ color: var(--text); text-align: right; max-width: 60%; }}
.empty {{ color: var(--muted); font-style: italic; }}
.footer-link {{ margin-top: 12px; text-align: center; font-family: var(--mono); font-size: 11px; color: var(--muted); }}
</style>
</head>
<body>
<div class="phase-tag">drive-trace · live · {plan_name} · auto-refresh 2s · {len(events)} events</div>

{status_bar}
{gate_banner}

<div class="trace-stream">
{stream}
</div>

<div class="footer-link">
drive-trace · meta-refresh 2s polling · /drive execution · <code>chrome-devtools</code> auto-open via startup
</div>

</body>
</html>
"""


def _render_status_bar(data: dict) -> str:
    state = data.get("state", {})
    active_stage = state.get("active_stage", "—")
    status = state.get("status", "unknown")
    current_wave = state.get("current_wave", "—")
    waves_total = state.get("waves_total", "—")
    revision = state.get("revision", "—")

    run_meta = data.get("run_meta", {})
    started_at = run_meta.get("started_at")

    if started_at:
        try:
            start_dt = parse_ts(started_at)
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc)
            elapsed_s = int((now - start_dt).total_seconds())
            m, sec = divmod(elapsed_s, 60)
            elapsed = f"{m}m{sec:02d}s"
        except Exception:
            elapsed = "—"
    else:
        elapsed = "—"

    if status == "completed":
        status_label = "COMPLETED"
        status_color = "var(--c-success)"
    elif state.get("pending_confirmation"):
        status_label = f"AWAITING HUMAN · {state['pending_confirmation']}"
        status_color = "var(--c-amber)"
    elif status == "executing":
        status_label = "RUNNING"
        status_color = "var(--c-amber)"
    else:
        status_label = status.upper()
        status_color = "var(--text)"

    return f"""
<div class="status-bar">
  <div class="status-pill" style="color: {status_color};">
    <span class="led"></span>
    {status_label}
  </div>
  <div class="status-meta">
    <div class="kv"><span class="k">当前阶段</span><span class="v">{active_stage}</span></div>
    <div class="kv"><span class="k">revision</span><span class="v">{revision}</span></div>
    <div class="kv"><span class="k">wave</span><span class="v">{current_wave} / {waves_total}</span></div>
    <div class="kv"><span class="k">已耗时</span><span class="v amber">{elapsed}</span></div>
  </div>
</div>
"""


def _render_gate_banner(data: dict) -> str:
    state = data.get("state", {})
    pending = state.get("pending_confirmation")
    if not pending:
        return ""

    events = data.get("events", [])
    confirm_event = next((e for e in reversed(events) if e.get("event") == "confirmation_requested"), {})

    ts = fmt_ts(confirm_event.get("ts", "—")) if confirm_event else "—"

    return f"""
<div class="gate-banner">
  <span class="icon">🟡</span>
  <div class="text">
    <strong>AWAITING HUMAN INPUT</strong>
    <span>{pending}-review gate is open · confirmation_requested @ {ts}</span>
  </div>
  <div class="countdown">⏱ waiting</div>
</div>
"""


def _render_trace_stream(data: dict, mode: str) -> str:
    state = data.get("state", {})
    events = data.get("events", [])

    # Mode dispatch: explicit mode=='dag' OR state.active_agents non-empty (DAG mode signal)
    is_dag = (mode == "dag") or bool(state.get("active_agents"))

    if is_dag:
        return _render_dag_stream(data)

    pending = state.get("pending_confirmation")
    confirmed_stages = set(state.get("confirmed_stages", []))
    active_stage = state.get("active_stage")

    # Derive phase-mode agent list from workflow.yaml (simple parsing)
    # or fall back to canonical 4-agent list
    workflow_yaml = data.get("workflow_yaml", "")
    phase_agents = _parse_phase_agents(workflow_yaml)

    # Build per-agent trace
    spawned_by_agent = {}
    for e in events:
        if e.get("event") == "agent_spawned":
            agent = e.get("subagent_type", "").replace("drive:", "")
            spawned_by_agent.setdefault(agent, []).append(e)

    sections = []

    # Past (confirmed stages) - synthesize from confirmed_stages
    past = []
    for stage in confirmed_stages:
        if stage == "start":
            continue
        agent = phase_agents.get(stage, stage)
        past.append({
            "agent": agent,
            "stage": stage,
            "spawned_events": spawned_by_agent.get(agent, []),
            "ts": "—",
            "duration": "—",
        })

    sections.append('<div class="stream-hint past">past · {} done</div>'.format(len(past)))

    past_html = ""
    for p in past:
        cards = _render_agent_card(
            agent=p["agent"],
            stage=p["stage"],
            events=p["spawned_events"],
            status="done",
            expanded=False,
            running_skill=None,
        )
        past_html += cards

    sections.append(past_html)

    # Now: pending gate or running agent
    if pending:
        sections.append('<div class="stream-hint now">↓ now · awaiting human</div>')
        gate_card = _render_gate_card(pending)
        sections.append(gate_card)
    elif active_stage and active_stage not in confirmed_stages and active_stage != "completed":
        # Running stage
        agent = phase_agents.get(active_stage, active_stage)
        running_events = spawned_by_agent.get(agent, [])
        sections.append('<div class="stream-hint now">↓ now · running</div>')
        sections.append(_render_agent_card(agent=agent, stage=active_stage, events=running_events, status="running", expanded=True, running_skill=None))

    # Future (queued stages after current)
    future = []
    if pending or active_stage:
        current = pending if pending else active_stage
        all_stages = ["start", "analyze", "plan", "execute", "evaluate"]
        current_idx = all_stages.index(current) if current in all_stages else -1
        for i, stage in enumerate(all_stages):
            if i <= current_idx:
                continue
            if stage in confirmed_stages:
                continue
            agent = phase_agents.get(stage, stage)
            future.append({"agent": agent, "stage": stage})

    if future:
        sections.append(f'<div class="stream-hint future">future · {len(future)} queued</div>')
        for f in future:
            sections.append(_render_queued_card(f["agent"], f["stage"]))

    return "\n".join(sections)


def _render_dag_stream(data: dict) -> str:
    """DAG-mode trace: group state.active_agents[] by wave; show each agent's
    input (prompt_excerpt from agent_spawned), command counts (bash_called),
    skill counts (skill_tool_called), output files (artifacts/W{wave}_{id}_*).

    The user-reported symptom was: only "wave 4 / 8" displayed, no agents or
    inputs/outputs. This branch addresses that.
    """
    state = data.get("state", {})
    events = data.get("events", [])
    plan_dir = data.get("plan_dir_path")
    active_agents = state.get("active_agents") or []
    current_wave = state.get("current_wave", 0)

    if not active_agents:
        return '<div class="stream-hint">no active agents</div>'

    # Build per-agent event indices by matching subagent_type to agent.id.
    # Note: state.active_agents[].started_at is NOT the agent's spawn time —
    # it's when the orchestrator first wrote active_agents[] (uniform for all
    # agents). Use agent_spawned event ts as the lower bound and updated_at
    # (or "now" if running) as the upper bound.
    spawned_events_by_agent: dict[str, list] = {a["id"]: [] for a in active_agents}
    skill_counts_by_agent: dict[str, int] = {a["id"]: 0 for a in active_agents}
    bash_counts_by_agent: dict[str, int] = {a["id"]: 0 for a in active_agents}

    from datetime import datetime as _dt, timezone as _tz
    now_iso = _dt.now(_tz.utc)

    # Pre-compute each agent's effective time window from its (last) spawn_event
    # to updated_at.
    agent_windows: dict[str, tuple[_dt | None, _dt | None]] = {}
    for a in active_agents:
        sp_events = [e for e in events
                     if e.get("event") == "agent_spawned"
                     and e.get("subagent_type") == a["id"]]
        spawn_ts = None
        if sp_events:
            last = sp_events[-1].get("ts")
            if last:
                try:
                    spawn_ts = parse_ts(last)
                except Exception:
                    spawn_ts = None
        end_ts = None
        if a.get("updated_at"):
            try:
                end_ts = parse_ts(a["updated_at"])
            except Exception:
                end_ts = None
        if end_ts is None and a.get("status") == "running":
            end_ts = now_iso
        agent_windows[a["id"]] = (spawn_ts, end_ts)

    for e in events:
        et = e.get("event")
        ts_str = e.get("ts")
        if not ts_str:
            continue
        try:
            e_dt = parse_ts(ts_str)
        except Exception:
            continue

        if et == "agent_spawned":
            sub_type = e.get("subagent_type", "")
            for a in active_agents:
                if a["id"] == sub_type:
                    spawned_events_by_agent[a["id"]].append(e)
                    break
            continue

        if et in ("skill_tool_called", "bash_called"):
            for aid, (start, end) in agent_windows.items():
                if start and e_dt < start:
                    continue
                if end and e_dt > end:
                    continue
                if et == "skill_tool_called":
                    skill_counts_by_agent[aid] = skill_counts_by_agent.get(aid, 0) + 1
                else:
                    bash_counts_by_agent[aid] = bash_counts_by_agent.get(aid, 0) + 1
                # Note: bash/skill events with no specific agent attribution may
                # double-count if multiple agents are in the same wave with
                # overlapping time windows. Acceptable approximation for trace view.

    # Group agents by wave
    by_wave: dict[int, list[dict]] = {}
    for a in active_agents:
        by_wave.setdefault(a.get("wave", 0), []).append(a)
    max_wave = max(by_wave.keys()) if by_wave else 0

    sections = []

    for wave_idx in sorted(by_wave.keys()):
        wave_agents = by_wave[wave_idx]
        marker = " ← current" if wave_idx == current_wave else ""
        status_counts: dict[str, int] = {}
        for a in wave_agents:
            s = a.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        status_summary = " · ".join(
            f"{n} {s}" for s, n in sorted(status_counts.items(), key=lambda x: -x[1])
        )
        sections.append(
            f'<div class="stream-hint past">wave {wave_idx} · {len(wave_agents)} {"parallel" if len(wave_agents) > 1 else "agent"} · {status_summary}{marker}</div>'
        )
        for a in wave_agents:
            sections.append(
                _render_dag_agent_card(
                    agent=a,
                    spawned_events=spawned_events_by_agent.get(a["id"], []),
                    skill_count=skill_counts_by_agent.get(a["id"], 0),
                    bash_count=bash_counts_by_agent.get(a["id"], 0),
                    plan_dir=plan_dir,
                )
            )

    return "\n".join(sections)


def _render_dag_agent_card(
    agent: dict,
    spawned_events: list,
    skill_count: int,
    bash_count: int,
    plan_dir: str | None,
) -> str:
    """Render one DAG agent card with real input/output (vs prior "暂无" stub).

    Always renders expanded (input / skills / commands / output visible by
    default) — the user's report was that without expansion the data was
    invisible. Collapse is opt-in via clicking the card.
    """
    agent_id = agent.get("id", "?")
    status = agent.get("status", "unknown")
    wave = agent.get("wave", "?")
    started_at = agent.get("started_at", "")
    updated_at = agent.get("updated_at", "")

    if status == "running":
        icon = "⏳"
        badge_color = "var(--c-amber)"
    elif status == "completed":
        icon = "✓"
        badge_color = "var(--c-success)"
    elif status == "failed":
        icon = "✗"
        badge_color = "var(--c-error, #ef4444)"
    elif status == "pending":
        icon = "○"
        badge_color = "var(--muted)"
    else:
        icon = "·"
        badge_color = "var(--muted)"

    ts_display = "—"
    dur_display = "—"
    if started_at:
        try:
            start_dt = parse_ts(started_at)
            ts_display = fmt_ts(started_at)
            end_dt = parse_ts(updated_at) if updated_at else None
            if end_dt:
                dur_display = fmt_dur(start_dt, end_dt)
        except Exception:
            pass

    # Input: from latest agent_spawned event's prompt_excerpt (first 120 chars).
    # Re-spawned agents keep multiple events; use the most recent.
    excerpt = ""
    if spawned_events:
        excerpt = spawned_events[-1].get("prompt_excerpt", "")[:120]

    # Output: list artifact files matching W{wave}_{id}_* pattern
    output_paths: list[str] = []
    if plan_dir:
        artifacts_dir = Path(plan_dir) / "artifacts"
        if artifacts_dir.is_dir():
            for p in artifacts_dir.glob(f"W{wave}_{agent_id}_*"):
                if p.is_file():
                    output_paths.append(p.name)

    body_lines = []
    if excerpt:
        body_lines.append(f'<div class="kv-line"><span class="k">input (excerpt)</span><span class="v">{excerpt}</span></div>')
    else:
        body_lines.append('<div class="kv-line"><span class="k">input</span><span class="v empty">暂无</span></div>')

    body_lines.append(
        f'<div class="kv-line"><span class="k">skills called</span><span class="v">{skill_count} 次</span></div>'
    )
    body_lines.append(
        f'<div class="kv-line"><span class="k">commands run</span><span class="v">{bash_count} 次</span></div>'
    )

    if output_paths:
        # List up to 3 files
        shown_list = output_paths[:3]
        more = f" · +{len(output_paths) - 3} more" if len(output_paths) > 3 else ""
        body_lines.append(
            f'<div class="kv-line"><span class="k">output</span><span class="v">{", ".join(shown_list)}{more}</span></div>'
        )
    else:
        body_lines.append(f'<div class="kv-line"><span class="k">output</span><span class="v empty">暂无（artifacts/ 无 W{wave}_{agent_id}_*）</span></div>')

    body = "\n".join(body_lines)
    # Default-expand every card: the user's report was that inputs/outputs
    # "没有显示出来". Collapse is opt-in via clicking.
    open_attr = " open"

    return f"""
<details class="trace-card {status}"{open_attr}>
  <summary>
    <span class="icon">{icon}</span>
    <span class="name">{agent_id} <span class="agent-id">wave {wave}</span></span>
    <span class="badge" style="background: rgba(251, 191, 36, 0.2); color: {badge_color};">{status}</span>
    <span class="summary-meta">
      <span class="duration">{ts_display}</span>
      <span style="color: var(--muted);">· {dur_display}</span>
      <span class="toggle">▸</span>
    </span>
  </summary>
  <div class="trace-body">
{body}
  </div>
</details>
"""


def _render_agent_card(agent: str, stage: str, events: list, status: str, expanded: bool, running_skill) -> str:
    """Render a single trace card for an agent invocation."""
    if events:
        e = events[0]
        ts = fmt_ts(e.get("ts", "—"))
        excerpt = e.get("prompt_excerpt", "")
    else:
        ts = "—"
        excerpt = ""

    summary_md = ""
    artifact = ""

    if status == "running":
        badge_color = "var(--c-amber)"
        icon = "⏳"
    else:  # done
        badge_color = "var(--c-success)"
        icon = "✓"

    body = ""
    if excerpt:
        body += f'<div class="kv-line"><span class="k">input (excerpt)</span><span class="v">{excerpt[:80]}</span></div>'
    body += f'<div class="kv-line"><span class="k">skills called</span><span class="v empty">暂无（skill_tool_called event 暂无 emitter）</span></div>'
    body += f'<div class="kv-line"><span class="k">hooks fired</span><span class="v empty">暂无（需 PostToolUse 钩子）</span></div>'
    body += f'<div class="kv-line"><span class="k">output</span><span class="v empty">暂无</span></div>'

    open_attr = " open" if expanded else ""
    return f"""
<details class="trace-card {status}"{open_attr}>
  <summary>
    <span class="icon">{icon}</span>
    <span class="name">{agent} <span class="agent-id">drive:{agent}</span></span>
    <span class="badge" style="background: rgba(251, 191, 36, 0.2); color: {badge_color};">{status}</span>
    <span class="summary-meta">
      <span class="duration">{ts}</span>
      <span style="color: var(--muted);">· {stage}</span>
      <span class="toggle">▸</span>
    </span>
  </summary>
  <div class="trace-body">
{body}
  </div>
</details>
"""


def _render_gate_card(pending_stage: str) -> str:
    return f"""
<details class="trace-card gate" open>
  <summary>
    <span class="icon">🚪</span>
    <span class="name">{pending_stage}-review gate <span class="agent-id">on phase: {pending_stage}</span></span>
    <span class="badge">awaiting human</span>
    <span class="summary-meta">
      <span class="duration">—</span>
      <span class="toggle">▾</span>
    </span>
  </summary>
  <div class="trace-body">
    <div class="kv-line"><span class="k">agent finishing</span><span class="v">planner</span></div>
    <div class="kv-line"><span class="k">agent waiting</span><span class="v">executor</span></div>
    <div class="kv-line"><span class="k">enforced by</span><span class="v">state_transition_guard.py</span></div>
    <div class="kv-line" style="margin-top: 8px;"><span class="k">artifact to review</span><span class="v empty">taskRecord.yaml (fixture 缺)</span></div>
  </div>
</details>
"""


def _render_queued_card(agent: str, stage: str) -> str:
    return f"""
<div class="trace-card queued">
  <summary>
    <span class="icon">⌛</span>
    <span class="name">{agent} <span class="agent-id">drive:{agent}</span></span>
    <span class="badge">queued</span>
    <span class="summary-meta">
      <span class="duration">—</span>
      <span style="color: var(--muted);">· {stage}</span>
    </span>
  </summary>
</div>
"""


def _parse_phase_agents(workflow_yaml: str) -> dict:
    """Parse workflow.yaml to get stage → agent mapping (simple regex)."""
    import re
    result = {}
    if not workflow_yaml:
        # Default 5-stage canonical mapping (for workdir-demo)
        return {
            "start": "analyzer",
            "analyze": "analyzer",
            "plan": "planner",
            "execute": "executor",
            "evaluate": "evaluator",
        }

    # Find lines like "  - stage: analyze\n    agent: drive:analyzer"
    for stage_match in re.finditer(r"-\s*stage:\s*(\S+)\s*\n\s*agent:\s*drive:(\S+)", workflow_yaml):
        stage, agent = stage_match.group(1), stage_match.group(2)
        result[stage] = agent
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--plan-dir", required=True, type=Path)
    p.add_argument("--mode", choices=["phase", "dag"], default="phase")
    args = p.parse_args()
    data = load_data(args.plan_dir, args.mode)
    print(render_html(data, args.mode))