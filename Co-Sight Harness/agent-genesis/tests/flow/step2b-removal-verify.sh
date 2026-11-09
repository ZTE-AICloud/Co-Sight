#!/usr/bin/env bash
# Step 2b 删除方案验证门（docs/plan/step2b-merge-into-2a.md §5）
# 用法: bash tests/flow/step2b-removal-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }

echo "══ 1. dc001-channel 四态（§5.1）══"
W="$TMP/work/x/agent-creation"; GR="$TMP/work/x/gate-results"
mkdir -p "$W" "$GR"
printf '# build plan\n' > "$W/build-plan.md"
printf '# human review\n' > "$W/human-review.md"
dc() { bash scripts/dc001-channel.sh "$TMP/work/x" 2>/dev/null; }

echo '{"verdict":"pass","concerns":[]}' > "$GR/step-2-matching-review.json"
out=$(dc); rc=$?
check "a) PASS 证据 → rc0" 0 "$rc"
check_json() { # check_json <描述> <断言表达式> <json>
  if echo "$3" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert ($2), d" 2>/dev/null; then
    ok "$1"
  else
    bad "$1 —— got: $(echo "$3" | head -c 250)"
  fi
}
check_json "a) channel=fast（4/4，fast 判定恢复为核心断言）" "d['channel']=='fast'" "$out"
echo '{"verdict":"CONCERNS","concerns":[{"c":1}]}' > "$GR/step-2-matching-review.json"
out=$(dc)
check_json "b) CONCERNS → channel=full + reason 含 g017:fail" \
  "d['channel']=='full' and any('g017:fail' in r for r in d['reasons'])" "$out"
rm "$GR/step-2-matching-review.json"
echo '{"verdict":"pass","concerns":[]}' > "$GR/step-2b-matching-review.json"
out=$(dc)
check_json "c) 仅旧文件存在 → reason 含 missing（新路径生效）" \
  "any('missing_step-2-matching-review.json' in r for r in d['reasons'])" "$out"
rm "$GR/step-2b-matching-review.json"
out=$(dc)
check_json "d) 文件全缺 → reason 含 missing" \
  "any('missing_step-2-matching-review' in r for r in d['reasons'])" "$out"

echo "══ 2. pattern-matcher 自检链路静态核对（§5.2a；实跑存记）══"
python3 -I - <<'PY'
import re, sys
s = open("agents/pattern-matcher.md", encoding="utf-8").read()
checks = [
    ("tools 含 Bash", "tools: [Read, Write, Grep, Glob, Bash]" in s),
    ("description 步骤 2", "触发于 Agent 创建步骤 2。" in s),
    ("步骤 8 自检节存在", "### 步骤 8: 产出后自检（G017）" in s),
    ("marker 机制零残留（OPT-7 删守卫后防回潮）", "每次 G017 调用前重写" not in s and "executor-bash-allowlist" not in s),
    ("G017 --input 调用形态（PLUGIN_ROOT 注入式）", "g017-pattern-constraints.sh --input" in s),
    ("≤2 轮循环", "≤2 轮" in s),
    ("三态落盘", "三种终态均写" in s),
    ("修订留痕（反博弈）", "修订记录" in s and "不许静默" in s),
    ("G017_BLOCKED 兜底", "G017_BLOCKED" in s),
]
bad = [n for n, c in checks if not c]
for n, c in checks:
    print(("  ✓ " if c else "  ✗ ") + n)
sys.exit(1 if bad else 0)
PY
[ $? -eq 0 ] && ok "静态核对 9/9" || bad "静态核对存在失败"

echo "══ 3. G017 直调回归（§5.3，--input 与 stdin 双形态）══"
cat > "$TMP/decision.md" <<'EOF'
---
decision_id: t-b3
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

## 结构决策

build_type_decision: single——无 subagent 拆分, 技能物化以 role 级表为准

## 决策物化（role 级）

| pattern_id | 机制 | target_roles | verify_hint |
|------------|------|--------------|-------------|
| W1 | 步骤序列表 | workflow_step | 内容核对 |
EOF
out=$(bash scripts/gates/g017-pattern-constraints.sh --input '{"matching_decision": "'"$TMP"'/decision.md"}'); rc=$?
check "--input 形态合法 decision → PASS" 0 "$rc"
out=$(echo '{"matching_decision": "'"$TMP"'/decision.md"}' | bash scripts/gates/g017-pattern-constraints.sh); rc=$?
check "stdin 旧形态兼容 → PASS" 0 "$rc"
sed -i 's/^build_type:$/build_type: x/; s/^  type: single$/  type: single/' "$TMP/decision.md" 2>/dev/null
cat > "$TMP/decision-str.md" <<'EOF'
---
decision_id: t-str
timestamp: "2026-10-12T00:00:00Z"
pipeline: agent-creation
selected_patterns: [W1]
build_type: single
---

## Tier 2

| 维度 | 模式 | 置信度 | 理由 |
|------|------|--------|------|
| 工作流 | W1-Pipeline | high | 固定步骤 |

## 结构决策

build_type_decision: single——无 subagent 拆分, 技能物化以 role 级表为准

## 决策物化（role 级）

| pattern_id | 机制 | target_roles | verify_hint |
|------------|------|--------------|-------------|
| W1 | 步骤序列表 | workflow_step | 内容核对 |
EOF
out=$(bash scripts/gates/g017-pattern-constraints.sh --input '{"matching_decision": "'"$TMP"'/decision-str.md"}'); rc=$?
# 批次 1 归一化语义: str 形态 ≡ dict 形态 → 与 decision.md 同判（PASS，不崩溃不误报）
check "str build_type 归一化 → 与 dict 形态同判 PASS" 0 "$rc"
check_json "str 形态 verdict=PASS" "d['verdict']=='PASS'" "$out"


echo "══ 4. allowlist 桩语义（OPT-7 删守卫后 fail-open, 等价未注册）══"
python3 - <<'PY'
import json, os, subprocess, sys
hook = os.path.abspath("hooks/gate-allowlist.py")

def run(cwd, cmd):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    return subprocess.run(["python3", hook], input=payload, capture_output=True,
                          text=True, cwd=cwd)

results = []
def report(n, c):
    results.append((n, c)); print(("  ✓ " if c else "  ✗ ") + n)

# OPT-7 终态: PreToolUse:Bash 注册已移除, 本文件为 fail-open 桩——任意输入放行
# （原 §5.4 拦截语义随守卫删除, 断言对齐见 docs/plan/pipeline-speedup-optimization.md §2）
g017 = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/gates/g017-pattern-constraints.sh" --input \'{"matching_decision": "d.md"}\''
r = run(os.getcwd(), g017)
report("gate 命令无 env 注入 → 放行（fail-open 桩）", r.returncode == 0)
r = run(os.getcwd(), "echo hi")
report("非 gate 命令 → 放行（等价未注册）", r.returncode == 0)
r = run(os.getcwd(), "bash scripts/gates/g999-nope.sh --target .")
report("相对路径不存在 → 放行（无守卫不拦截）", r.returncode == 0)
sys.exit(0 if all(c for _, c in results) else 1)
PY
[ $? -eq 0 ] && ok "allowlist 桩 3/3" || bad "allowlist 桩用例失败"

echo "══ 5. 残留 grep（§5.5）══"
residual=$(grep -rn "step-2b\b\|step-2a\b" --include="*.md" --include="*.sh" --include="*.py" --include="*.yaml" . 2>/dev/null \
  | grep -v "^\./\.git\|^\./tests/fixtures\|^\./docs/\|^\./knowledge/\|^\./tests/flow/step2b-removal-verify.sh\|^\./scripts/gates/g017-pattern-constraints.sh" \
  | grep -v "→ \`\?step-2\|missing_step-2-matching-review\|更名 step-2a→step-2\|step-2a.*→.*step-2\|step-2b 并入")
if [ -n "$residual" ]; then bad "残留:"; echo "$residual" | head -10; else ok "step-2b/step-2a 残留仅存白名单"; fi

echo "══ 6. registry + G024 抽查（§5.6/7）══"
bash scripts/check-gate-registry.sh >/dev/null 2>&1 && ok "check-gate-registry PASS" || bad "check-gate-registry FAIL"
out=$(echo '{"step_id": "step-2-pattern-matching", "name": "probe", "root": "'$REPO_ROOT'"}' | bash scripts/gates/g024-output-exists.sh)
check_json "G024 新 step_id 解析含双产物" \
  "any('phase1-matching-decision' in c for c in d['checked']) and any('phase2-review' in c for c in d['checked'])" "$out"

echo "══ 7. 既有套件回归（§5.8）══"
for t in tests/speedup/batch1-verify.sh tests/speedup/batch2-verify.sh tests/gates/stage1-verify.sh tests/gates/stage3-verify.sh; do
  bash "$t" >/dev/null 2>&1 && ok "回归: $t" || bad "回归失败: $t"
done

echo "══ 8. bash -n / py_compile 全链（§5.9）══"
syn=0
for f in scripts/gates/*.sh scripts/main-agent-helpers.sh scripts/dc001-channel.sh scripts/check-gate-registry.sh; do
  bash -n "$f" 2>/dev/null || { bad "bash -n: $f"; syn=1; }
done
for f in scripts/validate-plan-v2.py hooks/gate-allowlist.py skills/e2e-test-runner/scripts/run_e2e.py; do
  python3 -m py_compile "$f" 2>/dev/null || { bad "py_compile: $f"; syn=1; }
done
[ "$syn" -eq 0 ] && ok "全链语法通过"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
