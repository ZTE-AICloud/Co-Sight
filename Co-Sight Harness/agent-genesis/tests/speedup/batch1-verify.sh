#!/usr/bin/env bash
# 提速方案批次 1 验证门（docs/plan/pipeline-speedup-optimization.md OPT-1）
# 用法: bash tests/speedup/batch1-verify.sh   （在仓库根执行）
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

echo "══ validate-plan-v2 存量崩溃修复 + M7 三态 ══"
cat > "$TMP/decision.md" <<'EOF'
---
decision_id: t-batch1
timestamp: "2026-10-12T00:00:00Z"
pipeline: agent-creation
selected_patterns: [W1]
build_type:
  type: single
---

## 结构决策

单 Agent，无 SubAgent。

## 决策物化

| W1 | 步骤序列表承载固定执行顺序（输入检查→处理→报告） | — |
EOF
out=$(python3 scripts/validate-plan-v2.py --decision "$TMP/decision.md" 2>&1); rc=$?
check "合法 executor_protocol=goal-loop → PASS" 0 "$rc"
check_json "无 M7 finding" "not any('M7_' in f['check'] for r in d['results'] for f in r.get('findings',[]))" "$out"

# M7 挂 build-plan frontmatter（executor_protocol 属 build-plan 域）——构造最小合法 build-plan
mk_bp() { # mk_bp <protocol-value 或省略>
  local ep_line=""
  [ -n "${1:-}" ] && ep_line="executor_protocol: $1"
  cat > "$TMP/bp-t.md" <<EOF
---
plan_version: "2.0"
mode: greenfield
$ep_line
selected_patterns: [W1]
---

## 决策物化表

\`\`\`yaml
materialization:
  - {pattern_id: W1, target_files: [workflow.md]}
\`\`\`

## 文件清单

\`\`\`yaml
file:
  path: workflow.md
  type: workflow_md
  deps: []
  read_first: []
  materializes: [W1]
  brief: "步骤序列表承载固定执行顺序：输入完整性检查→三维并行安全扫描→独立复核→结构化报告输出，每步声明输入输出契约与完成自查项，工序卡形态而非描述体"
  invariants: []
  acceptance: []
  anti_patterns: []
\`\`\`
EOF
}

mk_bp goal-loop
out=$(python3 scripts/validate-plan-v2.py --decision "$TMP/decision.md" --build-plan "$TMP/bp-t.md" 2>&1); rc=$?
check "历史值 executor_protocol=goal-loop → FAIL（字段已废除）" 1 "$rc"
check_json "报 M7_executor_protocol_deprecated" "any('M7_executor_protocol_deprecated' in f['check'] for r in d['results'] for f in r.get('findings',[]))" "$out"

mk_bp auto
out=$(python3 scripts/validate-plan-v2.py --decision "$TMP/decision.md" --build-plan "$TMP/bp-t.md" 2>&1); rc=$?
check "残留 executor_protocol=auto → FAIL" 1 "$rc"
check_json "报 M7_executor_protocol_deprecated" "any('M7_executor_protocol_deprecated' in f['check'] for r in d['results'] for f in r.get('findings',[]))" "$out"

mk_bp ""
out=$(python3 scripts/validate-plan-v2.py --decision "$TMP/decision.md" --build-plan "$TMP/bp-t.md" 2>&1); rc=$?
check "缺失 executor_protocol → PASS（字段已废除, 缺失即合规）" 0 "$rc"

cat > "$TMP/decision-str.md" <<'EOF'
---
decision_id: t-batch1-str
timestamp: "2026-10-12T00:00:00Z"
pipeline: agent-creation
selected_patterns: [W1]
build_type: single
---

## 结构决策

单 Agent，无 SubAgent。

## 决策物化

| W1 | 步骤序列表承载固定执行顺序（输入检查→处理→报告） | — |
EOF
out=$(python3 scripts/validate-plan-v2.py --decision "$TMP/decision-str.md" 2>&1); rc=$?
check "存量形态 build_type 为 str → 不再 AttributeError 崩溃（rc∈{0,1}）" 0 "$([ $rc -eq 2 ] && echo 2 || echo 0)"

echo "══ D1 fixture 回归（fixture 已按现行契约整备: file: 包裹 + 物化增量表 + build_type 拓扑声明）══"
out=$(python3 scripts/validate-plan-v2.py --decision tests/fixtures/pr-security-reviewer/phase1-matching-decision.md --build-plan tests/fixtures/pr-security-reviewer/build-plan.md 2>&1); rc=$?
if [ $rc -eq 2 ] || echo "$out" | grep -q "Traceback"; then
  bad "D1 fixture 崩溃（rc=$rc）"
else
  check "D1 fixture 全绿（overall PASS）" 0 "$rc"
  check_json "D1 verdict/结果可解析" "'results' in d and len(d['results'])==2" "$out"
  check_json "D1 双文档零 findings" "all(not r.get('findings') for r in d['results'])" "$out"
  echo "$out" | python3 -I -c "import json,sys; [print('   -', r['target'], r['verdict'], [f['check'] for f in r.get('findings',[])][:4]) for r in json.load(sys.stdin)['results']]"
fi

echo "══ g023 批量协议 ══"
mkdir -p "$TMP/prod"
cat > "$TMP/bp.md" <<'EOF'
# build plan

```yaml
path: a.txt
invariants:
  - {type: content_contains, pattern: "hello"}
```

```yaml
path: b.txt
invariants:
  - {type: content_contains, pattern: "xyzabsent"}
```
EOF
printf 'hello world\n' > "$TMP/prod/a.txt"
printf 'nothing here\n' > "$TMP/prod/b.txt"

out=$(echo '{"gates":["gate.build.invariants"],"files":["a.txt"],"build_plan":"'"$TMP"'/bp.md","output_dir":"'"$TMP"'/prod"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "单文件全过批 → g026 整体 PASS" 0 "$rc"
out=$(echo '{"gates":["gate.build.invariants"],"files":["a.txt","b.txt"],"build_plan":"'"$TMP"'/bp.md","output_dir":"'"$TMP"'/prod"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "多文件含坏文件 → FAIL" 3 "$rc"
check_json "失败信息透传: failures 非空且含点名文件" "any(f.get('file')=='b.txt' and f.get('invariant')=='content_contains' for f in d['failures'])" "$out"
echo '{"gates":["gate.build.invariants"],"files":["a.txt","ghost.txt"],"build_plan":"'"$TMP"'/bp.md","output_dir":"'"$TMP"'/prod"}' | bash scripts/gates/g026-batch-gates.sh > "$TMP/o.json"; rc=$?
check "未声明文件 → FAIL" 3 "$rc"
check_json "未声明文件以 file+reason 记入 failures" "any(f.get('file')=='ghost.txt' and '不在 build-plan' in (f.get('reason') or '') for f in d['failures'])" "$(cat "$TMP/o.json")"
out=$(echo '{"gates":["gate.build.invariants"],"files":["a.txt"],"output_dir":"'"$TMP"'/prod"}' | bash scripts/gates/g026-batch-gates.sh); rc=$?
check "缺 build_plan → g026 schema 门控 input_error（gate.build.invariants 已登记）" 3 "$rc"
check_json "input_error 类型" "d['failures'][0]['type']=='input_error'" "$out"
out=$(printf '{"files":["a.txt"],"build_plan":"/nope/md","output_dir":"x"}' | bash scripts/gates/g023-invariants.sh); rc=$?
check "畸形输入: build_plan 不存在 → g023 直调 FAIL" 2 "$rc"
out=$(printf 'garbage not json' | bash scripts/gates/g023-invariants.sh --mode file 2>/dev/null); rc=$?
check "非 JSON stdin 不影响 argv file 模式（旧协议兼容）" 2 "$rc"

echo "══ 回归: bash -n + registry + 既有套件 ══"
syn=0
for f in scripts/gates/*.sh scripts/validate-plan-v2.py scripts/check-gate-registry.sh; do
  case "$f" in *.py) python3 -m py_compile "$f" 2>/dev/null || { bad "py_compile: $f"; syn=1; };; *) bash -n "$f" 2>/dev/null || { bad "bash -n: $f"; syn=1; };; esac
done
[ "$syn" -eq 0 ] && ok "bash -n / py_compile 全链"
bash scripts/check-gate-registry.sh >/dev/null 2>&1 && ok "check-gate-registry PASS" || bad "check-gate-registry FAIL"
bash tests/gates/stage1-verify.sh >/dev/null 2>&1 && ok "gate 治理阶段 1 套件回归 29/29" || bad "stage1 套件回归失败"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
