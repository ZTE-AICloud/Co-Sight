#!/bin/bash
# perf-report.sh — P0 基线/回归测量（goal-mode-pipeline-acceleration 方案 §四）
#
# 用法: bash scripts/perf-report.sh <name> [--out <md-path>]
# 输入: .agent-genesis/work/{name}/orchestrator-state.yaml  (finish_step 记录 started_at/finished_at)
#       .agent-genesis/work/{name}/gate-results/*.json       (gate verdict, 部分含 timestamp)
#       .agent-genesis/work/{name}/progress.json            (executor 逐文件 done/failed)
# 输出: Markdown 报告到 stdout（或 --out 落盘）
#
# 两个口径（方案 §四.3）:
#   LLM 口径  = 各 step 的 started_at→finished_at 之和（纯执行段，不含步间等待）
#   墙钟口径  = 首 step started_at → 末 step finished_at（含人审等待 = 步间 gap）
# 已知限制: progress.json 只记 current.started_at，无逐文件 finished_at，
#           逐文件耗时不可精确还原，只报 done/failed 计数与 executor 总跨度。
set -uo pipefail

NAME="${1:-}"
OUT=""
[[ "${2:-}" == "--out" && -n "${3:-}" ]] && OUT="$3"

if [[ -z "$NAME" ]]; then
  echo "用法: bash scripts/perf-report.sh <name> [--out <md-path>]" >&2
  exit 2
fi

WORK_DIR=".agent-genesis/work/$NAME"
STATE="$WORK_DIR/orchestrator-state.yaml"
[[ -f "$STATE" ]] || { echo "MISSING: $STATE" >&2; exit 1; }

python3 - "$NAME" "$WORK_DIR" "$OUT" << 'PYEOF'
import json, sys, os
from datetime import datetime

name, work_dir, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

import yaml
with open(os.path.join(work_dir, "orchestrator-state.yaml")) as f:
    state = yaml.safe_load(f) or {}
steps = state.get("steps", [])

def parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None

def fmt_dur(seconds):
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"

rows = []
llm_total = 0.0
gaps_total = 0.0
prev_fin = None
for st in steps:
    sta, fin = parse_ts(st.get("started_at")), parse_ts(st.get("finished_at"))
    dur = (fin - sta).total_seconds() if sta and fin else None
    gap = (sta - prev_fin).total_seconds() if sta and prev_fin else 0.0
    if prev_fin:
        gaps_total += gap
    if dur is not None:
        llm_total += dur
    prev_fin = fin or prev_fin
    rows.append({
        "step": st.get("step_id", "?"),
        "started": st.get("started_at", "—")[11:19],
        "dur": dur,
        "gap_before": gap if prev_fin and sta else None,
        "retry": st.get("retry_count", 0),
        "verdict": st.get("gate_verdict", "—"),
    })

wall_total = None
if rows:
    first_sta = parse_ts(steps[0].get("started_at"))
    last_fin = None
    for st in reversed(steps):
        last_fin = parse_ts(st.get("finished_at"))
        if last_fin:
            break
    if first_sta and last_fin:
        wall_total = (last_fin - first_sta).total_seconds()

# gate-results 汇总
gate_rows = []
gdir = os.path.join(work_dir, "gate-results")
if os.path.isdir(gdir):
    for fn in sorted(os.listdir(gdir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(gdir, fn)) as f:
                g = json.load(f)
        except Exception:
            continue
        gate_rows.append((fn[:-5], g.get("gate_id", "—"), g.get("verdict", "—")))

# progress.json（executor）
prog = {}
pfile = os.path.join(work_dir, "progress.json")
if os.path.isfile(pfile):
    with open(pfile) as f:
        prog = json.load(f) or {}

lines = []
lines.append(f"# Pipeline 性能报告: {name}")
lines.append("")
lines.append("## 总览（两个口径）")
lines.append("")
lines.append("| 口径 | 时长 | 说明 |")
lines.append("|------|------|------|")
lines.append(f"| LLM 口径（各 step 执行段合计） | {fmt_dur(llm_total)} | started_at→finished_at 之和，主战场 P2/P4 |")
lines.append(f"| 步间等待合计（人审+编排 gap） | {fmt_dur(gaps_total)} | 上一 step finished_at → 下一 step started_at，主战场 P1/P3 |")
lines.append(f"| 墙钟口径（首 step→末 step） | {fmt_dur(wall_total)} | 含全部等待 |")
lines.append("")
lines.append("## 逐步骤耗时")
lines.append("")
lines.append("| Step | 开始(UTC) | 执行时长 | 步前等待 | retry | gate |")
lines.append("|------|-----------|---------|--------|------:|------|")
for r in rows:
    lines.append(f"| {r['step']} | {r['started']} | {fmt_dur(r['dur'])} | "
                 f"{fmt_dur(r['gap_before']) if r['gap_before'] is not None else '—'} | "
                 f"{r['retry']} | {r['verdict']} |")
lines.append("")
if gate_rows:
    lines.append("## Gate 结果汇总")
    lines.append("")
    lines.append("| 结果文件 | Gate | Verdict |")
    lines.append("|---------|------|---------|")
    for sid, gid, v in gate_rows:
        lines.append(f"| {sid} | {gid} | {v} |")
    lines.append("")
if prog:
    lines.append("## Executor 进度（progress.json）")
    lines.append("")
    lines.append(f"- done: {len(prog.get('done', []))} 个文件")
    lines.append(f"- failed: {len(prog.get('failed', []))} 个文件")
    lines.append(f"- executor 启动: {prog.get('started_at', '—')}")
    lines.append("")
    lines.append("> 限制: progress.json 无逐文件 finished_at，逐文件耗时不可精确还原。")
    lines.append("")

report = "\n".join(lines)
if out_path:
    with open(out_path, "w") as f:
        f.write(report + "\n")
    print(f"已写出: {out_path}")
else:
    print(report)
PYEOF
