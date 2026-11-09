#!/usr/bin/env bash
# scripts/dc001-channel.sh
# P3: DC-001 通道判定脚本（确定性，不允许 LLM 自由裁断）
# docs/plan/goal-mode-pipeline-acceleration.md §七
#
# 协议: stdout JSON {channel: "fast"|"full", checks: {<4 项逐项>}, reason}
# 四项全过 → fast；任一不过 → full

set -uo pipefail

WORK_DIR="${1:?work_dir required}"
# 支持两种传参:
#   传 .agent-genesis/work/<name> (新)  → 内层路径自动加 /agent-creation/
#   传 .agent-genesis/work/<name>/agent-creation (旧,直接传内层) → 不加
if [ -d "$WORK_DIR/agent-creation" ]; then
  AGENT_DIR="$WORK_DIR/agent-creation"
else
  AGENT_DIR="$WORK_DIR"
fi
NAME=$(basename "$(dirname "$AGENT_DIR")")
NAME=${NAME%agent-creation}
[ -z "$NAME" ] && NAME=$(basename "$AGENT_DIR")

OUT_DIR="output/agents/${NAME}/v1"

checks_pass=0
checks_total=4
reasons=()

# 1. G017 verdict = pass 且 concerns = []
# gate-results 在 work/<name>/gate-results/ (P0 既有布局)
WORK_ROOT="$(dirname "$AGENT_DIR")"
matching_review="$WORK_ROOT/gate-results/step-2-matching-review.json"
if [ -f "$matching_review" ]; then
  v=$(python3 -c "
import json
try:
    with open('$matching_review') as f: d=json.load(f)
    if d.get('verdict','').lower() == 'pass' and not d.get('concerns'):
        print('pass')
    else:
        print(f\"fail:{d.get('verdict','?')},concerns={len(d.get('concerns',[]))}\")
except Exception as e:
    print(f'fail:parse_error={e}')
")
  case "$v" in pass) checks_pass=$((checks_pass+1)) ;; *) reasons+=("g017:$v") ;; esac
else
  reasons+=("g017:missing_step-2-matching-review.json")
fi

# 2. build-plan: manual_verify invariants ≤ 2 条
build_plan="$AGENT_DIR/build-plan.md"
if [ -f "$build_plan" ]; then
  mv_count=$(grep -cE '^\s*-\s*\{\s*type:\s*manual_verify' "$build_plan" 2>/dev/null)
  mv_count=${mv_count:-0}
  if [ "$mv_count" -le 2 ] 2>/dev/null; then
    checks_pass=$((checks_pass+1))
  else
    reasons+=("manual_verify:${mv_count}_gt_2")
  fi
else
  reasons+=("manual_verify:missing_build-plan.md")
fi

# 3. build_type.type = single_agent（不允许 multi_agent 进 fast）
# 判定: build-plan 内 type: subagent 出现次数 ≥3 → multi_agent
if [ -f "$build_plan" ]; then
  sub_count=$(grep -cE '^\s*type:\s*subagent' "$build_plan" 2>/dev/null)
  sub_count=${sub_count:-0}
  if [ "$sub_count" -ge 3 ] 2>/dev/null; then
    reasons+=("build_type:multi_agent_subcount=${sub_count}")
  else
    checks_pass=$((checks_pass+1))
  fi
else
  reasons+=("build_type:missing_build-plan.md")
fi

# 4. human-review.md 风险小节: 无 critical 级
human_review="$AGENT_DIR/human-review.md"
if [ -f "$human_review" ]; then
  crit_count=$(grep -cE '^\s*-\s*\[(临界|critical)\]' "$human_review" 2>/dev/null)
  crit_count=${crit_count:-0}
  if [ "$crit_count" -eq 0 ] 2>/dev/null; then
    checks_pass=$((checks_pass+1))
  else
    reasons+=("risk_level:${crit_count}_critical")
  fi
else
  reasons+=("risk_level:missing_human-review.md")
fi

# 防退化兜底：环境变量 DC001_FORCE_FULL=1 → 一律 full
if [ "${DC001_FORCE_FULL:-0}" = "1" ]; then
  checks_pass=0
  reasons+=("forced:DC001_FORCE_FULL=1")
fi

# 决断
if [ "$checks_pass" -eq "$checks_total" ]; then
  channel="fast"
else
  channel="full"
fi

# 写 dc001-decisions.yaml 留痕
DEC_FILE="$AGENT_DIR/dc001-decisions.yaml"
python3 -c "
import json, yaml, datetime
data = {
  'decision_checkpoint': 'DC-001',
  'channel': '$channel',
  'checks_pass': $checks_pass,
  'checks_total': $checks_total,
  'reasons': [$(printf "'%s'," "${reasons[@]}" | sed 's/,$//')],
  'decided_at': datetime.datetime.now(datetime.UTC).isoformat().replace('+00:00','Z')
}
with open('$DEC_FILE','w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
"

# stdout JSON
python3 -c "
import json
out = {
  'channel': '$channel',
  'checks_pass': $checks_pass,
  'checks_total': $checks_total,
  'reasons': [$(printf "'%s'," "${reasons[@]}" | sed 's/,$//')]
}
print(json.dumps(out, ensure_ascii=False))
"

# 退出码: fast=0, full=1（main agent 据此决定面板密度）
[ "$channel" = "fast" ] && exit 0 || exit 1