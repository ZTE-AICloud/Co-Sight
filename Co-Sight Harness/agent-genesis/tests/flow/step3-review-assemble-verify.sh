#!/usr/bin/env bash
# 步 1.6③ 验证门: runner.review.assemble（render-human-review.py）human-review 机械段组装
# 黄金对拍基线（D3）: tests/fixtures/pr-security-reviewer/human-review.md（仓内唯一 LLM 转写版）
# 对拍口径: ①11 节标题逐字一致  ②§4 表形态/行闭合  ③§5 判断条目透传恒等
# ④ §7 行数=acceptance_criteria 数  ⑤§11 拓扑角色闭合  ⑥ dc001-channel.sh §5 消费形态不变
# 用法: bash tests/flow/step3-review-assemble-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }

RENDER="scripts/render-human-review.py"
FIX="tests/fixtures/pr-security-reviewer"
GOLDEN="$FIX/human-review.md"
FRAGMENT="$FIX/human-review-fragment.md"
OUT="$TMP/human-review.md"

# ── 套件本地最小 build-plan（双形态契约: 平铺 path: 权威 + 嵌套 file: 包裹兼容 + 物化增量表; 文件清单镜像 golden §4）──
mk_bp() { # mk_bp <输出路径>
  cat > "$1" <<'EOF'
---
plan_version: "2.0"
mode: greenfield
selected_patterns: [W1, G1, K1, DT1, DF1, IH1, IT1, CD1, CD2]
---
## 决策物化表

```yaml
materialization:
  - {pattern_id: W1, target_files: [phase/02-workflows/phase-1-security-scan.md]}
  - {pattern_id: G1, target_files: [.claude/agents/security-reviewer.md]}
```

## 文件清单

### proposal-spec.md
```yaml
file:
  path: proposal-spec.md
  type: other
  deps: []
  read_first: []
  materializes: []
  brief: "用户可读构建方案（DC-001 审批展示面）自然语言描述构建决策与验收标准映射与已知风险"
  invariants: []
  acceptance: []
  anti_patterns: []
```

### CLAUDE.md
```yaml
file:
  path: CLAUDE.md
  type: claude_md
  deps: []
  read_first: []
  materializes: [K1]
  brief: "按装配规范八章生成主调度文件含安全约束节与工具策略节与执行流程节与知识节声明"
  invariants:
    - {type: content_contains, pattern: "AKIA", derived_from: "acceptance_criteria[0]"}
  acceptance: []
  anti_patterns: []
```

### phase/02-workflows/phase-1-security-scan.md
```yaml
file:
  path: phase/02-workflows/phase-1-security-scan.md
  type: workflow_md
  deps: []
  read_first: []
  materializes: [W1]
  brief: "核心扫描工作流四步输入检查并行扫描独立复核结构化报告每步声明输入输出与失败回退"
  invariants:
    - {type: content_contains, pattern: "重审≤2轮", derived_from: "acceptance_criteria[0]"}
  acceptance: []
  anti_patterns: []
```

### .claude/agents/secret-scanner.md
```yaml
file:
  path: .claude/agents/secret-scanner.md
  type: subagent
  deps: []
  read_first: []
  materializes: [CD2]
  brief: "密钥硬编码维度扫描 SubAgent 按模式清单静态文本分析命中判 critical 写 findings"
  invariants: []
  acceptance: []
  anti_patterns: []
```

### .claude/agents/injection-scanner.md
```yaml
file:
  path: .claude/agents/injection-scanner.md
  type: subagent
  deps: []
  read_first: []
  materializes: [CD2]
  brief: "注入维度扫描 SubAgent 按特征清单静态分析拼接 SQL 直触 critical 写 findings"
  invariants:
    - {type: content_contains, pattern: "SQL", derived_from: "acceptance_criteria[1]"}
  acceptance: []
  anti_patterns: []
```

### .claude/agents/security-reviewer.md
```yaml
file:
  path: .claude/agents/security-reviewer.md
  type: subagent
  deps: []
  read_first: []
  materializes: [G1]
  brief: "独立复核 SubAgent 校验每条 critical 判定证据真实性误判打回对应扫描器重审上限两轮"
  invariants:
    - {type: content_contains, pattern: "无 critical 问题", derived_from: "acceptance_criteria[2]"}
  acceptance: []
  anti_patterns: []
```

### .claude/hooks/hooks.json
```yaml
file:
  path: .claude/hooks/hooks.json
  type: other
  generation: copy
  source: knowledge/assets/gates/hooks-config.json
  deps: []
  read_first: []
  materializes: []
  brief: "hook 配置模板整包直拷无外部脚本引用确定性拷贝不走生成循环存在性照查"
  invariants:
    - {type: file_reference_exists}
  acceptance: []
  anti_patterns: []
```
EOF
}

assemble() { # assemble <out路径>
  python3 "$RENDER" \
    --fragment "$FRAGMENT" --build-plan "$TMP/bp.md" \
    --decision "$FIX/phase1-matching-decision.md" \
    --requirements "$FIX/clarified-agent-requirements.yaml" \
    --review "$FIX/phase2-review.md" --out "$1"
}

echo "══ 1. 组装正例 + 黄金对拍（D3 基线: $GOLDEN）══"
python3 -m py_compile "$RENDER" && ok "py_compile 通过" || bad "py_compile 失败"
mk_bp "$TMP/bp.md"
out=$(assemble "$OUT"); rc=$?
check "组装正例 rc=0" 0 "$rc"
check_json="import json,sys; d=json.loads('''$out'''); assert d['runner']=='review.assemble' and d['status']=='assembled' and d['files_n']==7 and d['acceptance_n']==3 and d['subagents_n']==3 and d['passthrough_findings_n']==0"
if python3 -I -c "$check_json" 2>/dev/null; then ok "stdout JSON 摘要字段正确（files_n=7/acceptance_n=3/subagents_n=3）"; else bad "stdout JSON 摘要字段不符: $out"; fi

echo "══ 1b. 双形态归一: 平铺 build-plan 组装产物与嵌套逐字一致 ══"
mk_bp "$TMP/bp-flat.md"
python3 -I - "$TMP/bp-flat.md" <<'PY'
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
OUT_FLAT="$TMP/human-review-flat.md"
python3 "$RENDER" \
  --fragment "$FRAGMENT" --build-plan "$TMP/bp-flat.md" \
  --decision "$FIX/phase1-matching-decision.md" \
  --requirements "$FIX/clarified-agent-requirements.yaml" \
  --review "$FIX/phase2-review.md" --out "$OUT_FLAT" >/dev/null 2>&1
check "平铺形态组装 rc=0" 0 "$?"
if diff "$OUT" "$OUT_FLAT" >/dev/null; then
  ok "双形态归一: 平铺组装产物与嵌套逐字一致"
else
  bad "双形态归一: 平铺组装产物漂移 —— $(diff "$OUT" "$OUT_FLAT" | head -4)"
fi

# 对拍①: 11 节标题逐字一致
if diff <(grep "^## " "$GOLDEN") <(grep "^## " "$OUT") >/dev/null; then
  ok "黄金对拍①: 11 节标题与 LLM 转写版逐字一致"
else
  bad "黄金对拍①: 节标题漂移 —— $(diff <(grep '^## ' "$GOLDEN") <(grep '^## ' "$OUT") | head -4)"
fi
# 对拍②: §4 表形态 + 行闭合（行数 = build-plan file 块数; 表头与 golden 一致）
bp_files=$(grep -c '^```yaml' "$TMP/bp.md")
bp_files=$((bp_files - 1)) # 减去 materialization 块
t4_rows=$(sed -n '/^## 4\./,/^## 5\./p' "$OUT" | grep -cE '^\| [0-9]+ \|')
if [ "$t4_rows" -eq "$bp_files" ]; then ok "黄金对拍②: §4 行闭合（$t4_rows 行 = file 块 $bp_files）"; else bad "黄金对拍②: §4 行 $t4_rows ≠ file 块 $bp_files"; fi
grep -q '^| # | 路径 | 角色 | 生成方式 |$' "$GOLDEN" && grep -q '^| # | 路径 | 角色 | 生成方式 |$' "$OUT" \
  && ok "黄金对拍②: §4 表头与 golden 逐字一致" || bad "黄金对拍②: §4 表头漂移"
for p in CLAUDE.md .claude/agents/security-reviewer.md .claude/hooks/hooks.json; do
  sed -n '/^## 4\./,/^## 5\./p' "$OUT" | grep -qF "| $p |" \
    && ok "黄金对拍②: §4 行闭合含 $p" || bad "黄金对拍②: §4 缺 $p"
done
# 对拍③: §5 判断条目透传恒等（fragment 风险行逐字出现在组装产物 §5）
frag_risks=$(sed -n '/^## 已知风险（判断条目）/,/^## /p' "$FRAGMENT" | grep -E '^\- \[' )
sec5=$(sed -n '/^## 5\./,/^## 6\./p' "$OUT")
t5_ok=1
while IFS= read -r line; do
  [ -z "$line" ] && continue
  grep -qF -- "$line" <<<"$sec5" || { t5_ok=0; bad "黄金对拍③: §5 透传失真: $line"; }
done <<<"$frag_risks"
[ "$t5_ok" -eq 1 ] && ok "黄金对拍③: §5 判断条目透传恒等（$(grep -c . <<<"$frag_risks") 条逐字一致）"
sec5_n=$(grep -cE '^\- \[(临界|重大|轻微)\]' <<<"$sec5")
[ "$sec5_n" -ge 2 ] && ok "黄金对拍③: §5 风险条数 $sec5_n ≥2（DC-001 下限）" || bad "黄金对拍③: §5 风险仅 $sec5_n 条"
# 对拍④: §7 行数 = acceptance_criteria 数
req_n=$(grep -cE '^\s*-\s*given:' "$FIX/clarified-agent-requirements.yaml")
t7_rows=$(sed -n '/^## 7\./,/^## 8\./p' "$OUT" | grep -cE '^\| AC[0-9]+ \|')
if [ "$t7_rows" -eq "$req_n" ]; then ok "黄金对拍④: §7 验收转写 $t7_rows 行 = acceptance_criteria $req_n 条"; else bad "黄金对拍④: §7 行 $t7_rows ≠ AC $req_n"; fi
# 对拍⑤: §11 拓扑角色闭合 + 隔离标注 + 无内部编号（C9-6）
sed -n '/^## 11\./,$p' "$OUT" | grep -q '```mermaid' && ok "黄金对拍⑤: §11 mermaid 代码块" || bad "黄金对拍⑤: 缺 mermaid"
for role in secret-scanner injection-scanner security-reviewer; do
  sed -n '/^## 11\./,$p' "$OUT" | grep -q "$role" && ok "黄金对拍⑤: 拓扑含 $role" || bad "黄金对拍⑤: 拓扑缺 $role"
done
sed -n '/^## 11\./,$p' "$OUT" | grep -qE '\[(W[0-9]+|G[0-9]+|S[0-9]+_|confidence|置信度)' \
  && bad "黄金对拍⑤(C9-6): §11 泄漏内部编号/置信度" || ok "黄金对拍⑤(C9-6): §11 无内部编号/置信度"
# 对拍⑥: 机械段全文档 C9-6 抽查（§4/§5/§7/§11 由脚本渲染, fragment 段透传不扫）
mech=$(cat <(sed -n '/^## 4\./,/^## 5\./p' "$OUT") <(sed -n '/^## 7\./,/^## 8\./p' "$OUT") <(sed -n '/^## 11\./,$p' "$OUT"))
grep -qE '(置信度|confidence[:：])' <<<"$mech" && bad "对拍⑥(C9-6): 机械段泄漏置信度" || ok "对拍⑥(C9-6): 机械段无置信度/内部术语"

echo "══ 2. dc001-channel.sh §5 消费形态回归（红线 1: 消费形态不变）══"
W="$TMP/work/pr-sec"; mkdir -p "$W/agent-creation" "$W/gate-results"
cp "$OUT" "$W/agent-creation/human-review.md"
cp "$TMP/bp.md" "$W/agent-creation/build-plan.md"
cat > "$W/gate-results/step-2-matching-review.json" <<'EOF'
{"verdict": "pass", "concerns": []}
EOF
dc_out=$(bash scripts/dc001-channel.sh "$W" 2>/dev/null); dc_rc=$?
echo "$dc_out" | grep -q '"risk_level' && bad "消费回归: 无 critical 风险却被记 risk_level —— $dc_out" \
  || ok "消费回归: 无 critical 前缀 → 第 4 项不记 risk_level（前缀计数=0）"
sed -i '5a - [临界] 注入测试: 构造 critical 前缀验证消费形态' "$W/agent-creation/human-review.md"
dc_out2=$(bash scripts/dc001-channel.sh "$W" 2>/dev/null)
echo "$dc_out2" | grep -q 'risk_level:1_critical' \
  && ok "消费回归: 追加 1 条 [临界] → reasons 记 risk_level:1_critical（grep 消费形态不变）" \
  || bad "消费回归: 临界前缀未被消费 —— $dc_out2"

echo "══ 3. input_error 负例（C8-1/C8-4: 畸形输入 → rc=2 + type:input_error）══"
neg() { # neg <描述> <fragment> <bp> <review>
  o=$(python3 "$RENDER" --fragment "$2" --build-plan "$3" --decision "$FIX/phase1-matching-decision.md" \
      --requirements "$FIX/clarified-agent-requirements.yaml" --review "$4" --out "$TMP/neg.md" 2>&1); r=$?
  if [ "$r" -eq 2 ] && grep -q '"type": "input_error"' <<<"$o"; then ok "$1 (rc=2 input_error)"; else bad "$1 (rc=$r): $(echo "$o" | head -1)"; fi
}
sed '/^## 概述/,/^## 核心能力/d' "$FRAGMENT" > "$TMP/frag-missing-slot.md"
neg "缺判断段槽位（概述）→ input_error" "$TMP/frag-missing-slot.md" "$TMP/bp.md" "$FIX/phase2-review.md"
awk '{if ($0 ~ /^## 交付计划/) print "## 自造机械段\n\n| a | b |"; print}' "$FRAGMENT" > "$TMP/frag-unknown-slot.md"
neg "fragment 未知槽位（防机械段走私）→ input_error" "$TMP/frag-unknown-slot.md" "$TMP/bp.md" "$FIX/phase2-review.md"
sed 's/^- \[重大\] skills=0/- skills=0/' "$FRAGMENT" > "$TMP/frag-noprefix.md"
neg "风险条目缺等级前缀 → input_error" "$TMP/frag-noprefix.md" "$TMP/bp.md" "$FIX/phase2-review.md"
awk '/^## 已知风险（判断条目）/{f=1;next} /^## /{f=0} f&&/^- \[轻微\]/{next} 1' "$FRAGMENT" > "$TMP/frag-1risk.md"
neg "判断风险仅 1 条（<2 下限）→ input_error" "$TMP/frag-1risk.md" "$TMP/bp.md" "$FIX/phase2-review.md"
grep -v '^  path: ' "$TMP/bp.md" > "$TMP/bp-nofile.md"
neg "build-plan 无 file 块 → input_error" "$FRAGMENT" "$TMP/bp-nofile.md" "$FIX/phase2-review.md"
printf 'verdict: pass\n' > "$TMP/review-nofindings.md"
neg "phase2-review 缺 findings 行 → input_error" "$FRAGMENT" "$TMP/bp.md" "$TMP/review-nofindings.md"
neg "输入文件缺失 → input_error" "$TMP/absent-fragment.md" "$TMP/bp.md" "$FIX/phase2-review.md"
printf 'acceptance_criteria: [broken\n' > "$TMP/req-broken.yaml"
o=$(python3 "$RENDER" --fragment "$FRAGMENT" --build-plan "$TMP/bp.md" --decision "$FIX/phase1-matching-decision.md" --requirements "$TMP/req-broken.yaml" --review "$FIX/phase2-review.md" --out "$TMP/neg.md" 2>&1); r=$?
if [ "$r" -eq 2 ] && grep -q 'input_error' <<<"$o"; then ok "requirements yaml 畸形 → input_error"; else bad "requirements 畸形未拦截 (rc=$r)"; fi
out_fail=$(python3 "$RENDER" --fragment "$FRAGMENT" --build-plan "$TMP/bp.md" --decision "$FIX/phase1-matching-decision.md" --requirements "$FIX/clarified-agent-requirements.yaml" --review "$FIX/phase2-review.md" --out "$TMP/no-such-dir/h.md" 2>&1); r=$?
if [ "$r" -eq 2 ] && grep -q 'input_error' <<<"$out_fail"; then ok "--out 不可写 → input_error（不产出半成品）"; else bad "--out 失败未 fail-closed (rc=$r)"; fi

echo "══ 4. C8-2 位置无关 ══"
o=$(cd /tmp && python3 "$REPO_ROOT/$RENDER" --fragment "$REPO_ROOT/$FRAGMENT" --build-plan "$TMP/bp.md" \
    --decision "$REPO_ROOT/$FIX/phase1-matching-decision.md" \
    --requirements "$REPO_ROOT/$FIX/clarified-agent-requirements.yaml" \
    --review "$REPO_ROOT/$FIX/phase2-review.md" --out "$TMP/from-tmp.md"); r=$?
check "从仓外目录（/tmp）跑 → rc=0" 0 "$r"

echo "══ 5. build-planner.md Step 6 fragment 化（工具契约: 无 Bash/不调脚本）══"
step6=$(sed -n '/^### Step 6:/,/^### Step 7:/p' agents/build-planner.md)
echo "$step6" | grep -q 'render-human-review' && ok "Step 6 声明机械段移交组装器（引用 runner 名）" || bad "Step 6 未声明组装器移交"
echo "$step6" | grep -qE '^```bash|^[[:space:]]*(bash|python3|sh) ' && bad "Step 6 含脚本调用（工具契约无 Bash）" || ok "Step 6 无 Bash/脚本调用（脚本路径仅 prose 指针）"
echo "$step6" | grep -q 'human-review-fragment.md' && ok "Step 6 产出 fragment 契约" || bad "Step 6 未写 fragment 产出"
grep -q 'human-review-fragment.md' agents/build-planner.md && ok "frontmatter/正文 fragment 产出登记" || bad "缺 fragment 产出登记"

echo "══ 6. workflow.md step-3 校验+组装接线 ══"
wf=$(sed -n '/^## Step 3: 方案生成/,/^## Step 3c:/p' skills/harness-create/references/workflow.md)
echo "$wf" | grep -q 'validate-plan-v2.py' && ok "step-3 校验接线在案（T07② 对账）" || bad "step-3 缺校验接线"
echo "$wf" | grep -q 'render-human-review.py' && ok "step-3 组装接线在案（1.6③）" || bad "step-3 缺组装接线"
echo "$wf" | grep -q '\-\-fragment' && echo "$wf" | grep -q '\-\-review' \
  && ok "组装命令五输入齐（fragment/build-plan/decision/requirements/review）" || bad "组装命令输入不全"
echo "$wf" | grep -q 'exit 2' && ok "input_error → step-3 retry 回路声明" || bad "缺 input_error 回路声明"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
