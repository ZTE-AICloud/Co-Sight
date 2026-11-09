#!/usr/bin/env bash
# 阶段 3 验证门（gate 治理方案 §5）——合成用例
# 用法: bash tests/gates/stage3-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
check_json() {
  if echo "$3" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert ($2), d" 2>/dev/null; then
    ok "$1"
  else
    bad "$1 —— got: $(echo "$3" | head -c 300)"
  fi
}

echo "══ g005 词边界 + 大小写 ══"
mkdir -p "$TMP/p1"
printf -- '这里是等待定义的阶段\n' > "$TMP/p1/a.md"
printf -- '支持期待定制的场景\n' > "$TMP/p1/b.md"
out=$(bash scripts/gates/g005-no-placeholders.sh --target "$TMP/p1"); rc=$?
check "「等待定义/期待定制」不误报" 0 "$rc"
printf -- '此处待定\n' > "$TMP/p1/c.md"
out=$(bash scripts/gates/g005-no-placeholders.sh --target "$TMP/p1"); rc=$?
check "「此处待定」仍报" 2 "$rc"
check_json "cn_placeholder 命中" "any(f['type']=='cn_placeholder' for f in d['failures'])" "$out"
rm "$TMP/p1/c.md"; printf -- 'todo: fix me\n' > "$TMP/p1/d.md"
out=$(bash scripts/gates/g005-no-placeholders.sh --target "$TMP/p1"); rc=$?
check "小写 todo: 补检命中" 2 "$rc"

echo "══ g014 extends 降 CONCERNS ══"
mkdir -p "$TMP/sk/my-skill" "$TMP/rules"
printf -- '---\nname: x\ndescription: y\n---\nbody\n' > "$TMP/sk/my-skill/SKILL.md"
printf -- '# 合法规则但不继承 common 层\n' > "$TMP/rules/standalone.md"
out=$(echo '{"skills_dir":"'"$TMP"'/sk","rules_dir":"'"$TMP"'/rules"}' | bash scripts/gates/g014-skill-rule-quality.sh); rc=$?
check "rule 缺 extends → CONCERNS rc0（原 FAIL rc2）" 0 "$rc"
check_json "verdict=CONCERNS + rule_missing_extends" "d['verdict']=='CONCERNS' and any(c['type']=='rule_missing_extends' for c in d['concerns'])" "$out"
out=$(echo '{"skills_dir":"'"$TMP"'/nope"}' | bash scripts/gates/g014-skill-rule-quality.sh); rc=$?
check "缺键仍 FAIL（fail-closed 不降级）" 2 "$rc"

echo "══ g027 单行字段 + XXX 豁免 ══"
mkdir -p "$TMP/rep"
cat > "$TMP/rep/design.md" <<'EOF'
---
mode: create
created_at: "2026-10-12T00:00:00Z"
confidence: high
---
skill_name: my-skill
operation_mode: transform
granularity_decision: single-skill
frontmatter_draft: 内联草案见下
acceptance_criteria: 见验收列表
说明: 本方案含 XXX 缩写示例
EOF
out=$(echo '{"mode":"create","report_path":"'"$TMP"'/rep/design.md","root":"'"$REPO_ROOT"'"}' | bash scripts/gates/g027-plan-sanity.sh); rc=$?
check_json "单行 key: value 不再误 FAIL" "not any(f.get('field')=='granularity_decision' for f in d.get('failures',[]))" "$out"
check_json "XXX 不再计入占位符" "not any(f['type']=='placeholders_present' for f in d.get('failures',[]))" "$out"

echo "══ g027 CONCERNS 统一 rc0 ══"
cat > "$TMP/rep/diag.md" <<'EOF'
---
mode: optimize
created_at: "2026-10-12T00:00:00Z"
confidence: high
---
## 七维诊断
- decomposition: PASS
- information: PASS
- state: PASS
- verification: FAIL
- logic_consistency: PASS
- design_form: PASS
- global_context: PASS

## 边界判定: skill 内可解决
EOF
out=$(echo '{"mode":"optimize","report_path":"'"$TMP"'/rep/diag.md","root":"'"$REPO_ROOT"'"}' | bash scripts/gates/g027-plan-sanity.sh); rc=$?
v=$(echo "$out" | python3 -I -c "import json,sys; print(json.load(sys.stdin)['verdict'])" 2>/dev/null || echo "?")
if [ "$v" = "CONCERNS" ] && [ "$rc" -eq 0 ]; then
  ok "verdict=CONCERNS 时 rc=0（原 rc1 已统一）"
else
  bad "verdict=$v rc=$rc（期望 CONCERNS/0）"
fi

echo "══ g017 无粗体 Tier-2 兼容 + 坏 validator → M0_validator_error ══"
cat > "$TMP/decision.md" <<'EOF'
---
decision_id: t-stage3
timestamp: "2026-10-12T00:00:00Z"
pipeline: agent-creation
selected_patterns: [W1]
build_type: single
---

## Tier 2

| 维度 | 模式 | 置信度 | 理由 |
|------|------|--------|------|
| 工作流 | W1-Pipeline | high | 固定步骤 |
EOF
out=$(echo '{"matching_decision":"'"$TMP"'/decision.md"}' | bash scripts/gates/g017-pattern-constraints.sh); rc=$?
check_json "无粗体表格行仍解析出选中集合（无 L1_no_tier2_rows）" "not any(f['type']=='L1_no_tier2_rows' for f in d.get('failures',[]))" "$out"
# 提速方案批次 1 已修复 validator 的 str build_type 崩溃（归一化）——此处应正常执行而非 M0
check_json "字符串 build_type 归一化后 validator 正常执行（无 M0_*、无崩溃误报）" "not any(f['type'].startswith('M0_') for f in d.get('failures',[]))" "$out"
# M0 容错路径仍有效: validator 临时不可读 → g017 必须显式 FAIL 而非静默跳过
mv scripts/validate-plan-v2.py "$TMP/validator.bak"
out=$(echo '{"matching_decision":"'"$TMP"'/decision.md"}' | bash scripts/gates/g017-pattern-constraints.sh); rc=$?
mv "$TMP/validator.bak" scripts/validate-plan-v2.py
check_json "validator 缺失 → M0_validator_missing FAIL（容错路径回归）" "any(f['type']=='M0_validator_missing' for f in d.get('failures',[]))" "$out"
# 合法 dict build_type + 无粗体 → validator 正常路径不误报
cat > "$TMP/decision2.md" <<'EOF'
---
decision_id: t-stage3b
timestamp: "2026-10-12T00:00:00Z"
pipeline: agent-creation
selected_patterns: [W1]
build_type:
  type: single
---

## Tier 2

| 维度 | 模式 | 置信度 | 理由 |
|------|------|--------|------|
| 工作流 | W1-Pipeline | high | 固定步骤 |
EOF
out=$(echo '{"matching_decision":"'"$TMP"'/decision2.md"}' | bash scripts/gates/g017-pattern-constraints.sh); rc=$?
check_json "合法 v2 frontmatter + 无粗体 → validator 正常执行（无 M0_*）" "not any(f['type'].startswith('M0_') for f in d.get('failures',[]))" "$out"

echo "══ 2.2 skill-verifier 采信改造 ═══"
SV=agents/skill-verifier.md
grep -q "采信机检结论" "$SV" && ok "采信声明存在（不重跑）" || bad "缺采信声明"
grep -q "fail-closed" "$SV" && grep -q "机检结论缺失" "$SV" && ok "fail-closed 三态条款存在（红线 3）" || bad "缺 fail-closed 条款"
grep -qE "grep -E '.*\{\{" "$SV" && bad "仍含占位符重跑指令（双轨残留, 红线 6）" || ok "无占位符重跑指令（SK-S3 归并 g005）"
grep -q "test -f SKILL.md" "$SV" && bad "仍含 SK-S1 重跑指令（双轨残留）" || ok "无 SK-S1 重跑指令"
for s in SK-S4 SK-S8 SK-S9 SK-S10; do grep -q "$s" "$SV" || bad "缺语义项 $s"; done
grep -q "SK-S4" "$SV" && grep -q "SK-S8" "$SV" && grep -q "SK-S9" "$SV" && grep -q "SK-S10" "$SV" && ok "语义四项保留（红线 2）" || true
grep -q "failed_items" "$SV" && ok "机读段 failed_items 保留" || bad "机读段丢失"
# 采信映射与 g028 module.skill.static failure 类型闭合（module+type ↔ SK-S 编号）
missing_types=$(python3 - <<'PY'
import re
g028 = open('scripts/gates/g028-exit-sanity.sh', encoding='utf-8').read()
sv = open('agents/skill-verifier.md', encoding='utf-8').read()
sec = g028.split('module.skill.static: SK-S1/S2 移植')[1].split('6. 合并 verdict')[0]
types = set(re.findall(r'"type": "(skill_[a-z_]+|frontmatter_[a-z_]+|broken_reference|script_syntax_[a-z]+|absolute_path_found)"', sec))
missing = sorted(t for t in types if t not in sv)
print(','.join(missing) if missing else 'closed')
PY
)
[ "$missing_types" = "closed" ] && ok "采信映射闭合: skill_static 全部 failure 类型入映射" || bad "映射缺口: $missing_types"
grep -q "机检结论注入" skills/skill-foundry/references/workflow.md && ok "workflow s5 派发注入存在" || bad "workflow s5 缺机检注入"
# 定义源单源化: 双源均标注脚本化 owner, 权威版 SK-S2 与实现口径一致
grep -q "module.skill.static" rules/shared/verification-checks.md && ok "verification-checks.md 标注脚本 owner" || bad "verification-checks.md 未标注 owner"
grep -q "references/\*.md 全部存在" rules/shared/verification-checks.md && ok "权威版 SK-S2 口径=内联版" || bad "权威版 SK-S2 口径漂移"
grep -q "module.skill.static" rules/shared/phase-execution-guide.md && ok "phase-execution-guide.md 标注脚本 owner" || bad "phase-execution-guide.md 未标注 owner"
grep -qE "所有引用的 rules/ 文件存在" rules/shared/verification-checks.md && bad "权威版残留旧 rules/ 口径行" || ok "无旧 rules/commands/agents/hooks 口径残留"

echo "══ 2.3 s 段编排瘦身（step_complete 单入口）════"
SW=skills/skill-foundry/references/workflow.md
SS=skills/skill-foundry/SKILL.md
grep -q "step_complete" "$SW" && ok "skill workflow s 段单入口存在" || bad "s 段无 step_complete"
grep -q 'init ".agent-genesis/work/{name}" skill-foundry' "$SW" && ok "s 段 init 指令存在（fail-closed 前置）" || bad "s 段缺 init 指令"
grep -q "step_complete" "$SS" && ok "skill SKILL.md 驱动循环同步单入口" || bad "skill SKILL.md 未同步"
grep -q "step_complete" skills/harness-create/SKILL.md && ok "agent 线 SKILL.md 驱动循环漂移修复" || bad "harness-create SKILL.md 仍为旧式手调"
python3 - <<'PY'
import yaml
d = yaml.safe_load(open('phase/gates/gates.yaml'))
sf = (d.get('pipeline') or {}).get('state_file', '')
assert 'agent-creation' not in sf, f"state_file 仍在 agent-creation 层: {sf}"
assert sf == '.agent-genesis/work/*/orchestrator-state.yaml', sf
print('ok')
PY
[ "$?" -eq 0 ] && ok "gates.yaml state_file 对齐 {name} 层（两线同构）" || bad "state_file 层级漂移"
grep -c "step_complete" skills/harness-create/references/workflow.md | grep -qE '^[1-9]' && ok "agent 线 workflow 单入口仍存（未回归）" || bad "agent 线 workflow 单入口丢失"

echo "══ gates.yaml 超时配置 ═══"
v=$(python3 -c "import yaml; print(yaml.safe_load(open('phase/gates/gates.yaml'))['defaults']['per_gate_timeout_seconds'])")
[ "$v" = "120" ] && ok "per_gate_timeout_seconds=120" || bad "per_gate_timeout_seconds=$v"

echo "══ 回归: bash -n + registry + 阶段1 套件 ═══"
syn=0
for f in scripts/gates/*.sh scripts/check-gate-registry.sh; do bash -n "$f" 2>/dev/null || { bad "bash -n: $f"; syn=1; }; done
[ "$syn" -eq 0 ] && ok "bash -n 全链"
bash scripts/check-gate-registry.sh >/dev/null 2>&1 && ok "check-gate-registry PASS" || bad "check-gate-registry FAIL"
bash tests/gates/stage1-verify.sh >/dev/null 2>&1 && ok "阶段 1 套件回归 29/29" || bad "阶段 1 套件回归失败"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
