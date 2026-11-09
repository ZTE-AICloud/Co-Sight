#!/usr/bin/env bash
# scripts/main-agent-helpers.sh
# Main agent 调用的 helper, 封装状态文件读写 + gate verdict 读取 + 重试决策
#
# 实现: 用 Python 读/写 YAML (避免依赖 yq)
# 协议: 每个函数 stdin/stdout JSON 友好, 但也支持直接 Bash 调用
# 用法: source scripts/main-agent-helpers.sh && finish_step "step-N-..." "$WORK_DIR" "$OUTPUT_DIR" "$outputs_json"

set -euo pipefail

# gates.yaml 定位（可被环境变量覆盖，测试用）；verdict 落盘契约见 00-conventions 状态机节
_HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATES_YAML="${GATES_YAML:-$_HELPER_DIR/../phase/gates/gates.yaml}"

# verdict 等待秒数（防呆等待，非 gate 执行超时）——读 gates.yaml defaults.verdict_wait_seconds，
# 缺失/非法回落 30。verdict 落盘责任在 SKILL.md 主循环（跑完 gate 即写
# gate-results/<step_id>.json 再调 finish_step）。
_verdict_wait_seconds() {
  local v
  v=$(_yaml_get "$GATES_YAML" "defaults.verdict_wait_seconds" 2>/dev/null || echo "")
  [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 30
}

# 读 gates.yaml triggers[step_id].on_failure.<path>（路径如 retry.max / back_off_to /
# escalate.after_exhausted）；NOT_FOUND 原样返回，由调用方回落
_on_failure_field() {
  local step_id="$1"
  local field_path="$2"
  python3 -c "
import sys, yaml
try:
    with open('$GATES_YAML') as f:
        d = yaml.safe_load(f) or {}
    t = (d.get('triggers') or {}).get('$step_id') or {}
    of = t.get('on_failure') or {}
    cur = of
    ok = True
    for k in '$field_path'.split('.'):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            ok = False
            break
    if not ok:
        print('NOT_FOUND')
    elif cur is None:
        print('null')
    else:
        print(cur)
except Exception:
    print('NOT_FOUND')
" 2>/dev/null
}

# Python helper for YAML read/write
_yaml_get() {
  local file="$1"
  local expr="$2"
  python3 -c "
import sys, yaml
try:
    with open('$file') as f:
        d = yaml.safe_load(f) or {}
    # Simple expression: 'field' or '.field.subfield'
    keys = '$expr'.lstrip('.').split('.')
    val = d
    for k in keys:
        if k == '':
            continue
        if isinstance(val, list):
            try:
                val = val[int(k)]
            except (ValueError, IndexError):
                print('NOT_FOUND')
                sys.exit(0)
        elif isinstance(val, dict):
            val = val.get(k, 'NOT_FOUND')
        else:
            print('NOT_FOUND')
            sys.exit(0)
    if val is None:
        print('null')
    elif isinstance(val, (dict, list)):
        print(yaml.dump(val, default_flow_style=False).rstrip())
    else:
        print(val)
except FileNotFoundError:
    print('NOT_FOUND')
" 2>/dev/null
}

_yaml_set() {
  local file="$1"
  local yq_expr="$2"
  python3 -c "
import sys, yaml, re
# Parse simple yq-style expression
# Examples:
#   .current_step = \"val\"
#   .total_retry_count = .total_retry_count + 1
#   (.steps[] | select(.step_id == \"x\") | .retry_count) += 1
#   .steps += [...]
expr = '''$yq_expr'''
with open('$file') as f:
    data = yaml.safe_load(f) or {}

# Simple parser for our specific patterns
if '| select(.step_id' in expr:
    # Update specific step's field
    m = re.search(r'\.steps\[\]\s*\|\s*select\(\.step_id\s*==\s*\"([^\"]+)\"\)\s*\|\s*\.(\w+)\)\s*\+=\s*(\d+)', expr)
    if m:
        step_id, field, delta = m.group(1), m.group(2), int(m.group(3))
        for step in data.get('steps', []):
            if step.get('step_id') == step_id:
                step[field] = step.get(field, 0) + delta
                break
elif '+=' in expr and '.steps' in expr:
    # Append to steps array
    m = re.search(r'\.steps\s*\+=\s*(.+)', expr, re.DOTALL)
    if m:
        new_step = yaml.safe_load(m.group(1).strip())
        if 'steps' not in data:
            data['steps'] = []
        data['steps'].append(new_step)
elif '=' in expr:
    # Set field
    m = re.match(r'\.(\w+(?:\.\w+)*)\s*=\s*(.+)', expr.strip(), re.DOTALL)
    if m:
        field, val = m.group(1), m.group(2).strip()
        # Handle quoted strings
        if val.startswith('\"') and val.endswith('\"'):
            val = val[1:-1]
        else:
            # Try parsing as YAML
            try:
                val = yaml.safe_load(val)
            except:
                pass
        keys = field.split('.')
        target = data
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = val

with open('$file', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
" 2>&1
}

# ═══════════════════════════════════════════════════════
# 1. finish_step - 写 orchestrator-state.yaml + 等待 gate verdict
# ═══════════════════════════════════════════════════════
finish_step() {
  local step_id="$1"
  local work_dir="$2"
  local output_dir="${3:-}"
  local outputs_json="${4:-[]}"
  local retry_count="${5:-0}"
  local started_at="${6:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
  local finished_at
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  local state_file="$work_dir/orchestrator-state.yaml"
  local params_json
  params_json=$(python3 -c "
import json
print(json.dumps({'WORK_DIR': '$work_dir', 'OUTPUT_DIR': '$output_dir'}))
")

  # 追加 step 到 state file
  python3 <<PYEOF
import yaml
with open("$state_file") as f:
    data = yaml.safe_load(f) or {}
if "steps" not in data:
    data["steps"] = []
import json
new_step = {
    "step_id": "$step_id",
    "status": "DONE",
    "started_at": "$started_at",
    "finished_at": "$finished_at",
    "params": json.loads('''$params_json'''),
    "outputs": json.loads('''$outputs_json'''),
    "retry_count": int("$retry_count"),
    "gate_verdict": "PENDING"
}
data["steps"].append(new_step)
data["current_step"] = "$step_id"
data["last_update"] = "$finished_at"
with open("$state_file", "w") as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
PYEOF

  # 防呆等待 verdict 落盘（落盘责任在 SKILL.md 主循环：跑完 gate 即写
  # gate-results/<step_id>.json 再调 finish_step；此处非 gate 执行超时）
  local result_path="$work_dir/gate-results/$step_id.json"
  local wait_secs
  wait_secs=$(_verdict_wait_seconds)
  for i in $(seq 1 "$wait_secs"); do
    if [[ -f "$result_path" ]]; then
      return 0
    fi
    sleep 1
  done

  echo "WARN: gate-results/$step_id.json ${wait_secs}s 内未落盘——主循环须先跑 gate 并写 verdict 再调 finish_step" >&2
  return 1
}

# ═══════════════════════════════════════════════════════
# 2. read_gate_verdict - 读 gate verdict
# ═══════════════════════════════════════════════════════
read_gate_verdict() {
  # 读 step verdict。文件名分工: gate-results/<step_id>.json = step verdict
  # （step-4 起由 executor 写）; <step_id>.g024.json = main agent G024 兜底结果, 本函数不读
  local step_id="$1"
  local work_dir="$2"
  local result_path="$work_dir/gate-results/$step_id.json"

  if [[ ! -f "$result_path" ]]; then
    echo "PENDING"
    return
  fi

  python3 -c "
import yaml
with open('$result_path') as f:
    d = yaml.safe_load(f) or {}
print(d.get('verdict', 'UNKNOWN'))
" 2>/dev/null
}

# ═══════════════════════════════════════════════════════
# 3. read_gate_failures - 读 gate 失败详情
# ═══════════════════════════════════════════════════════
read_gate_failures() {
  local step_id="$1"
  local work_dir="$2"
  local result_path="$work_dir/gate-results/$step_id.json"

  if [[ ! -f "$result_path" ]]; then
    echo "[]"
    return
  fi

  python3 -c "
import yaml, json
with open('$result_path') as f:
    d = yaml.safe_load(f) or {}
print(json.dumps(d.get('failures', [])))
" 2>/dev/null
}

# ═══════════════════════════════════════════════════════
# 4. decide_action - 根据 verdict + retry_count 决定下一步
# ═══════════════════════════════════════════════════════
decide_action() {
  # 调用契约: 仅 gate verdict=FAIL 后调用（step_gate_summary 的 FAIL 分支/dry-run 同）;
  # PASS/CONCERNS 走 step_gate_summary, 本函数只看 retry_count 不读 verdict
  local step_id="$1"
  local work_dir="$2"
  local max_retry="${3:-}"
  local back_off_to="${4:-}"

  local state_file="$work_dir/orchestrator-state.yaml"

  # 未显式传参时从 gates.yaml triggers[step_id].on_failure 读取（注册表为唯一权威，
  # retry.max:0 的步不再被默认 3 错误重试）
  if [[ -z "$max_retry" ]]; then
    max_retry=$(_on_failure_field "$step_id" "retry.max")
    [[ "$max_retry" =~ ^[0-9]+$ ]] || max_retry=3
  fi
  if [[ -z "$back_off_to" ]]; then
    # 注册表中 back_off_to 嵌套于 retry 之下（gates.yaml 既有形态），兼容顶层写法
    back_off_to=$(_on_failure_field "$step_id" "retry.back_off_to")
    if [[ "$back_off_to" == "NOT_FOUND" || "$back_off_to" == "null" ]]; then
      back_off_to=$(_on_failure_field "$step_id" "back_off_to")
    fi
    if [[ "$back_off_to" == "NOT_FOUND" || "$back_off_to" == "null" ]]; then
      back_off_to=""
    fi
  fi
  local after_exhausted
  after_exhausted=$(_on_failure_field "$step_id" "escalate.after_exhausted")

  # 读 retry_count
  local retry_count
  retry_count=$(python3 -c "
import yaml
try:
    with open('$state_file') as f:
        d = yaml.safe_load(f) or {}
    for s in d.get('steps', []):
        if s.get('step_id') == '$step_id':
            print(s.get('retry_count', 0))
            break
    else:
        print(0)
except: print(0)
" 2>/dev/null)

  # 读 total_retry_count (circuit breaker)
  local total_retry
  total_retry=$(python3 -c "
import yaml
try:
    with open('$state_file') as f:
        d = yaml.safe_load(f) or {}
    print(d.get('total_retry_count', 0))
except: print(0)
" 2>/dev/null)

  local budget
  budget=$(python3 -c "
import yaml
try:
    with open('$state_file') as f:
        d = yaml.safe_load(f) or {}
    print(d.get('pipeline_retry_budget', 5))
except: print(5)
" 2>/dev/null)

  # Circuit breaker check
  if [[ $total_retry -ge $budget ]]; then
    echo "ESCALATE_GLOBAL"
    return
  fi

  # 单 step 重试预算
  if [[ $retry_count -lt $max_retry ]]; then
    echo "RETRY"
    return
  fi

  # 超限: back_off_to 存在且未声明 escalate.after_exhausted:true 才回退，
  # 否则升级（after_exhausted 落地——per-step 升级阈值不再被 BACK_OFF 吞掉）
  if [[ -n "$back_off_to" && "$after_exhausted" != "True" ]]; then
    echo "BACK_OFF:$back_off_to"
  else
    echo "ESCALATE_STEP"
  fi
}

# ═══════════════════════════════════════════════════════
# 5. increment_retry - retry_count + total_retry_count +1
# ═══════════════════════════════════════════════════════
increment_retry() {
  local step_id="$1"
  local work_dir="$2"
  local state_file="$work_dir/orchestrator-state.yaml"

  python3 <<PYEOF
import yaml
with open("$state_file") as f:
    data = yaml.safe_load(f) or {}

found = False
for step in data.get("steps", []):
    if step.get("step_id") == "$step_id":
        step["retry_count"] = step.get("retry_count", 0) + 1
        found = True
        break

if not found:
    # Step not in state yet, add minimal entry
    if "steps" not in data:
        data["steps"] = []
    data["steps"].append({"step_id": "$step_id", "retry_count": 1})

data["total_retry_count"] = data.get("total_retry_count", 0) + 1

with open("$state_file", "w") as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
PYEOF
}

# ═══════════════════════════════════════════════════════
# 6. write_gate_block - 失败升级时写 gate-block.md
# ═══════════════════════════════════════════════════════
write_gate_block() {
  local step_id="$1"
  local work_dir="$2"
  local verdict="$3"
  local failures_json="$4"
  local block_path="$work_dir/gate-block.md"
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # 读 retry history
  local retry_count
  retry_count=$(python3 -c "
import yaml
try:
    with open('$work_dir/orchestrator-state.yaml') as f:
        d = yaml.safe_load(f) or {}
    for s in d.get('steps', []):
        if s.get('step_id') == '$step_id':
            print(s.get('retry_count', 0))
            break
    else:
        print(0)
except: print(0)
" 2>/dev/null)

  cat > "$block_path" <<EOF
# Pipeline Blocked

**Step**: $step_id
**Time**: $now
**Verdict**: $verdict
**Retry Count**: $retry_count

## 失败详情

$(python3 -c "
import json
try:
    failures = json.loads('''$failures_json''')
    for f in failures:
        print(f\"| {f.get('gate', '?')} | {f.get('type', '?')} | {f.get('detail', '?')} |\")
except:
    print('| ? | ? | (parse error) |')
")

## 下一步选项

- [Continue Retry] 重新跑 $step_id
- [Skip Step] 跳过 $step_id, 标记为 skipped
- [Abort Pipeline] 终止整个 pipeline
EOF

  echo "WARN: pipeline blocked at $step_id, 报告: $block_path" >&2
}

# ═══════════════════════════════════════════════════════
# 7. mark_pipeline_status - 更新 pipeline_status
# ═══════════════════════════════════════════════════════
mark_pipeline_status() {
  local work_dir="$1"
  local status="$2"  # IN_PROGRESS | COMPLETED | BLOCKED | FAILED
  local state_file="$work_dir/orchestrator-state.yaml"

  python3 -c "
import yaml
with open('$state_file') as f:
    d = yaml.safe_load(f) or {}
d['pipeline_status'] = '$status'
d['last_update'] = '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
with open('$state_file', 'w') as f:
    yaml.dump(d, f, default_flow_style=False, sort_keys=False)
"
}

# ═══════════════════════════════════════════════════════
# 8. init_state - 初始化 orchestrator-state.yaml
# ═══════════════════════════════════════════════════════
init_state() {
  local work_dir="$1"
  local pipeline_name="${2:-agent-creation}"
  local retry_budget="${3:-5}"
  local state_file="$work_dir/orchestrator-state.yaml"
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  mkdir -p "$work_dir/gate-results"

  python3 <<PYEOF
import yaml
data = {
    "pipeline": "$pipeline_name",
    "pipeline_status": "IN_PROGRESS",
    "current_step": None,
    "last_update": "$now",
    "pipeline_retry_budget": int("$retry_budget"),
    "total_retry_count": 0,
    "steps": []
}
with open("$state_file", "w") as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
PYEOF

  echo "✅ state file initialized: $state_file"
}

# ═══════════════════════════════════════════════════════
# 9. record_failure - 记录 step 失败到 state
# ═══════════════════════════════════════════════════════
record_failure() {
  local step_id="$1"
  local work_dir="$2"
  local verdict="$3"
  local failures_json="$4"
  local state_file="$work_dir/orchestrator-state.yaml"

  python3 -c "
import yaml, json
with open('$state_file') as f:
    d = yaml.safe_load(f) or {}
for s in d.get('steps', []):
    if s.get('step_id') == '$step_id':
        s['gate_verdict'] = '$verdict'
        s['gate_failures'] = json.loads('''$failures_json''')
        break
with open('$state_file', 'w') as f:
    yaml.dump(d, f, default_flow_style=False, sort_keys=False)
"
}

# ═══════════════════════════════════════════════════════
# 10. step_gate_summary - 一站式: 写 state + 读 verdict + 决策
# ═══════════════════════════════════════════════════════
step_gate_summary() {
  local step_id="$1"
  local work_dir="$2"
  local max_retry="${3:-}"
  local back_off_to="${4:-}"
  local state_file="$work_dir/orchestrator-state.yaml"

  local verdict
  verdict=$(read_gate_verdict "$step_id" "$work_dir")

  case "$verdict" in
    PASS)
      echo "PASS"
      return
      ;;
    PENDING)
      echo "GATE_PENDING"
      return
      ;;
    CONCERNS)
      # CONCERNS 非阻断（与 G017/G027 语义对齐）: 记 concern 不走失败路径
      python3 -c "
import yaml, json
with open('$work_dir/gate-results/$step_id.json') as f:
    d = yaml.safe_load(f) or {}
with open('$state_file') as f:
    s = yaml.safe_load(f) or {}
for st in s.get('steps', []):
    if st.get('step_id') == '$step_id':
        st['gate_verdict'] = 'CONCERNS'
        st['gate_concerns'] = d.get('concerns', [])
        break
with open('$state_file', 'w') as f:
    yaml.dump(s, f, default_flow_style=False, sort_keys=False)
" 2>/dev/null || true
      echo "CONCERNS"
      return
      ;;
  esac

  # FAIL 或 INCOMPLETE
  local failures
  failures=$(read_gate_failures "$step_id" "$work_dir")
  record_failure "$step_id" "$work_dir" "$verdict" "$failures"

  local action
  action=$(decide_action "$step_id" "$work_dir" "$max_retry" "$back_off_to")

  case "$action" in
    RETRY)
      increment_retry "$step_id" "$work_dir"
      echo "RETRY"
      ;;
    ESCALATE_GLOBAL)
      write_gate_block "$step_id" "$work_dir" "$verdict" "$failures"
      mark_pipeline_status "$work_dir" "BLOCKED"
      echo "ESCALATE_GLOBAL"
      ;;
    ESCALATE_STEP)
      write_gate_block "$step_id" "$work_dir" "$verdict" "$failures"
      echo "ESCALATE_STEP"
      ;;
    BACK_OFF:*)
      echo "$action"
      ;;
  esac
}

# ═══════════════════════════════════════════════════════
# 11. step_done - P1 复合命令: validate + finish + verdict + decide 单调用
# ═══════════════════════════════════════════════════════
# 用法: step_done <step_id> <work_dir> [output_dir] [outputs_json] [max_retry] [back_off_to] [--validate] [--dry-run]
#
# 与分别调 finish + verdict + decide 的语义等价,但合并到一个 Bash 调用.
# --validate: 在 finish 前先检查 outputs_json 中每个文件路径是否落盘
# --dry-run: 只跑合并逻辑 + 读既有 gate-results,不重写 orchestrator-state、不等 30s
step_done() {
  local validate=0 dry_run=0
  local args=()
  for arg in "$@"; do
    case "$arg" in
      --validate) validate=1 ;;
      --dry-run) dry_run=1 ;;
      *) args+=("$arg") ;;
    esac
  done
  set -- "${args[@]}"

  local step_id="${1:?step_id required}"
  local work_dir="${2:?work_dir required}"
  local output_dir="${3:-}"
  local outputs_json="${4:-[]}"
  if [ $# -ge 4 ]; then shift 4; fi
  local max_retry="${1:-}"
  local back_off_to="${2:-}"

  # --dry-run: 读既有 verdict,跳过 finish (不动 orchestrator-state)
  if [[ $dry_run -eq 1 ]]; then
    local v
    v=$(read_gate_verdict "$step_id" "$work_dir")
    local a=""
    case "$v" in
      FAIL)     a=$(decide_action "$step_id" "$work_dir" "$max_retry" "$back_off_to" 2>/dev/null || echo "") ;;
      PASS)     a="PROCEED" ;;
      CONCERNS) a="PROCEED_WITH_CONCERNS" ;;
      *)        a="GATE_PENDING" ;;
    esac
    python3 -c "
import json, sys
out = {'step_id': '$step_id', 'dry_run': True,
       'gate_verdict': '$v', 'action': '$a'}
print(json.dumps(out, ensure_ascii=False))
"
    return 0
  fi

  # --validate: 检查 outputs_json 中每个文件存在
  local all_present=true
  if [[ $validate -eq 1 ]]; then
    local missing
    missing=$(python3 -c "
import json, sys, os
out = '$outputs_json'
try:
    arr = json.loads(out)
except: arr = []
missing = [p for p in arr if not os.path.exists(p)]
print(json.dumps(missing))
")
    if [[ "$missing" != "[]" ]]; then
      all_present=false
      echo "VALIDATE_FAIL: missing $missing" >&2
    fi
  fi

  # finish: 写 state + 等 gate verdict (既有函数,语义不变)
  finish_step "$step_id" "$work_dir" "$output_dir" "$outputs_json" 0 \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>/dev/null || true

  # verdict + decide（PENDING/UNKNOWN 禁止输出 PROCEED——verdict 未落盘不得视为通过）
  local verdict
  verdict=$(read_gate_verdict "$step_id" "$work_dir")
  local action
  case "$verdict" in
    FAIL)     action=$(decide_action "$step_id" "$work_dir" "$max_retry" "$back_off_to") ;;
    PASS)     action="PROCEED" ;;
    CONCERNS) action="PROCEED_WITH_CONCERNS" ;;
    *)        action="GATE_PENDING" ;;
  esac

  python3 -c "
import json
print(json.dumps({
  'step_id': '$step_id',
  'outputs_all_present': '$all_present' == 'true',
  'gate_verdict': '$verdict',
  'action': '$action'
}, ensure_ascii=False))
"
}

# ═══════════════════════════════════════════════════════
# 12. step_complete - 单入口: 执行 + 决策 + 落盘 (两线共用编排件)
# ═══════════════════════════════════════════════════════
# 用法: step_complete <step_id> <work_dir> [output_dir] [outputs_json] [max_retry] [back_off_to]
# 组合 finish_step(执行落盘) + verdict 消费 + 决策 + 失败处置落盘
# (concerns/failures 记录 / retry 计数 / gate-block / BLOCKED 状态 / PASS 回写)。
# 只做"执行+决策+落盘"组合, 不携带步骤语义; 决策策略唯一权威 = gates.yaml
# triggers[step_id].on_failure。输出单行 JSON {step_id, gate_verdict, action[, block_file]};
# action ∈ PROCEED|PROCEED_WITH_CONCERNS|GATE_PENDING|RETRY|BACK_OFF:<step_id>|
# ESCALATE_STEP|ESCALATE_GLOBAL; rc 0=正常(任意 action), 2=输入错误
step_complete() {
  local step_id="${1:-}" work_dir="${2:-}" output_dir="${3:-}"
  local outputs_json="${4:-[]}" max_retry="${5:-}" back_off_to="${6:-}"

  # 输入容错 (C8-1): fail-closed, 拒绝静默
  if [[ -z "$step_id" || -z "$work_dir" ]]; then
    echo "input_error: 用法 step_complete <step_id> <work_dir> [output_dir] [outputs_json] [max_retry] [back_off_to]" >&2
    return 2
  fi
  if [[ ! -f "$work_dir/orchestrator-state.yaml" ]]; then
    echo "input_error: $work_dir/orchestrator-state.yaml 不存在——先跑 init, 拒绝静默新建 state" >&2
    return 2
  fi
  if [[ -n "$outputs_json" ]] && ! OUTPUTS_JSON="$outputs_json" python3 -c "import json,os,sys; sys.exit(0 if isinstance(json.loads(os.environ['OUTPUTS_JSON']), list) else 1)" 2>/dev/null; then
    echo "input_error: outputs_json 不是 JSON 数组: $outputs_json" >&2
    return 2
  fi
  # 执行: 写 state + 防呆等 verdict (verdict 未落盘 → 下方决策输出 GATE_PENDING)
  finish_step "$step_id" "$work_dir" "$output_dir" "$outputs_json" 0 \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" || true

  # 决策 + 失败处置落盘 (concerns/retry 计数/gate-block/BLOCKED 均在 step_gate_summary 内)
  local action
  action=$(step_gate_summary "$step_id" "$work_dir" "$max_retry" "$back_off_to")
  local verdict
  verdict=$(read_gate_verdict "$step_id" "$work_dir")

  # 统一动作协议 (与 step_done JSON 同形)
  case "$action" in
    PASS) action="PROCEED" ;;
    CONCERNS) action="PROCEED_WITH_CONCERNS" ;;
  esac

  # 落盘补全: PASS 回写 gate_verdict (复用 record_failure; finish_step 预写 PENDING)
  [[ "$action" == "PROCEED" ]] && record_failure "$step_id" "$work_dir" "PASS" "[]" || true

  local block_file=""
  [[ "$action" == ESCALATE_* ]] && block_file="$work_dir/gate-block.md"

  STEP_ID="$step_id" VERDICT="$verdict" ACTION="$action" BLOCK_FILE="$block_file" \
    python3 -c "import json,os; out={'step_id':os.environ['STEP_ID'],'gate_verdict':os.environ['VERDICT'],'action':os.environ['ACTION']}; out.update(block_file=os.environ['BLOCK_FILE']) if os.environ.get('BLOCK_FILE') else None; print(json.dumps(out, ensure_ascii=False))"
}

# ═══════════════════════════════════════════════════════
# 如果直接运行 (不 source), 提供命令行入口
# ═══════════════════════════════════════════════════════
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  usage() {
    cat <<EOF
Usage: $0 <cmd> [args]

Commands:
  init <work_dir> [pipeline_name] [retry_budget]
    初始化 orchestrator-state.yaml

  finish <step_id> <work_dir> [output_dir] [outputs_json] [retry_count] [started_at]
    写 step 到 state, 等 gate verdict 出现

  verdict <step_id> <work_dir>
    读 gate verdict (PASS / FAIL / PENDING)

  decide <step_id> <work_dir> [max_retry] [back_off_to]
    决策 retry / back-off / escalate

  summary <step_id> <work_dir> [max_retry] [back_off_to]
    一站式: 写 state + 读 verdict + 决策 + 写 gate-block

  status <work_dir> <IN_PROGRESS|COMPLETED|BLOCKED|FAILED>
    更新 pipeline_status

  block <step_id> <work_dir> <verdict> <failures_json>
    写 gate-block.md

  step_complete <step_id> <work_dir> [output_dir] [outputs_json] [max_retry] [back_off_to]
    单入口: 执行+决策+落盘一体; 输出单行 JSON; rc 0=正常(任意 action), 2=输入错误

Examples:
  $0 init .agent-genesis/work/test/agent-creation
  $0 finish step-1-requirement-clarification .agent-genesis/work/test/agent-creation "" '[]' 0
  $0 verdict step-1-requirement-clarification .agent-genesis/work/test/agent-creation
  $0 summary step-4-implementation .agent-genesis/work/test/agent-creation 3 step-2-pattern-matching
EOF
  }
  cmd="${1:-help}"
  shift || true
  case "$cmd" in
    init)
      init_state "$@"
      ;;
    finish)
      finish_step "$@"
      ;;
    verdict)
      read_gate_verdict "$@"
      ;;
    decide)
      decide_action "$@"
      ;;
    summary)
      step_gate_summary "$@"
      ;;
    status)
      mark_pipeline_status "$@"
      ;;
    block)
      write_gate_block "$@"
      ;;
    step_done)
      step_done "$@"
      ;;
    step_complete)
      step_complete "$@"
      ;;
    help)
      usage
      ;;
    *)
      # fail-closed (C8-1): 未知命令拒绝静默 no-op（rc 0 假成功）——
      # 函数名（init_state/finish_step 等）≠ dispatcher 子命令名（init/finish 等）
      echo "unknown_command: $cmd（子命令名≠内部函数名, 见 Usage; 典型误用: init_state → init）" >&2
      usage >&2
      exit 2
      ;;
  esac
fi
