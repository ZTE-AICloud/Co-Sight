#!/usr/bin/env bash
# 阶段 1 验证门（gate 治理方案 §3）——合成用例，全部通过输出 ALL PASS
# 用法: bash tests/gates/stage1-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { # check <描述> <期望rc> <实际rc>
  if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi
}
check_json() { # check_json <描述> <python表达式> <json文本>
  if echo "$3" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert ($2), d" 2>/dev/null; then
    ok "$1"
  else
    bad "$1 —— got: $(echo "$3" | head -c 300)"
  fi
}

echo "══ g014 fail-closed ══"
out=$(echo '{}' | bash scripts/gates/g014-skill-rule-quality.sh); rc=$?
check "缺键 FAIL" 2 "$rc"
check_json "报 missing_input/skills_dir" "any(f['type']=='missing_input' and f['key']=='skills_dir' for f in d['failures'])" "$out"

out=$(echo '{"skills_dir":"'"$TMP"'/nope","rules_dir":"'"$TMP"'/nope2"}' | bash scripts/gates/g014-skill-rule-quality.sh); rc=$?
check "目录不存在 FAIL" 2 "$rc"

mkdir -p "$TMP/sk/my-skill" "$TMP/rules"
printf -- '---\nname: x\ndescription: y\n---\nbody\n' > "$TMP/sk/my-skill/SKILL.md"
printf -- '# rule\n' > "$TMP/rules/plain.md"
out=$(echo '{"skills_dir":"'"$TMP"'/sk","rules_dir":"'"$TMP"'/rules"}' | bash scripts/gates/g014-skill-rule-quality.sh); rc=$?
# 阶段 3 降严: 缺 extends 行从 FAIL 改为 CONCERNS rc0（不继承 common 层是合法选择）
check "rule 缺 extends 行 → CONCERNS rc0（阶段 3 降严）" 0 "$rc"
check_json "verdict=CONCERNS" "d['verdict']=='CONCERNS'" "$out"
printf -- '> This file extends common/x.md\n# rule\n' > "$TMP/rules/plain.md"
out=$(echo '{"skills_dir":"'"$TMP"'/sk","rules_dir":"'"$TMP"'/rules"}' | bash scripts/gates/g014-skill-rule-quality.sh); rc=$?
check "合法输入 PASS" 0 "$rc"
mkdir -p "$TMP/sk/bad skill"
printf -- '---\nname: x\ndescription: y\n---\nbody\n' > "$TMP/sk/bad skill/SKILL.md"
out=$(echo '{"skills_dir":"'"$TMP"'/sk","rules_dir":"'"$TMP"'/rules"}' | bash scripts/gates/g014-skill-rule-quality.sh); rc=$?
check "空格路径不碎（仍 PASS，未漏检崩溃）" 0 "$rc"

echo "══ g026 输入校验 ══"
out=$(printf 'not json' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "非 JSON → input_error" 3 "$rc"
check_json "input_error 类型" "d['failures'][0]['type']=='input_error'" "$out"
out=$(echo '{"gates":[]}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "空 gates → input_error" 3 "$rc"
out=$(echo '{"gates":["runner.exit"],"profile":"agent-exit","build_plan":"x","output_dir":"y"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "G028 agent-exit 缺 work_dir → FAIL（脚本内 fail-closed）" 3 "$rc"
out=$(echo '{"gates":["runner.exit"],"build_plan":"x","output_dir":"y","work_dir":"w","skills_dir":"s","rules_dir":"r"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "G028 缺 profile → input_error" 3 "$rc"
check_json "缺键报告指明 profile" "any(f['type']=='input_error' and 'profile' in json.dumps(f) for f in d['failures'])" "$out"
out=$(echo '{"gates":["gate.skill.quality"],"work_dir":"x"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "G014 缺 skills_dir/rules_dir → FAIL（g014 自身 fail-closed，已归并 G028 模块）" 3 "$rc"

echo "══ g026 正常批跑 + CONCERNS 分支 + 防呆 + stderr ══"
mkdir -p "$TMP/fake/scripts/gates"
cat > "$TMP/fake/scripts/gates/g901-fakepass.sh" <<'EOF'
#!/bin/bash
cat >/dev/null
echo '{"gate_id":"G901","verdict":"PASS","failures":[]}'
exit 0
EOF
cat > "$TMP/fake/scripts/gates/g902-fakeconcern.sh" <<'EOF'
#!/bin/bash
cat >/dev/null
echo '{"gate_id":"G902","verdict":"CONCERNS","concerns":[{"c":"watch this"}]}'
exit 0
EOF
cat > "$TMP/fake/scripts/gates/g903-fakestderr.sh" <<'EOF'
#!/bin/bash
cat >/dev/null
echo "some diagnostic noise" >&2
echo '{"gate_id":"G903","verdict":"PASS"}'
exit 0
EOF
out=$(echo '{"gates":["G901"]}' | G026_GATES_DIR="$TMP/fake/scripts/gates" bash "$REPO_ROOT/scripts/gates/g026-batch-gates.sh"); rc=$?
check "批跑单 gate PASS" 0 "$rc"
out=$(echo '{"gates":["G901","G902"]}' | G026_GATES_DIR="$TMP/fake/scripts/gates" bash "$REPO_ROOT/scripts/gates/g026-batch-gates.sh"); rc=$?
check "CONCERNS → 整体 CONCERNS rc1（原 * 分支误判 FAIL 已修）" 1 "$rc"
check_json "concerns 透传合并" "d['verdict']=='CONCERNS' and len(d['concerns'])==1" "$out"
out=$(echo '{"gates":["G903"]}' | G026_GATES_DIR="$TMP/fake/scripts/gates" bash "$REPO_ROOT/scripts/gates/g026-batch-gates.sh"); rc=$?
check "stderr 不再丢弃" 0 "$rc"
check_json "stderr_notes 捕获" "d['stderr_notes'][0]['stderr'].startswith('some diagnostic')" "$out"
mkdir -p "$TMP/prod" && touch "$TMP/prod/.keep"
out=$(echo '{"gates":["G005-goodsuffix"],"target":"'"$TMP/prod"'"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
# sunset 后: 编号写法（含 -goodsuffix 截断）必 unknown fail-closed——验证截断解析路径已退场
check "sunset 后编号带后缀写法 → unknown fail-closed" 3 "$rc"
check_json "unknown_gate_script 兜底" "any(f.get('type')=='unknown_gate_script' for f in d['failures'])" "$out"
out=$(echo '{"gates":["G999"],"target":"'"$TMP/prod"'"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "未知 gate → FAIL" 3 "$rc"
check_json "unknown_gate_script + warnings 不静默" "any(f['type']=='unknown_gate_script' for f in d['failures']) and d.get('warnings')" "$out"

echo "══ helpers: GATE_PENDING / retry.max / after_exhausted / CONCERNS ══"
# gates.yaml fixture: retry.max=0 + after_exhausted / retry.max=1 + BACK_OFF / CONCERNS
cat > "$TMP/gates-fixture.yaml" <<'EOF'
defaults:
  verdict_wait_seconds: 1
triggers:
  step-no-retry:
    step_id: step-no-retry
    on_failure: {retry: {max: 0}, escalate: {always: true}}
  step-backoff:
    step_id: step-backoff
    on_failure: {retry: {max: 1, back_off_to: "step-prev"}, escalate: {after_exhausted: false}}
  step-escalate:
    step_id: step-escalate
    on_failure: {retry: {max: 1, back_off_to: "step-prev"}, escalate: {after_exhausted: true}}
  step-concerns:
    step_id: step-concerns
    on_failure: {retry: {max: 1}}
EOF
W="$TMP/work"; mkdir -p "$W"
bash scripts/main-agent-helpers.sh init "$W" >/dev/null
# 未知子命令 fail-closed（knowledge-scout 实战: init_state 误用曾 rc0 静默 no-op）
out=$(bash scripts/main-agent-helpers.sh init_state "$W" 2>&1); rc=$?
check "未知子命令 rc=2（拒绝静默 no-op 假成功）" 2 "$rc"
echo "$out" | grep -q "unknown_command: init_state" && ok "stderr 报 unknown_command（函数名≠子命令名提示）" || bad "unknown_command 缺失: $out"
# init 指令接线锚（agent 线 SKILL.md + workflow.md 两面; skill 线本就有）
grep -q 'main-agent-helpers.sh init ".agent-genesis/work/{name}" agent-creation' skills/harness-create/SKILL.md \
  && ok "harness-create SKILL.md init 指令在场" || bad "harness-create SKILL.md 缺 init 指令"
grep -q 'main-agent-helpers.sh init ".agent-genesis/work/{name}" agent-creation' skills/harness-create/references/workflow.md \
  && ok "harness-create workflow.md §Main Agent 必做 init 项在场" || bad "harness-create workflow.md 缺 init 项"
grep -q 'main-agent-helpers.sh init ".agent-genesis/work/{name}" skill-foundry' skills/skill-foundry/references/workflow.md \
  && ok "skill-foundry workflow.md init 项在场（对称面核对）" || bad "skill-foundry workflow.md 缺 init 项"
out=$(GATES_YAML="$TMP/gates-fixture.yaml" bash scripts/main-agent-helpers.sh step_done step-x "$W" "" '[]'); rc=$?
check "step_done 退出码 0" 0 "$rc"
check_json "step_done verdict 未落盘 → GATE_PENDING（禁止 PROCEED）" "d['action']=='GATE_PENDING' and d['gate_verdict']=='PENDING'" "$out"

export GATES_YAML="$TMP/gates-fixture.yaml"
mkdir -p "$W/no-retry"; bash scripts/main-agent-helpers.sh init "$W/no-retry" >/dev/null
echo '{"verdict":"FAIL","failures":[{"type":"t"}]}' > "$W/no-retry/gate-results/step-no-retry.json"
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh decide step-no-retry "$W/no-retry"); rc=$?
check "retry.max=0 从注册表读取 → 不 RETRY 直接 ESCALATE_STEP" 0 "$rc"
[ "$out" = "ESCALATE_STEP" ] && ok "决策=ESCALATE_STEP" || bad "决策=$out（期望 ESCALATE_STEP）"

mkdir -p "$W/bo"; bash scripts/main-agent-helpers.sh init "$W/bo" >/dev/null
echo '{"verdict":"FAIL","failures":[]}' > "$W/bo/gate-results/step-backoff.json"
python3 - "$W/bo/orchestrator-state.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p)) or {}
d["steps"] = [{"step_id": "step-backoff", "retry_count": 1, "status": "DONE", "gate_verdict": "PENDING"}]
yaml.dump(d, open(p, "w"), default_flow_style=False, sort_keys=False)
PY
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh decide step-backoff "$W/bo")
[ "$out" = "BACK_OFF:step-prev" ] && ok "retry 耗尽 + after_exhausted:false → BACK_OFF" || bad "决策=$out"

mkdir -p "$W/esc"; bash scripts/main-agent-helpers.sh init "$W/esc" >/dev/null
echo '{"verdict":"FAIL","failures":[]}' > "$W/esc/gate-results/step-escalate.json"
python3 - "$W/esc/orchestrator-state.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p)) or {}
d["steps"] = [{"step_id": "step-escalate", "retry_count": 1, "status": "DONE", "gate_verdict": "PENDING"}]
yaml.dump(d, open(p, "w"), default_flow_style=False, sort_keys=False)
PY
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh decide step-escalate "$W/esc")
[ "$out" = "ESCALATE_STEP" ] && ok "retry 耗尽 + after_exhausted:true → ESCALATE_STEP（不再被 BACK_OFF 吞掉）" || bad "决策=$out"

mkdir -p "$W/cc"; bash scripts/main-agent-helpers.sh init "$W/cc" >/dev/null
echo '{"verdict":"CONCERNS","concerns":[{"c":1}]}' > "$W/cc/gate-results/step-concerns.json"
python3 - "$W/cc/orchestrator-state.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p)) or {}
d["steps"] = [{"step_id": "step-concerns", "retry_count": 0, "status": "DONE", "gate_verdict": "PENDING"}]
yaml.dump(d, open(p, "w"), default_flow_style=False, sort_keys=False)
PY
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh summary step-concerns "$W/cc")
[ "$out" = "CONCERNS" ] && ok "step_gate_summary CONCERNS → 记 concern 不走失败路径" || bad "summary=$out"
python3 - "$W/cc/orchestrator-state.yaml" <<'PY'
import sys, yaml, json
d = yaml.safe_load(open(sys.argv[1])) or {}
st = [s for s in d.get("steps", []) if s.get("step_id") == "step-concerns"][0]
assert st.get("gate_verdict") == "CONCERNS", st
assert "gate_failures" not in st, st
print("concern-state-ok")
PY
[ "$?" -eq 0 ] && ok "state 记 gate_verdict=CONCERNS 且无 gate_failures" || bad "state 未正确记录 CONCERNS"

echo "══ helpers step_complete 单入口 (执行+决策+落盘) ══"
# PASS → PROCEED + state gate_verdict 回写
mkdir -p "$W/sc/gate-results"; bash scripts/main-agent-helpers.sh init "$W/sc" >/dev/null
echo '{"verdict":"PASS","failures":[]}' > "$W/sc/gate-results/step-sc-pass.json"
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh step_complete step-sc-pass "$W/sc" "out/x" '["out/x/a.md"]'); rc=$?
check "step_complete PASS rc=0" 0 "$rc"
check_json "PASS → PROCEED" "d['action']=='PROCEED' and d['gate_verdict']=='PASS'" "$out"
python3 - "$W/sc/orchestrator-state.yaml" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1])) or {}
st = [s for s in d.get("steps", []) if s.get("step_id") == "step-sc-pass"][0]
assert st["gate_verdict"] == "PASS" and st["params"]["OUTPUT_DIR"] == "out/x" and st["retry_count"] == 0, st
print("sc-pass-state-ok")
PY
[ "$?" -eq 0 ] && ok "PASS 回写 state (gate_verdict/params/retry_count)" || bad "PASS 未回写 state"

# FAIL → RETRY + retry 计数落盘
echo '{"verdict":"FAIL","failures":[{"type":"t","detail":"d"}]}' > "$W/sc/gate-results/step-backoff.json"
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh step_complete step-backoff "$W/sc"); rc=$?
check "step_complete FAIL→RETRY rc=0" 0 "$rc"
check_json "FAIL → RETRY" "d['action']=='RETRY' and d['gate_verdict']=='FAIL'" "$out"
python3 - "$W/sc/orchestrator-state.yaml" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1])) or {}
st = [s for s in d.get("steps", []) if s.get("step_id") == "step-backoff"][0]
assert st["gate_verdict"] == "FAIL" and st["retry_count"] == 1 and d["total_retry_count"] == 1, st
assert st["gate_failures"][0]["detail"] == "d", st
print("sc-retry-state-ok")
PY
[ "$?" -eq 0 ] && ok "RETRY 落盘 (retry_count=1, failures 字段精度保持)" || bad "RETRY 未落盘"

# 耗尽 → BACK_OFF (fixture: after_exhausted:false, 无 block_file); retry.max=0 → ESCALATE + block_file
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh step_complete step-backoff "$W/sc")
check_json "retry 耗尽 → BACK_OFF:step-prev 无 block_file" "d['action']=='BACK_OFF:step-prev' and 'block_file' not in d" "$out"
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh step_complete step-no-retry "$W/no-retry")
check_json "retry.max=0 → ESCALATE_STEP + block_file" "d['action']=='ESCALATE_STEP' and d['block_file'].endswith('gate-block.md')" "$out"
[ -f "$W/no-retry/gate-block.md" ] && ok "gate-block.md 已落盘" || bad "gate-block.md 未落盘"

# CONCERNS → PROCEED_WITH_CONCERNS
out=$(GATES_YAML="$GATES_YAML" bash scripts/main-agent-helpers.sh step_complete step-concerns "$W/cc")
check_json "CONCERNS → PROCEED_WITH_CONCERNS" "d['action']=='PROCEED_WITH_CONCERNS'" "$out"

# 负例: rc=2 + input_error (C8-1/C8-4)
bash scripts/main-agent-helpers.sh step_complete 2>"$TMP/e1"
check "缺参 → rc2" 2 "$?"
grep -q "input_error" "$TMP/e1" && ok "缺参报 input_error" || bad "缺参无 input_error"
bash scripts/main-agent-helpers.sh step_complete step-x "$TMP/no-state" 2>"$TMP/e2"
check "state 缺失 → rc2" 2 "$?"
grep -q "orchestrator-state.yaml 不存在" "$TMP/e2" && ok "state 缺失指明路径" || bad "state 缺失信息不足"
bash scripts/main-agent-helpers.sh step_complete step-x "$W/sc" "" 'not-json' 2>"$TMP/e3"
check "outputs_json 非数组 → rc2" 2 "$?"
grep -q "input_error" "$TMP/e3" && ok "非数组报 input_error" || bad "非数组未报"

# C8-2 位置无关: 仓外目录运行
mkdir -p "$W/sc-out/gate-results"; bash scripts/main-agent-helpers.sh init "$W/sc-out" >/dev/null
echo '{"verdict":"PASS","failures":[]}' > "$W/sc-out/gate-results/step-sc-out.json"
out=$(cd "$TMP" && GATES_YAML="$GATES_YAML" bash "$REPO_ROOT/scripts/main-agent-helpers.sh" step_complete step-sc-out "$W/sc-out"); rc=$?
check "仓外目录运行 rc=0" 0 "$rc"
check_json "仓外运行 → PROCEED" "d['action']=='PROCEED'" "$out"

echo "══ bash -n 全链 ══"
syn=0
for f in scripts/gates/*.sh scripts/main-agent-helpers.sh tests/gates/stage1-verify.sh; do
  if ! bash -n "$f" 2>/dev/null; then bad "bash -n: $f"; syn=1; fi
done
[ "$syn" -eq 0 ] && ok "全部脚本 bash -n 通过"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
