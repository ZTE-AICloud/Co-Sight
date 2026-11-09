#!/usr/bin/env bash
# 步 1.6①② 验证门: build-plan 物化增量表 + matching↔build-plan 物化对账 + step-3 接线
# 用法: bash tests/flow/step3-reconciliation-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
VALIDATOR="scripts/validate-plan-v2.py"
CATALOG="$REPO_ROOT/knowledge/shared/pattern-catalog.yaml"

# bp_has / bp_none_has: 只看 results[1]（build-plan 半边）的 findings
bp_has() { # bp_has <描述> <finding子串> <json文件>
  if python3 -I -c "
import json,sys
d=json.load(open('$3'))
fs=[f['check'] for r in d['results'][1:] for f in r.get('findings',[])]
assert any('$2' in x for x in fs), fs" 2>/dev/null; then ok "$1"; else
    bad "$1 —— bp findings: $(python3 -I -c "import json,sys; print([f['check'] for r in json.load(open('$3'))['results'][1:] for f in r.get('findings',[])])" 2>/dev/null)"
  fi
}
bp_none_has() { # bp_none_has <描述> <finding子串> <json文件>
  if python3 -I -c "
import json,sys
d=json.load(open('$3'))
fs=[f['check'] for r in d['results'][1:] for f in r.get('findings',[])]
assert not any('$2' in x for x in fs), fs" 2>/dev/null; then ok "$1"; else bad "$1"; fi
}

mk_decision() { # mk_decision <输出路径>
  cat > "$1" <<'EOF'
---
decision_id: t-step3-recon
timestamp: "2026-10-14T00:00:00Z"
pipeline: agent-creation
selected_patterns: [W1, G1]
build_type:
  type: single
---

## 结构决策

单 Agent，无 SubAgent。

## 决策物化

| W1 | 步骤序列表承载固定执行顺序（输入检查→处理→报告） | — |
| G1 | 独立复核者校验关键判定（误判打回→修正→重审≤2轮） | executor_subagent |
EOF
}

# mk_bp <输出路径> <materialization yaml 行...>（每行一条目, 花括号内字面；嵌套 file: 形态）
# 双形态契约: 平铺 path: 为权威形态（schemas/build-plan.schema.yaml），嵌套 file: 包裹兼容；
# 平铺变体见 mk_bp_flat
mk_bp() {
  local out="$1"; shift
  {
    cat <<'EOF'
---
plan_version: "2.0"
mode: greenfield
selected_patterns: [W1, G1]
---

## 决策物化表

```yaml
materialization:
EOF
    for entry in "$@"; do echo "  - $entry"; done
    cat <<'EOF'
```

## 文件清单

```yaml
file:
  path: workflow.md
  type: workflow_md
  deps: []
  read_first: []
  materializes: [W1]
  brief: "步骤序列表承载固定执行顺序：输入完整性检查→三维并行扫描→独立复核→结构化报告输出，每步声明输入输出契约与完成自查项，工序卡形态而非描述体"
  invariants: []
  acceptance: []
  anti_patterns: []
```

```yaml
file:
  path: .claude/agents/reviewer.md
  type: subagent
  deps: [workflow.md]
  read_first: []
  materializes: [G1]
  brief: "独立复核子代理：校验扫描关键判定，误判打回来源修正后重审并设轮次上限，只读结论不读中间推理，双向 forbidden_inputs 隔离，写完自查 I/O 闭合"
  invariants: []
  acceptance: []
  anti_patterns: []
```
EOF
  } > "$out"
}

run_pair() { # run_pair <decision> <build-plan> <json输出路径>; rc 经全局 RC 返回
  python3 "$VALIDATOR" --decision "$1" --build-plan "$2" --catalog "$CATALOG" > "$3" 2>/dev/null
  RC=$?
}

mk_bp_flat() { # mk_bp_flat <输出路径> <materialization yaml 行...>（mk_bp 生成后展开为平铺形态）
  mk_bp "$@"
  python3 -I - "$1" <<'PY'
import sys, re
p = sys.argv[1]
src = open(p, encoding="utf-8").read()
def flat(m):
    inner = "\n".join(ln[2:] if ln.startswith("  ") else ln
                      for ln in m.group(1).splitlines())
    return "```yaml\n" + inner + "\n```"
src = re.sub(r"```yaml\nfile:\n(.*?)```", flat, src, flags=re.DOTALL)
open(p, "w", encoding="utf-8").write(src)
PY
}

echo "══ ① 增量表 + ② 对账: 正例 ══"
mk_decision "$TMP/decision.md"
mk_bp "$TMP/bp-ok.md" \
  '{pattern_id: W1, target_files: [workflow.md]}' \
  '{pattern_id: G1, target_files: [.claude/agents/reviewer.md]}'
run_pair "$TMP/decision.md" "$TMP/bp-ok.md" "$TMP/ok.json"
check "对账正例（2 行 ↔ 2 绑定行）→ PASS" 0 "$RC"
bp_none_has "正例无任何 MAT_ finding" "MAT_" "$TMP/ok.json"
python3 -I -c "
import json,sys
d=json.load(open('$TMP/ok.json'))
assert d['results'][0]['materialization_ids'] == ['W1','G1'], d['results'][0].get('materialization_ids')" \
  && ok "decision 侧暴露 materialization_ids（接线消费面）" || bad "materialization_ids 缺失或值错"

echo "══ ①② 双形态归一: 平铺权威 + 嵌套兼容 ══"
mk_bp_flat "$TMP/bp-flat-ok.md" \
  '{pattern_id: W1, target_files: [workflow.md]}' \
  '{pattern_id: G1, target_files: [.claude/agents/reviewer.md]}'
run_pair "$TMP/decision.md" "$TMP/bp-flat-ok.md" "$TMP/flatok.json"
check "平铺形态正例 → PASS" 0 "$RC"
bp_none_has "平铺正例无任何 MAT_ finding" "MAT_" "$TMP/flatok.json"

mk_bp_flat "$TMP/bp-flat-missing.md" '{pattern_id: W1, target_files: [workflow.md]}'
run_pair "$TMP/decision.md" "$TMP/bp-flat-missing.md" "$TMP/flatmissing.json"
check "平铺形态负例（缺 G1 绑定行）→ FAIL" 1 "$RC"
bp_has "平铺负例报 MAT_missing_binding（非静默吞）" "MAT_missing_binding: G1" "$TMP/flatmissing.json"

echo "══ ② 对账反例: 四类漂移 ══"
mk_bp "$TMP/bp-missing.md" '{pattern_id: W1, target_files: [workflow.md]}'
run_pair "$TMP/decision.md" "$TMP/bp-missing.md" "$TMP/missing.json"
check "缺绑定行（G1）→ FAIL" 1 "$RC"
bp_has "报 MAT_missing_binding" "MAT_missing_binding: G1" "$TMP/missing.json"

mk_bp "$TMP/bp-invent.md" \
  '{pattern_id: W1, target_files: [workflow.md]}' \
  '{pattern_id: G1, target_files: [.claude/agents/reviewer.md]}' \
  '{pattern_id: K9, target_files: [workflow.md]}'
run_pair "$TMP/decision.md" "$TMP/bp-invent.md" "$TMP/invent.json"
check "发明 matching 表外绑定行（K9）→ FAIL" 1 "$RC"
bp_has "报 MAT_unbound_pattern" "MAT_unbound_pattern: K9" "$TMP/invent.json"

mk_bp "$TMP/bp-dup.md" \
  '{pattern_id: W1, target_files: [workflow.md]}' \
  '{pattern_id: W1, target_files: [workflow.md]}' \
  '{pattern_id: G1, target_files: [.claude/agents/reviewer.md]}'
run_pair "$TMP/decision.md" "$TMP/bp-dup.md" "$TMP/dup.json"
check "重复绑定行（W1 ×2）→ FAIL" 1 "$RC"
bp_has "报 MAT_duplicate_binding" "MAT_duplicate_binding: W1" "$TMP/dup.json"

mk_bp "$TMP/bp-transcribe.md" \
  '{pattern_id: W1, mechanism: "步骤序列表承载固定执行顺序（输入检查→处理→报告）", target_files: [workflow.md]}' \
  '{pattern_id: G1, target_files: [.claude/agents/reviewer.md], verify: "重审≤2轮"}'
run_pair "$TMP/decision.md" "$TMP/bp-transcribe.md" "$TMP/transcribe.json"
check "转写回潮（mechanism/verify 混入增量表）→ FAIL" 1 "$RC"
bp_has "报 MAT_transcription_duplicate（mechanism）" "MAT_transcription_duplicate: W1 增量表携带 mechanism" "$TMP/transcribe.json"
bp_has "报 MAT_transcription_duplicate（verify）" "MAT_transcription_duplicate: G1 增量表携带 verify" "$TMP/transcribe.json"

mk_bp "$TMP/bp-notf.md" \
  '{pattern_id: W1, target_files: [workflow.md]}' \
  '{pattern_id: G1}'
run_pair "$TMP/decision.md" "$TMP/bp-notf.md" "$TMP/notf.json"
check "绑定行缺 target_files（无路径增量）→ FAIL" 1 "$RC"
bp_has "报 target_files 非空" "G1 target_files 非空" "$TMP/notf.json"

echo "══ step-3 接线拦截 + retry 回路收敛 ══"
mkdir -p "$TMP/gate-results"
mk_bp "$TMP/bp-drift.md" '{pattern_id: W1, target_files: [workflow.md]}'
# 接线命令形态 = workflow.md step-3 校验接线段（verdict 重定向落 reconciliation 文件）
python3 "$VALIDATOR" \
  --decision "$TMP/decision.md" \
  --build-plan "$TMP/bp-drift.md" \
  --catalog "$CATALOG" \
  > "$TMP/gate-results/step-3-build-planning.reconciliation.json" 2>/dev/null
RC=$?
check "漂移 build-plan 经接线命令 → rc=1（main agent 可拦截）" 1 "$RC"
python3 -I -c "
import json,sys
d=json.load(open('$TMP/gate-results/step-3-build-planning.reconciliation.json'))
bp=d['results'][1]
assert bp['verdict']=='FAIL' and any(f['check'].startswith('MAT_missing_binding') for f in bp['findings']), bp" \
  && ok "reconciliation 文件机读: verdict=FAIL + MAT_ 点名（修复信号）" || bad "reconciliation 文件不可机读"
# retry 回路: 重跑 build-planner（修复后）→ 同一接线命令 → PASS
mk_bp "$TMP/bp-drift.md" \
  '{pattern_id: W1, target_files: [workflow.md]}' \
  '{pattern_id: G1, target_files: [.claude/agents/reviewer.md]}'
python3 "$VALIDATOR" \
  --decision "$TMP/decision.md" \
  --build-plan "$TMP/bp-drift.md" \
  --catalog "$CATALOG" \
  > "$TMP/gate-results/step-3-build-planning.reconciliation.json" 2>/dev/null
RC=$?
check "retry 修复后同命令重跑 → rc=0（回路收敛）" 0 "$RC"
python3 -I -c "
import json,sys
d=json.load(open('$TMP/gate-results/step-3-build-planning.reconciliation.json'))
assert d['overall']=='PASS', d['overall']" \
  && ok "reconciliation 文件翻转为 PASS（可追溯覆盖写）" || bad "reconciliation 未翻转为 PASS"

echo "══ C8-4 畸形输入（≥3 负例, 全部机读 FAIL 无崩溃）══"
mk_bp "$TMP/bp-nomat.md" >/dev/null 2>&1 # 占位; 下行重写无 materialization 块版本
python3 -I - "$TMP/bp-nomat.md" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
head, rest = src.split("## 决策物化表", 1)
rest = rest.split("## 文件清单", 1)[1]
open(sys.argv[1], "w", encoding="utf-8").write(head + "## 文件清单\n" + rest)
PY
run_pair "$TMP/decision.md" "$TMP/bp-nomat.md" "$TMP/nomat.json"
check "畸形 1: 缺 materialization 块 → FAIL（无崩溃）" 1 "$RC"
bp_has "报恰一非空块缺失" "恰有一个非空 materialization 块" "$TMP/nomat.json"

python3 -I - "$TMP/bp-ok.md" "$TMP/bp-scalar.md" <<'PY'
import sys, re
src = open(sys.argv[1], encoding="utf-8").read()
src = src.replace("  - {pattern_id: W1, target_files: [workflow.md]}", "  - W1")
src = src.replace("  - {pattern_id: G1, target_files: [.claude/agents/reviewer.md]}", "  - G1")
open(sys.argv[2], "w", encoding="utf-8").write(src)
PY
run_pair "$TMP/decision.md" "$TMP/bp-scalar.md" "$TMP/scalar.json"
check "畸形 2: materialization 条目为标量 → FAIL（无崩溃）" 1 "$RC"
bp_has "报条目非对象" "物化条目非对象" "$TMP/scalar.json"

head -6 "$TMP/decision.md" > "$TMP/decision-trunc.md"   # 截断 frontmatter（无收尾 ---）
run_pair "$TMP/decision-trunc.md" "$TMP/bp-ok.md" "$TMP/trunc.json"
check "畸形 3: decision frontmatter 截断 → FAIL（对账优雅跳过, 无崩溃）" 1 "$RC"
python3 -I -c "
import json,sys
d=json.load(open('$TMP/trunc.json'))
assert any('frontmatter' in f['check'] for f in d['results'][0]['findings']), d['results'][0]" \
  && ok "decision 侧报 frontmatter 解析失败（机读）" || bad "decision 侧未报截断"

echo "══ C8-2 位置无关 + 不新增 gate 件 ══"
( cd "$TMP" && python3 "$REPO_ROOT/scripts/validate-plan-v2.py" \
    --decision "$TMP/decision.md" --build-plan "$TMP/bp-ok.md" --catalog "$CATALOG" \
    > "$TMP/offroot.json" 2>/dev/null )
check "仓外目录 + 全绝对路径参数 → PASS" 0 "$?"
bash scripts/check-gate-registry.sh >/dev/null 2>&1 && ok "gate registry 闭合 PASS（未新增 gate 件）" || bad "gate registry FAIL"
if grep -q "reconciliation" phase/gates/gates.yaml; then bad "gates.yaml 混入 reconciliation（违不新增 gate 件）"; else ok "gates.yaml 无 reconciliation 条目"; fi

echo "══ 回归: 既有套件 ══"
bash tests/speedup/batch1-verify.sh >/dev/null 2>&1 && ok "批次 1 套件回归 21/21" || bad "批次 1 套件回归失败"
bash tests/speedup/batch2-verify.sh >/dev/null 2>&1 && ok "批次 2 套件回归 16/16" || bad "批次 2 套件回归失败"
bash tests/gates/stage1-verify.sh >/dev/null 2>&1 && ok "stage1 套件回归 49/49" || bad "stage1 套件回归失败"
bash tests/gates/stage3-verify.sh >/dev/null 2>&1 && ok "stage3 套件回归 18/18" || bad "stage3 套件回归失败"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
