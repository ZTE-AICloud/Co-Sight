#!/usr/bin/env python3
"""drive-record/generate_report.py — generate post-run replay HTML.

Output: self-contained HTML matching 00-docs/prototypes/01-replay.html structure.

Usage:
    python3 generate_report.py --plan-dir <path> [--out <path>]

Calls drive-viz/scripts/tokens.py for CSS tokens (per SKILL.md protocol).

Like render_dag.py, this is a RENDERER not a validator. Reads files directly
with PyYAML/JSON; tolerates missing fields gracefully.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# === drive-viz invocation (per skill protocol) ===
DRIVE_VIZ_SKILL = Path(__file__).parent.parent.parent / "drive-viz"


def tokens_css() -> str:
    """Call drive-viz scripts/tokens.py and return CSS."""
    result = subprocess.run(
        ["python3", str(DRIVE_VIZ_SKILL / "scripts/tokens.py"), "light"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


# === Data loading ===
def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_ts(s: str) -> str:
    return parse_ts(s).strftime("%H:%M:%S")


def fmt_dur_long(start: datetime, end: datetime) -> str:
    s = int((end - start).total_seconds())
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{sec:02d}s"


def fmt_ts_short(dt) -> str:
    """Format datetime as HH:MM. Accepts str (ISO) or datetime."""
    if isinstance(dt, str):
        dt = parse_ts(dt)
    return dt.strftime("%H:%M")


def load_plan(plan_dir: Path) -> dict:
    """Load all plan data into a dict. Tolerates missing fields."""
    plan_dir = Path(plan_dir)
    data = {
        "plan_name": plan_dir.name,
        "run_meta": {},
        "state": {},
        "events": [],
        "artifacts": [],
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

    artifacts_dir = plan_dir / "artifacts"
    if artifacts_dir.exists() and artifacts_dir.is_dir():
        arts = []
        for d in sorted(artifacts_dir.iterdir()):
            if not d.is_dir():
                continue
            summary = d / "SUMMARY.md"
            arts.append({
                "task_id": d.name,
                "summary_path": str(summary.relative_to(plan_dir.parent.parent)) if summary.exists() else None,
                "summary_lines": len(summary.read_text().splitlines()) if summary.exists() else 0,
            })
        data["artifacts"] = arts

    workflow_path = plan_dir.parent.parent / "workflow.yaml"
    if workflow_path.exists():
        try:
            import yaml
            data["workflow_yaml"] = yaml.safe_load(workflow_path.read_text())
        except Exception:
            pass

    return data


# === Renderers ===

def render_header(data: dict) -> str:
    """Top header: title, status, duration, commit."""
    run_meta = data.get("run_meta", {})
    state = data.get("state", {})

    plan_name = data.get("plan_name", "drive")
    plan_name_short = plan_name.split("plan-", 1)[-1] if "plan-" in plan_name else plan_name

    status = state.get("status", "unknown")
    if status == "completed":
        status_html = '<span class="badge badge-success">✓ Completed</span>'
    else:
        status_html = f'<span class="badge">{status}</span>'

    # Total duration: from drive_startup to drive_completed (or updated_at)
    events = data.get("events", [])
    started = None
    ended = None
    for e in events:
        if e.get("event") == "drive_startup":
            started = parse_ts(e["ts"])
        if e.get("event") == "drive_completed":
            ended = parse_ts(e["ts"])
    if started and not ended:
        ended = parse_ts(state.get("updated_at", started.isoformat()))

    duration = fmt_dur_long(started, ended) if started and ended else "—"

    commit = run_meta.get("git_head", "—")
    branch = run_meta.get("git_branch", "")

    return f"""
  <header class="header">
    <div class="title-block">
      <h1>drive-record 回放报告</h1>
      <div class="sub">{plan_name_short} · branch: {branch}</div>
    </div>
    <div class="meta">
      {status_html}
      <span style="font-family: var(--mono); color: var(--text); font-weight: 600;">{duration}</span>
      <span class="commit">{commit}</span>
    </div>
  </header>"""


def render_timeline(data: dict) -> str:
    """Gantt timeline + gate marker."""
    events = data.get("events", [])
    run_meta = data.get("run_meta", {})

    # Find start and end times
    started = None
    ended = None
    for e in events:
        if e.get("event") == "drive_startup":
            started = parse_ts(e["ts"])
        if e.get("event") == "drive_completed":
            ended = parse_ts(e["ts"])

    if not started:
        return ""  # can't render timeline without a start time
    if not ended:
        ended = datetime.now(timezone.utc)

    # Compute stage timings from stage_advanced events
    stage_adv = [e for e in events if e.get("event") == "stage_advanced"]
    stage_times: dict[str, tuple[datetime, datetime]] = {}
    for i, e in enumerate(stage_adv):
        stage = e.get("to")
        if not stage:
            continue
        start_ts = parse_ts(e["ts"])
        if i + 1 < len(stage_adv):
            end_ts = parse_ts(stage_adv[i + 1]["ts"])
        else:
            end_ts = ended
        stage_times[stage] = (start_ts, end_ts)

    # Lane definitions (canonical phase order)
    lanes_def = [
        ("analyze", "bar-analyze", "var(--c-analyze)"),
        ("plan", "bar-plan", "var(--c-plan)"),
        ("execute", "bar-execute", "var(--c-execute)"),
        ("evaluate", "bar-evaluate", "var(--c-evaluate)"),
    ]

    total_sec = (ended - started).total_seconds() or 1

    def lane_pct(stage):
        if stage not in stage_times:
            return None
        s, e = stage_times[stage]
        left = (s - started).total_seconds() / total_sec * 100
        width = (e - s).total_seconds() / total_sec * 100
        return left, width, fmt_dur_long(s, e)

    # Find gate marker location (between plan and execute = where plan-review happened)
    gate_marker = ""
    if "plan" in stage_times:
        plan_end = stage_times["plan"][1]
        gate_pct = (plan_end - started).total_seconds() / total_sec * 100
        # Look for confirmation_requested event for explicit gate text
        confirm = next((e for e in events if e.get("event") == "confirmation_requested"), None)
        gate_label_ts = fmt_ts(confirm["ts"]) if confirm else "—"
        gate_marker = f'<div class="gate-marker" style="left: {gate_pct:.1f}%;"></div>'

    lanes_html = []
    for stage, cls, _ in lanes_def:
        pct = lane_pct(stage)
        if pct is None:
            lanes_html.append(f'<div class="lane-label">{stage}</div><div class="lane-track"></div>')
            continue
        left, width, dur = pct
        bars_html = f'<div class="bar {cls}" style="left: {left:.1f}%; width: {width:.1f}%;">{dur}</div>'
        # Add gate marker to the last bar before gate
        if stage == "plan":
            lanes_html.append(f'<div class="lane-label">{stage}</div><div class="lane-track">{bars_html}{gate_marker}</div>')
        else:
            lanes_html.append(f'<div class="lane-label">{stage}</div><div class="lane-track">{bars_html}</div>')

    # Time axis
    n_marks = 5
    axis_marks = []
    for i in range(n_marks + 1):
        pct = i / n_marks * 100
        ts = started + (ended - started) * i / n_marks
        axis_marks.append(f'<span style="left: {pct:.0f}%; position: absolute;">{fmt_ts_short(ts)}</span>')

    return f"""
  <section class="section">
    <h2>Agent Timeline</h2>
    <div class="gantt">
      {''.join(lanes_html)}
    </div>
    <div class="time-axis" style="position: relative; margin-top: 8px; padding: 0 2px; margin-left: 104px;">
      {''.join(axis_marks)}
    </div>
  </section>"""


def render_events_and_artifacts(data: dict) -> str:
    """Two-column section: key events + artifacts per stage."""
    events = data.get("events", [])
    artifacts = data.get("artifacts", [])

    # Key events
    event_rows = []
    for e in events:
        ts = fmt_ts(e.get("ts", "—"))
        ev = e.get("event", "")
        if ev == "stage_advanced":
            icon = "→"
            detail = f'stage: <strong>{e.get("to", "")}</strong>'
        elif ev == "confirmation_requested":
            icon = "🚪"
            detail = '<span class="gate-event">plan-review requested</span>'
        elif ev == "transition_with_verdict":
            verdict = e.get("verdict", "—")
            color = "var(--c-success)" if verdict == "pass" else "var(--c-gate)"
            icon = "✓"
            detail = f'verdict: <strong style="color: {color};">{verdict}</strong>'
        elif ev == "drive_completed":
            icon = "🏁"
            detail = "drive_completed"
        elif ev == "drive_startup":
            continue  # skip, no useful info
        elif ev == "agent_spawned":
            continue  # too noisy for the summary
        else:
            continue
        event_rows.append(f'<li><time>{ts}</time> <span class="icon">{icon}</span> {detail}</li>')

    events_html = ''.join(event_rows) if event_rows else '<li><span style="color: var(--muted);">暂无</span></li>'

    # Artifacts
    art_rows = []
    for a in artifacts:
        task_short = a["task_id"].split("-")[-1] if "-" in a["task_id"] else a["task_id"]
        if a["summary_path"]:
            art_rows.append(
                f'<li><span class="name">{task_short}</span>'
                f'<span class="meta">{a["summary_path"]} · {a["summary_lines"]} lines</span></li>'
            )
        else:
            art_rows.append(f'<li><span class="name">{task_short}</span><span class="meta">暂无 SUMMARY.md</span></li>')

    art_html = ''.join(art_rows) if art_rows else '<li><span style="color: var(--muted);">暂无</span></li>'

    return f"""
  <div class="two-col">
    <section class="col">
      <h2>关键事件 (from run-log.jsonl)</h2>
      <ul class="list">
        {events_html}
      </ul>
    </section>
    <section class="col">
      <h2>Artifacts (from artifacts/)</h2>
      <ul class="list">
        {art_html}
      </ul>
    </section>
  </div>"""


def render_footer(data: dict) -> str:
    """Footer: underlying files (git-auditable)."""
    plan_dir = Path(data.get("plan_dir_path", "."))
    run_meta = data.get("run_meta", {})
    state = data.get("state", {})

    items = [
        f'executeState.json · revision {state.get("revision", "—")}',
        f'run-log.jsonl · {len(data.get("events", []))} events',
        "workflow.yaml",
    ]
    if run_meta.get("workflow_hash"):
        items.append(f'run-meta.json · workflow_hash {run_meta["workflow_hash"][:20]}...')

    items_html = ''.join(f'<li>{item}</li>' for item in items)

    return f"""
  <footer class="section footer">
    <h2>底层文件 (git 可审计)</h2>
    <ul>
      {items_html}
    </ul>
  </footer>"""


def render_html(data: dict) -> str:
    """Main render function."""
    css = tokens_css()

    header = render_header(data)
    timeline = render_timeline(data)
    events_section = render_events_and_artifacts(data)
    footer = render_footer(data)

    plan_name = data.get("plan_name", "drive")
    n_events = len(data.get("events", []))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>drive-record 回放 · {plan_name}</title>
<style>{css}
/* === drive-record replay component CSS === */
body {{ margin: 0; padding: 32px; font: 14px/1.5 -apple-system, "Segoe UI", system-ui, "PingFang SC", sans-serif; color: var(--text); background: var(--bg); }}
.phase-tag {{ display: inline-flex; align-items: center; gap: 6px; font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); background: #e2e8f0; padding: 4px 10px; border-radius: 999px; margin-bottom: 16px; font-weight: 600; }}
.phase-tag::before {{ content: "▸"; color: var(--c-plan); }}
.report {{ max-width: 1200px; margin: 0 auto; background: var(--card); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04); }}
.header {{ display: flex; align-items: center; padding: 22px 28px; border-bottom: 1px solid var(--border); background: linear-gradient(180deg, #fafbfc, #ffffff); gap: 20px; }}
.header .title-block {{ flex: 1; min-width: 0; }}
.header h1 {{ margin: 0 0 4px; font-size: 19px; font-weight: 600; }}
.header .sub {{ color: var(--muted); font-family: var(--mono); font-size: 12.5px; }}
.header .meta {{ display: flex; gap: 18px; align-items: center; font-size: 13px; }}
.header .meta .commit {{ font-family: var(--mono); color: var(--muted); background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
.badge {{ display: inline-flex; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
.badge-success {{ background: #d1fae5; color: #065f46; }}
.section {{ padding: 24px 28px; border-bottom: 1px solid var(--border); }}
.section:last-child {{ border-bottom: none; }}
.section h2 {{ margin: 0 0 18px; font-size: 11.5px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
.gantt {{ display: grid; grid-template-columns: 90px 1fr; gap: 10px 14px; align-items: center; }}
.lane-label {{ text-align: right; font-size: 12.5px; font-weight: 600; }}
.lane-track {{ position: relative; height: 36px; background: var(--track); border-radius: 6px; border: 1px solid #e2e8f0; }}
.bar {{ position: absolute; top: 4px; bottom: 4px; border-radius: 4px; display: flex; align-items: center; padding: 0 10px; color: white; font-size: 11.5px; font-weight: 600; font-family: var(--mono); white-space: nowrap; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }}
.bar-analyze {{ background: linear-gradient(180deg, #60a5fa, var(--c-analyze)); }}
.bar-plan {{ background: linear-gradient(180deg, #c084fc, var(--c-plan)); }}
.bar-execute {{ background: linear-gradient(180deg, #34d399, var(--c-execute)); }}
.bar-evaluate {{ background: linear-gradient(180deg, #fb923c, var(--c-evaluate)); }}
.gate-marker {{ position: absolute; top: -6px; bottom: -6px; width: 2px; background: var(--c-gate); }}
.gate-marker::before {{ content: "GATE"; position: absolute; top: -14px; left: 50%; transform: translateX(-50%); color: var(--c-gate); font-size: 9.5px; font-weight: 800; letter-spacing: 0.08em; background: white; padding: 1px 5px; border: 1px solid var(--c-gate); border-radius: 3px; }}
.time-axis {{ font-family: var(--mono); font-size: 11px; color: var(--muted); height: 16px; }}
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; }}
.col {{ padding: 22px 28px; }}
.col:first-child {{ border-right: 1px solid var(--border); }}
ul.list {{ list-style: none; margin: 0; padding: 0; }}
ul.list li {{ padding: 6px 0; border-bottom: 1px dashed #e2e8f0; font-size: 13px; display: flex; align-items: baseline; gap: 10px; }}
ul.list time {{ font-family: var(--mono); color: var(--muted); font-size: 11.5px; min-width: 60px; }}
ul.list .name {{ font-weight: 600; min-width: 80px; font-family: var(--mono); font-size: 12.5px; }}
ul.list .meta {{ color: var(--muted); font-size: 12px; }}
ul.list .icon {{ font-size: 12px; min-width: 14px; text-align: center; }}
ul.list .gate-event {{ color: var(--c-gate); }}
.footer ul {{ list-style: none; margin: 0; padding: 0; display: flex; gap: 12px; flex-wrap: wrap; }}
.footer li {{ font-family: var(--mono); font-size: 12px; padding: 7px 13px; background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; color: var(--muted); }}
</style>
</head>
<body>
<div class="phase-tag">drive-record · replay · {plan_name} · {n_events} events</div>
<div class="report">
{header}
{timeline}
{events_section}
{footer}
</div>
</body></html>
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plan-dir", required=True, type=Path)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    data = load_plan(args.plan_dir)
    data["plan_dir_path"] = str(args.plan_dir)
    html = render_html(data)

    if args.out:
        args.out.write_text(html)
        print(f"wrote {args.out} ({len(html)} bytes)")
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()