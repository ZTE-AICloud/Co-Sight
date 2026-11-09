#!/usr/bin/env bash
# G024: step 产物落盘检查（gates.yaml triggers[].outputs 清单驱动）
# 承接原 validate-contract.sh --node（P10 删除 contract.yaml 后迁移至此，见
# docs/plan/pipeline-io-contract-removal.md §2.1）
# 协议: stdin JSON → stdout JSON → exit 0(PASS)/2(FAIL)
# 输入: {"step_id": "...", "name": "...", "root": "<用户 cwd, 默认 $PWD>"}
# 数据源: phase/gates/gates.yaml triggers[step_id].outputs（机器可检事实源，P10.5 机检层）
# 路径模板（P10: 原 contract.yaml paths 模板的唯一权威迁移地）:
#   {work_root}   = .agent-genesis/work/{name}/agent-creation
#   {output_root} = output/agents/{name}/v1
#   {name}        = 用户确认的 kebab-case 名
#   （skill 线 trigger 的 outputs 用含 {name} 的字面路径: work 子目录为
#     .agent-genesis/work/{name}/create-skill|optimize-skill/，输出 output/skills/{name}/v1/）
# FAIL-CLOSED（§0.1a）: outputs 清单缺失/为空 → FAIL，绝不空转恒 PASS
#   （前科: 6ab8b96 validate-contract --node 空 outputs 分支缺失导致 always-PASS）
set -euo pipefail

INPUT=$(cat)
STEP_ID=$(echo "$INPUT" | jq -r '.step_id // ""')
NAME=$(echo "$INPUT" | jq -r '.name // ""')
ROOT=$(echo "$INPUT" | jq -r '.root // ""')
# 可选 outputs 覆盖键（fast lane 条件 outputs 语义, 方案 §4.4: 注册全集, 按实际
# 形态传子集——如 step-f2 形态①③ 仅 self-report.md, 形态② 含 trace-diagnosis.md）。
# 缺省不传 → 读注册表全集（既有调用行为零变化）; 传入须为非空数组, 否则 FAIL-CLOSED。
OUTPUTS_OVERRIDE=$(echo "$INPUT" | jq -c 'if has("outputs") then .outputs else empty end' 2>/dev/null || true)
[[ -z "$ROOT" || "$ROOT" == "null" ]] && ROOT="$PWD"

if [[ -z "$STEP_ID" || "$STEP_ID" == "null" ]]; then
  echo '{"gate_id":"gate.step.outputs","verdict":"FAIL","failures":[{"type":"missing_step_id"}]}'
  exit 2
fi

# gates.yaml 位于插件根（脚本 ../.. 相对定位，不依赖 cwd —— 防 cd 漂移，
# 同 scripts/gates/g022 只消费 work_dir 的惯例；插件根只读）
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATES_YAML="$REPO_ROOT/phase/gates/gates.yaml"

if [[ ! -f "$GATES_YAML" ]]; then
  echo "{\"gate_id\":\"G024\",\"verdict\":\"FAIL\",\"failures\":[{\"type\":\"gates_yaml_missing\",\"path\":\"$GATES_YAML\"}]}"
  exit 2
fi

RESULT=$(python3 - "$GATES_YAML" "$STEP_ID" "$NAME" "$ROOT" "$OUTPUTS_OVERRIDE" <<'PY'
import os, sys, json

gates_yaml, step_id, name, root = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
override = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None

try:
    import yaml
except ImportError:
    print(json.dumps({"verdict": "FAIL", "failures": [{"type": "pyyaml_missing"}]}))
    sys.exit(0)

try:
    with open(gates_yaml, encoding="utf-8") as f:
        gates = yaml.safe_load(f)
except Exception as e:
    print(json.dumps({"verdict": "FAIL", "failures": [{"type": "gates_yaml_parse_error", "error": str(e)}]}))
    sys.exit(0)

triggers = (gates or {}).get("triggers") or {}
trigger = triggers.get(step_id)

# FAIL-CLOSED: 未知 step 或 outputs 缺失/为空 → FAIL
if trigger is None:
    print(json.dumps({"verdict": "FAIL", "failures": [{"type": "unknown_step_id", "step_id": step_id}]}))
    sys.exit(0)

outputs = trigger.get("outputs")
if override is not None:
    # 可选覆盖（条件 outputs 子集）: 须为非空 JSON 数组（FAIL-CLOSED, 与注册表同严）
    try:
        outputs = json.loads(override)
    except Exception:
        print(json.dumps({"verdict": "FAIL", "failures": [{"type": "outputs_override_invalid", "step_id": step_id}]}))
        sys.exit(0)
    if not outputs or not isinstance(outputs, list):
        print(json.dumps({"verdict": "FAIL", "failures": [{"type": "outputs_missing_or_empty", "step_id": step_id, "source": "override"}]}))
        sys.exit(0)
if not outputs or not isinstance(outputs, list):
    print(json.dumps({"verdict": "FAIL", "failures": [{"type": "outputs_missing_or_empty", "step_id": step_id}]}))
    sys.exit(0)

work_root = f".agent-genesis/work/{name}/agent-creation"
output_root = f"output/agents/{name}/v1"

checked, missing = [], []
for raw in outputs:
    p = str(raw)
    p = p.replace("{work_root}", work_root).replace("{output_root}", output_root).replace("{name}", name)
    full = os.path.join(root, p)
    is_dir_expect = p.endswith("/")
    ok = os.path.isdir(full) if is_dir_expect else os.path.isfile(full)
    checked.append(p)
    if not ok:
        missing.append({"type": "output_missing", "path": p})

if missing:
    print(json.dumps({"verdict": "FAIL", "checked": checked, "failures": missing}))
else:
    print(json.dumps({"verdict": "PASS", "checked": checked, "failures": []}))
PY
)

VERDICT=$(echo "$RESULT" | jq -r '.verdict')
echo "$RESULT" | jq -c --arg gid "gate.step.outputs" --arg sid "$STEP_ID" \
  '{gate_id:$gid, step_id:$sid, verdict, checked:(.checked // []), failures:(.failures // [])}'
if [[ "$VERDICT" == "PASS" ]]; then
  exit 0
else
  exit 2
fi
