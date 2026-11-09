#!/usr/bin/env python3
"""workflow-builder/render_dag.py — render workflow.yaml as plan-review HTML.

Generates the same visual outputs as 00-docs/prototypes/03-phase.html +
03-dag.html, but driven by actual workflow.yaml data.

Usage:
    python3 render_dag.py --work-dir <path> [--selected <agent_id>] [--out <path>]

Calls drive-viz/scripts/tokens.py for CSS tokens (per SKILL.md protocol).

Note: render_dag is a RENDERER, not a validator. It uses PyYAML directly instead
of read_workflow.py's strict Envelope-validated parser — the renderer should
work on partial / loosely-formatted workflow.yaml without failing on missing
optional fields. Validation is workflow-builder's separate concern.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

# === drive-viz invocation (per skill protocol) ===
DRIVE_VIZ_SKILL = Path(__file__).parent.parent.parent / "drive-viz"


def tokens_css(mode: str = "light") -> str:
    """Call drive-viz scripts/tokens.py and return CSS."""
    result = subprocess.run(
        ["python3", str(DRIVE_VIZ_SKILL / "scripts/tokens.py"), mode],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def load_yaml(work_dir: Path) -> dict:
    """Load workflow.yaml as a raw dict. Tolerant of missing fields."""
    candidates = [work_dir / "workflow.yaml", work_dir / "workflow.yml"]
    for p in candidates:
        if p.exists():
            return yaml.safe_load(p.read_text())
    raise FileNotFoundError(f"No workflow.yaml in {work_dir}")


# === Mode detection ===
def detect_mode(data: dict) -> str:
    """phase / dag based on which field is populated."""
    mode = data.get("mode")
    if mode in ("phase", "dag"):
        return mode
    if data.get("phases"):
        return "phase"
    if data.get("agents"):
        return "dag"
    return "phase"


# === Wave computation (topological levels) ===
def compute_waves(agents: list[dict]) -> dict[str, int]:
    """Topological wave assignment. Wave 0 = no depends_on."""
    waves: dict[str, int] = {}
    for a in agents:
        if not a.get("depends_on"):
            waves[a["id"]] = 0
    changed = True
    while changed:
        changed = False
        for a in agents:
            if a["id"] in waves:
                continue
            deps = a.get("depends_on", []) or []
            dep_waves = [waves.get(d) for d in deps]
            if all(w is not None for w in dep_waves):
                waves[a["id"]] = max(dep_waves) + 1
                changed = True
    for a in agents:
        if a["id"] not in waves:
            waves[a["id"]] = 0
    return waves


# === drive-viz invocation (per skill protocol) ===
DRIVE_VIZ_SKILL = Path(__file__).parent.parent.parent / "drive-viz"


# Component CSS lives in assets/component.css (extracted from
# 00-docs/prototypes/03-phase.html — the canonical plan-review visual language).
# drive-viz tokens (`:root` vars) come separately from `tokens_css()` below;
# this file holds component classes only.
_COMPONENT_CSS_PATH = Path(__file__).parent.parent / "assets" / "component.css"


def component_css() -> str:
    """Return the component CSS for plan-review rendering (no tokens)."""
    if not _COMPONENT_CSS_PATH.is_file():
        raise FileNotFoundError(
            f"Component CSS missing: {_COMPONENT_CSS_PATH}. "
            "Expected assets/component.css alongside the script."
        )
    return _COMPONENT_CSS_PATH.read_text(encoding="utf-8")


def _phase_field(p: dict) -> str:
    """Get phase stage/name field (workdir-demo uses 'stage', drive-core uses 'name' too)."""
    return p.get("name") or p.get("stage") or ""


def render_phase_mode(data: dict, selected: str) -> str:
    """Render phase-mode HTML (linear chain, possibly with back-jumps)."""
    phases = data.get("phases") or []
    by_stage = {_phase_field(p): p for p in phases}

    # Auto-select gate if none specified
    if not selected:
        for p in phases:
            if p.get("gate"):
                selected = _phase_field(p)
                break
        if not selected and phases:
            selected = _phase_field(phases[0])

    # Layout: vertical chain.
    n = len(phases)
    has_any_gate = any(p.get("gate") for p in phases)
    node_h = 50 if has_any_gate else 40
    svg_h = n * 90 + 60
    nodes_svg = []
    edges_svg = []
    back_edges = []

    for i, phase in enumerate(phases):
        y = 40 + i * 90
        stage = _phase_field(phase)
        agent = phase.get("agent", "—")
        is_selected = (stage == selected)
        is_gate = phase.get("gate") is not None
        terminal = phase.get("terminal_stage", False)

        drive_builtins = {
            "drive:analyzer": "var(--c-analyze)",
            "drive:planner": "var(--c-plan)",
            "drive:executor": "var(--c-execute)",
            "drive:evaluator": "var(--c-evaluate)",
        }
        fill = drive_builtins.get(agent, "var(--c-user-fill)")
        stroke = (
            "var(--c-selected)" if is_selected else
            "var(--c-gate)" if is_gate else
            "var(--c-evaluate)" if terminal else
            "var(--c-user)"
        )
        stroke_w = 2.5 if (is_selected or terminal) else 2 if is_gate else 1.5
        dash = ' stroke-dasharray="6,3"' if is_gate else ""

        stage_label = f"{stage} 🚪" if is_gate else stage

        nodes_svg.append(f'''
<g class="node {'gate' if is_gate else ''} {'selected' if is_selected else ''} {'terminal' if terminal and not is_gate else ''}">
  <rect x="120" y="{y}" width="140" height="{node_h}" rx="6" fill="{fill if not is_gate else '#fef2f2'}" stroke="{stroke}" stroke-width="{stroke_w}"{dash}/>
  <text class="agent-name" x="190" y="{y+25}" text-anchor="middle">{stage_label}</text>
  <text class="agent-id" x="190" y="{y+38}" text-anchor="middle">{agent}</text>
  {f'<text x="190" y="{y+node_h-3}" text-anchor="middle" font-size="9" font-weight="800" fill="#ef4444" letter-spacing="0.1em">HUMAN GATE</text>' if is_gate else ""}
</g>''')

        if i < n - 1:
            edges_svg.append(f'<path class="edge" d="M 190 {y+node_h} L 190 {y+90}" marker-end="url(#arr)"/>')

    # Back-jump edges
    allowed_back_jumps = data.get("allowed_back_jumps") or {}
    if allowed_back_jumps:
        for from_stage, targets in allowed_back_jumps.items():
            for target in targets:
                from_idx = next((i for i, p in enumerate(phases) if _phase_field(p) == from_stage), None)
                target_idx = next((i for i, p in enumerate(phases) if _phase_field(p) == target), None)
                if from_idx is None or target_idx is None or from_idx <= target_idx:
                    continue
                from_y = 40 + from_idx * 90 + node_h
                target_y = 40 + target_idx * 90
                back_edges.append(f'<path class="edge-back" d="M 260 {from_y} C 320 {from_y}, 320 {target_y}, 260 {target_y}" marker-end="url(#arr-back)"/>')

    side_panel = render_phase_side_panel(phases, by_stage, selected)

    progress_pills = []
    for i, phase in enumerate(phases):
        is_sel = _phase_field(phase) == selected
        cls = "stage-pill selected" if is_sel else "stage-pill"
        progress_pills.append(f'<span class="{cls}">{_phase_field(phase)}{" 🚪" if phase.get("gate") else ""}</span>')
        if i < len(phases) - 1:
            progress_pills.append('<span class="arrow">→</span>')
    if allowed_back_jumps:
        progress_pills.append('<span class="back-arrow">↺</span>')

    sub = (
        f'<span class="mode-tag phase">phase</span> '
        f"{len(phases)} phases · "
        + (f'{len(allowed_back_jumps)} back-jump · ' if allowed_back_jumps else '')
        + 'ready_for: human'
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>workflow-builder render · plan-review</title>
<style>{tokens_css("light")}{component_css()}</style>
</head>
<body>
<div class="editor">
  <div class="toolbar">
    <div class="title-block">
      <h1>workflow.yaml · plan-review view</h1>
      <div class="sub">{sub}</div>
    </div>
    <div class="actions">
      <button class="btn primary">Approve Plan →</button>
      <button class="btn danger">Request Revision</button>
      <button class="btn">View YAML</button>
    </div>
  </div>
  <div class="main">
    <div class="canvas-wrap">
      <svg viewBox="0 0 380 {svg_h}" width="100%">
        <defs>
          <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 Z" class="arrow-head"/>
          </marker>
          <marker id="arr-back" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 Z" class="arrow-back-head"/>
          </marker>
        </defs>
        {''.join(nodes_svg)}
        {''.join(edges_svg)}
        {''.join(back_edges)}
      </svg>
    </div>
    <aside class="side">
      {side_panel}
    </aside>
  </div>
  <div class="footer">
    <div class="progress-line">
      <span style="color: var(--muted);">进度</span>
      {''.join(progress_pills)}
    </div>
    <span style="font-family: var(--mono); font-size: 11px;">{len(phases)} phases · ready_for: human</span>
  </div>
</div>
</body></html>"""


def render_phase_side_panel(phases: list, by_stage: dict, selected: str) -> str:
    """Render side panel showing details of the selected phase."""
    if selected not in by_stage:
        return ""
    phase = by_stage[selected]
    is_gate = phase.get("gate") is not None
    terminal = phase.get("terminal_stage", False)
    agent = phase.get("agent", "—")

    badges = []
    if is_gate:
        badges.append('<span class="gate-badge">GATE</span>')
    if terminal:
        badges.append('<span class="terminal-badge">TERMINAL</span>')

    drive_builtins = {
        "drive:analyzer": "var(--c-analyze)",
        "drive:planner": "var(--c-plan)",
        "drive:executor": "var(--c-execute)",
        "drive:evaluator": "var(--c-evaluate)",
    }
    dot_color = drive_builtins.get(agent, "var(--c-user)")

    rows = [
        f'<div class="kv"><span class="k">stage</span><span class="v">{selected}</span></div>',
        f'<div class="kv"><span class="k">agent</span><span class="v">{agent}</span></div>',
    ]
    deps = phase.get("depends_on") or []
    if deps:
        rows.append(f'<div class="kv"><span class="k">depends_on</span><span class="v">{", ".join(deps)}</span></div>')

    gate_section = ""
    if is_gate:
        gate = phase["gate"]
        opts = ", ".join(gate.get("options", []) or []) or "—"
        gate_section = f'''
<h3>Gate 配置</h3>
<div class="gate-config">
  <strong>human_review</strong>
  type: <code>{gate.get("type", "—")}</code><br>
  enforced_by: <code>{gate.get("enforced_by", "—")}</code><br>
  options: <code>{opts}</code>
</div>'''

    return f"""
<h3>已选节点</h3>
<div class="selected-card">
  <div class="selected-name">
    <span class="dot" style="background: {dot_color};"></span>
    {selected}
    {''.join(badges)}
  </div>
  <div class="selected-sub" style="margin-bottom: 10px;">{agent} · phase mode</div>
  {''.join(rows)}
</div>
{gate_section}
"""


def render_dag_mode(data: dict, selected: str) -> str:
    """Render DAG-mode HTML (workflow-builder preview style)."""
    agents = data.get("agents") or []
    if not agents:
        return "<html><body>No DAG agents defined.</body></html>"

    # Normalize: each agent is dict with id, agent, depends_on, terminal, gate
    normalized = []
    for a in agents:
        normalized.append({
            "id": a.get("id") or a.get("agent") or "?",
            "agent": a.get("agent", ""),
            "depends_on": a.get("depends_on", []) or [],
            "terminal": a.get("terminal", False),
            "gate": "gate" in (a.get("agent", "") + a.get("id", "")),
        })

    waves = compute_waves(normalized)
    by_wave: dict[int, list[dict]] = {}
    for a in normalized:
        by_wave.setdefault(waves[a["id"]], []).append(a)

    n_waves = max(waves.values()) + 1 if waves else 0

    # Layout
    node_w, node_h = 140, 50
    h_gap, v_gap = 30, 60
    max_per_wave = max((len(v) for v in by_wave.values()), default=1)
    svg_w = max_per_wave * (node_w + h_gap) + h_gap
    svg_h = n_waves * (node_h + v_gap) + v_gap

    positions: dict[str, tuple[int, int]] = {}
    for wave_idx in sorted(by_wave.keys()):
        wave_agents = by_wave[wave_idx]
        n = len(wave_agents)
        total_w = n * node_w + (n - 1) * h_gap
        start_x = (svg_w - total_w) // 2
        for i, a in enumerate(wave_agents):
            x = start_x + i * (node_w + h_gap)
            y = v_gap + wave_idx * (node_h + v_gap)
            positions[a["id"]] = (x, y)

    nodes_svg = []
    edges_svg = []
    for a in normalized:
        x, y = positions[a["id"]]
        is_selected = (a["id"] == selected)
        is_gate = a["gate"]
        terminal = a["terminal"]

        drive_builtins = {
            "drive:analyzer": ("#dbeafe", "var(--c-analyze)"),
            "drive:planner": ("#f3e8ff", "var(--c-plan)"),
            "drive:executor": ("#d1fae5", "var(--c-execute)"),
            "drive:evaluator": ("#ffedd5", "var(--c-evaluate)"),
            "drive:gate-human": ("#fef2f2", "var(--c-gate)"),
            "drive:code-reviewer": ("#dbeafe", "var(--c-analyze)"),
        }
        is_builtin = a["agent"] in drive_builtins
        fill, stroke = drive_builtins.get(a["agent"], ("var(--c-user-fill)", "var(--c-user)"))
        stroke_w = 2.5 if is_selected else 2 if is_gate or terminal else 1.5
        cls_parts = ["node"]
        if not is_builtin:
            cls_parts.append("user")
        if is_gate:
            cls_parts.append("gate")
        if terminal:
            cls_parts.append("terminal")
        if is_selected:
            cls_parts.append("selected")
        cls = " ".join(cls_parts)
        dash = ' stroke-dasharray="6,3"' if is_gate else ""

        label = a["id"]
        if is_gate:
            label = f"{a['id']} 🚪"
        if terminal:
            label = f"{a['id']} ★"

        nodes_svg.append(f'''
<g class="{cls}">
  <rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}"{dash}/>
  <text class="agent-name" x="{x + node_w//2}" y="{y + 22}" text-anchor="middle">{label}</text>
  <text class="agent-id" x="{x + node_w//2}" y="{y + 36}" text-anchor="middle">{a["agent"]}</text>
  {f'<text x="{x + node_w//2}" y="{y + node_h - 4}" text-anchor="middle" font-size="9" font-weight="800" fill="#ef4444" letter-spacing="0.1em">HUMAN GATE</text>' if is_gate else ""}
</g>''')

    for a in normalized:
        for dep in a["depends_on"]:
            if dep not in positions:
                continue
            sx, sy = positions[dep]
            tx, ty = positions[a["id"]]
            edges_svg.append(
                f'<path class="edge" d="M {sx + node_w//2} {sy + node_h} '
                f'C {sx + node_w//2} {sy + node_h + v_gap//2}, '
                f'{tx + node_w//2} {ty - v_gap//2}, '
                f'{tx + node_w//2} {ty}" marker-end="url(#arr)"/>'
            )

    wave_bands = []
    for wave_idx in sorted(by_wave.keys()):
        wave_agents = by_wave[wave_idx]
        if not wave_agents:
            continue
        xs = [positions[a["id"]][0] for a in wave_agents]
        xe = [positions[a["id"]][0] + node_w for a in wave_agents]
        band_x = min(xs) - 15
        band_w = max(xe) - band_x + 15
        band_y = v_gap + wave_idx * (node_h + v_gap) - 15
        band_h = node_h + 30
        wave_bands.append(f'<rect class="wave-band" x="{band_x}" y="{band_y}" width="{band_w}" height="{band_h}" rx="6"/>')
        wave_bands.append(f'<text class="wave-label" x="{band_x + 10}" y="{band_y + 12}">wave {wave_idx + 1} · {len(wave_agents)} {"parallel" if len(wave_agents) > 1 else "agent"}</text>')

    side_panel = render_dag_side_panel(normalized, selected)
    terminal_count = sum(1 for a in normalized if a["terminal"])

    orch = data.get("orchestration") or {}
    concurrent = orch.get("max_concurrent_agents", "?")
    sub = (
        f'<span class="mode-tag">dag</span> '
        f"{len(normalized)} agents · {n_waves} waves · 1 gate · {terminal_count} terminal"
        f"· {concurrent} concurrent"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>workflow-builder render · plan-review (dag)</title>
<style>{tokens_css("light")}{component_css()}</style>
</head>
<body>
<div class="editor">
  <div class="toolbar">
    <div class="title-block">
      <h1>workflow.yaml · plan-review view</h1>
      <div class="sub">{sub}</div>
    </div>
    <div class="actions">
      <button class="btn primary">Approve Plan →</button>
      <button class="btn danger">Request Revision</button>
      <button class="btn">View YAML</button>
    </div>
  </div>
  <div class="main">
    <div class="canvas-wrap">
      <svg viewBox="0 0 {svg_w} {svg_h}" width="100%">
        <defs>
          <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 Z" class="arrow-head"/>
          </marker>
        </defs>
        {''.join(wave_bands)}
        {''.join(edges_svg)}
        {''.join(nodes_svg)}
      </svg>
    </div>
    <aside class="side">
      {side_panel}
    </aside>
  </div>
  <div class="footer">
    <div class="progress-line">
      <span style="color: var(--muted);">进度</span>
      {"".join(f'<span class="stage-pill">{a["id"]}</span>' + ("" if a == normalized[-1] else ' <span class="arrow">→</span>') for a in normalized)}
    </div>
    <span style="font-family: var(--mono); font-size: 11px;">{len(normalized)} agents · {n_waves} waves</span>
  </div>
</div>
</body></html>"""


def render_dag_side_panel(agents: list[dict], selected: str) -> str:
    """Render DAG-mode side panel for the selected agent."""
    by_id = {a["id"]: a for a in agents}
    if not selected or selected not in by_id:
        return ""
    a = by_id[selected]
    is_gate = a["gate"]
    is_user = a["agent"] not in {"drive:analyzer", "drive:planner", "drive:executor", "drive:evaluator", "drive:gate-human", "drive:code-reviewer"}

    badges = []
    if is_gate:
        badges.append('<span class="gate-badge">GATE</span>')
    if a["terminal"]:
        badges.append('<span class="terminal-badge">TERMINAL</span>')
    if is_user:
        badges.append('<span class="user-badge">USER</span>')

    drive_builtins = {
        "drive:analyzer": "var(--c-analyze)",
        "drive:planner": "var(--c-plan)",
        "drive:executor": "var(--c-execute)",
        "drive:evaluator": "var(--c-evaluate)",
    }
    dot_color = drive_builtins.get(a["agent"], "var(--c-user)")

    rows = [f'<div class="kv"><span class="k">agent</span><span class="v">{a["agent"]}</span></div>']
    if a["depends_on"]:
        rows.append(f'<div class="kv"><span class="k">depends_on</span><span class="v">{", ".join(a["depends_on"])}</span></div>')
    if is_gate:
        rows.append('<div class="kv"><span class="k">type</span><span class="v">human_review</span></div>')
        rows.append('<div class="kv"><span class="k">options</span><span class="v">approve, revise</span></div>')

    return f"""
<h3>已选节点</h3>
<div class="selected-card">
  <div class="selected-name">
    <span class="dot" style="background: {dot_color};"></span>
    {a['id']}
    {''.join(badges)}
  </div>
  <div class="selected-sub" style="margin-bottom: 10px;">{a['agent']} · dag mode</div>
  {''.join(rows)}
</div>
"""


# === Main ===

def render_html(work_dir: Path, selected: str = "") -> str:
    """Render workflow.yaml as plan-review HTML."""
    try:
        data = load_yaml(work_dir)
    except FileNotFoundError as e:
        return f"<!DOCTYPE html><body><h1>render_dag error</h1><pre>{e}</pre></body></html>"

    mode = detect_mode(data)

    # Default selection: first gate, else first node
    if not selected:
        if mode == "phase":
            for p in (data.get("phases") or []):
                if p.get("gate"):
                    selected = _phase_field(p)
                    break
            if not selected and data.get("phases"):
                selected = _phase_field(data["phases"][0])
        else:
            agents = data.get("agents") or []
            for a in agents:
                if "gate" in a.get("id", ""):
                    selected = a["id"]
                    break
            if not selected and agents:
                selected = agents[0].get("id", "")

    if mode == "phase":
        return render_phase_mode(data, selected)
    return render_dag_mode(data, selected)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work-dir", required=True, type=Path)
    p.add_argument("--selected", default="")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    html = render_html(args.work_dir, args.selected)
    if args.out:
        args.out.write_text(html)
        print(f"wrote {args.out} ({len(html)} bytes)")
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()