#!/usr/bin/env bash
# golden-lookup 检索接线验证门（docs/plan/golden-asset-pool-plan.md §4 G1 验证行）
# 覆盖: 单命中 argv/stdin 双通道 / 多命中 acceptance_items_max 裁决（含再平词典序确定性）/
#        未命中 fail-closed（NONE, 键外 id / 缩写 / 空输入 / INDEX 缺失→NONE 不阻塞）/
#        检索键域断言（v1.2 批 3 参数化: ⊆ mapping 核心列 数据驱动 且 ≤20 硬顶; 拓扑模式非键）/
#        消费面接线断言（workflow-fast.md 判定节全 id 格式断言 + 步骤 2 检索注入措辞;
#        fast-lane-builder.md 输入④ 无 fixtures 硬编码残留）
# 用法: bash tests/flow/golden-lookup-verify.sh   （在仓库根执行）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
expect_out() { # expect_out <说明> <期望串> <实际串>
  if [[ "$3" == "$2" ]]; then ok "$1"; else bad "$1（期望 '$2', 实际 '$3'）"; fi
}

LOOKUP="bash scripts/golden-lookup.sh"

echo "══ 单命中（IH3-Plan-Approval → plan-approval 包; W2-Router/W3-MapReduce 多命中, 见下节）══"
out=$($LOOKUP IH3-Plan-Approval); expect_out "argv 命中" "knowledge/golden/plan-approval" "$out"
out=$(echo '{"mode_id":"IH3-Plan-Approval"}' | $LOOKUP); expect_out "stdin JSON 命中" "knowledge/golden/plan-approval" "$out"
out=$(printf 'IH3-Plan-Approval' | $LOOKUP); expect_out "stdin 裸串命中" "knowledge/golden/plan-approval" "$out"

echo "══ 真池多命中（W2-Router: 三包同 4 条 → 平票词典序 command-router 在前; 裁决唯一权威 = multi_hit_rule）══"
out=$($LOOKUP W2-Router); expect_out "真池裁决" "knowledge/golden/command-router" "$out"

echo "══ v1.2 批 2 新命中（W3 双命中平票词典序 browser 在前; K3/DP1/WF5 首次有包单命中）══"
out=$($LOOKUP W3-MapReduce); expect_out "W3 裁决" "knowledge/golden/browser-automation-suite" "$out"
out=$($LOOKUP K3-KB-Backed); expect_out "K3 单命中" "knowledge/golden/vector-kb-skill" "$out"
out=$($LOOKUP DP1-Traceable-Lineage); expect_out "DP1 单命中" "knowledge/golden/lineage-context-skill" "$out"
out=$($LOOKUP WF5-Contract-Lock); expect_out "WF5 单命中" "knowledge/golden/leader-worker-orchestrator" "$out"

echo "══ 真池 skill 线命中（G3: IV1-Progress-Streaming → skill-gate-report, 自有产物锚验证跨线通用）══"
out=$($LOOKUP IV1-Progress-Streaming); expect_out "G3 追加包命中" "knowledge/golden/skill-gate-report" "$out"

echo "══ 未命中 fail-closed（全部字面 NONE, 退出码恒 0 不阻塞构建）══"
out=$($LOOKUP WF4-Multi-Agent-Debate); expect_out "键域内未入库 id（WF4 现无包, 批 2 后 W3/K3/DP1/WF5 均已入库）" "NONE" "$out"
out=$($LOOKUP W1-Chain-Topology); expect_out "拓扑模式非检索键" "NONE" "$out"
out=$($LOOKUP W2); expect_out "缩写陷阱（W3 vs W3-MapReduce 实测坑）" "NONE" "$out"
out=$($LOOKUP "" < /dev/null); expect_out "空 argv" "NONE" "$out"
out=$(echo '{}' | $LOOKUP); expect_out "空 stdin JSON" "NONE" "$out"
out=$($LOOKUP < /dev/null); expect_out "无参无 stdin" "NONE" "$out"
out=$($LOOKUP "W2-Router; rm -rf /"); expect_out "注入串不在键域" "NONE" "$out"

echo "══ 多命中裁决（multi_hit_rule = acceptance_items_max）══"
mkdir -p "$TMP/multi/golden"
cat > "$TMP/multi/INDEX.yaml" <<'IDX'
lookup:
  primary_key: mode_id
  key_domain:
    - W2-Router
    - WF4-Multi-Agent-Debate
  multi_hit_rule: acceptance_items_max
  miss_behavior: NONE_fail_closed
pool:
  alpha:  {mode_id: W2-Router, line: skill}
  beta:   {mode_id: W2-Router, line: skill}
  gamma:  {mode_id: W2-Router, line: skill}
IDX
# alpha: 1 条 acceptance / beta: 3 条 / gamma: 3 条（再平 → 词典序 beta 胜）
for tag in alpha beta gamma; do
  n=$([[ "$tag" == "alpha" ]] && echo 1 || echo 3)
  { for i in $(seq 1 "$n"); do echo "  - 验收要点 $i"; done; } > "/tmp/acc-$tag.txt"
  mkdir -p "$TMP/multi/golden/$tag"
  cat > "$TMP/multi/golden/$tag/manifest.yaml" <<MAN
task_tag: $tag
acceptance:
$(cat /tmp/acc-$tag.txt)
MAN
done
# 用插件内脚本 + 临时 INDEX: 复制脚本到 TMP 并替换 INDEX 路径
cp scripts/golden-lookup.sh "$TMP/golden-lookup-multi.sh"
sed -i "s|INDEX=\"\$PLUGIN_ROOT/knowledge/golden/INDEX.yaml\"|INDEX=\"$TMP/multi/INDEX.yaml\"|" "$TMP/golden-lookup-multi.sh"
chmod +x "$TMP/golden-lookup-multi.sh"
out=$(bash "$TMP/golden-lookup-multi.sh" W2-Router)
expect_out "条数多者胜（beta 3 > alpha 1）" "knowledge/golden/beta" "$out"
# gamma 改 2 条 → beta 仍胜; beta 改 1 条 → gamma 3 条胜
sed -i 's|  - 验收要点 2||; s|  - 验收要点 3||' "$TMP/multi/golden/beta/manifest.yaml"
out=$(bash "$TMP/golden-lookup-multi.sh" W2-Router)
expect_out "改条后再裁决（gamma 3 > beta 1）" "knowledge/golden/gamma" "$out"

echo "══ INDEX 缺失 fail-closed（NONE 不阻塞, 禁静默 fallback）══"
cp scripts/golden-lookup.sh "$TMP/golden-lookup-noindex.sh"
sed -i "s|INDEX=\"\$PLUGIN_ROOT/knowledge/golden/INDEX.yaml\"|INDEX=\"$TMP/no-such-INDEX.yaml\"|" "$TMP/golden-lookup-noindex.sh"
chmod +x "$TMP/golden-lookup-noindex.sh"
out=$(bash "$TMP/golden-lookup-noindex.sh" W2-Router); expect_out "INDEX 缺失 → NONE" "NONE" "$out"

echo "══ 检索键域断言（v1.2 批 3 参数化: key_domain ⊆ mapping 核心列 且 ≤20 硬顶; 拓扑模式非键）══"
python3 - <<'PY'
import re
idx = open('knowledge/golden/INDEX.yaml', encoding='utf-8').read()
m = re.search(r"key_domain:(.*?)(?=\n  \w|\Z)", idx, re.S)
keys = re.findall(r'-\s+([A-Za-z0-9_-]+)', m.group(1))
# 核心列从 mapping 数据驱动解析（末列 ASCII 模式 id; 预置范式表末列为中文, 天然排除）
mp = open('knowledge/agent-creation/task-mode-pattern-mapping.md', encoding='utf-8').read()
core_ids = set(re.findall(r'\|\s*([A-Z]{1,3}\d-[A-Za-z-]+)\s*\|\s*\n', mp, re.M))
assert core_ids, "mapping 核心列解析为空（表格式漂移）"
assert len(keys) == len(set(keys)), "key_domain 含重复项"
assert set(keys) <= core_ids, f"key_domain 越出 mapping 核心列: {set(keys)-core_ids}"
assert len(keys) <= 20, f"key_domain 超硬顶 20: {len(keys)}（REFLUX.md §5）"
assert 'W2-Router' in keys, "W2-Router 须在键域"
assert 'W2' not in keys and 'W3' not in keys, "缩写不得入键域"
for topo in ('W1-Chain-Topology', 'W4-Parallel-Mesh', 'DT2-Hierarchical-Decompose'):
    assert topo not in keys, f"拓扑模式 {topo} 非检索键"
assert 'multi_hit_rule: acceptance_items_max' in idx
assert 'miss_behavior: NONE_fail_closed' in idx
print('ok')
PY
[[ $? -eq 0 ]] && ok "key_domain 11 核心 + 裁决规则 + miss 语义闭合" || bad "INDEX.yaml 键域漂移"

echo "══ 消费面接线断言（fast 车道 R15: 非交互等价复验的数据面）══"
grep -q "anchored_mode 必须写 mapping" skills/harness-create/references/workflow-fast.md \
  && grep -q "非缩写 \`W2\`" skills/harness-create/references/workflow-fast.md \
  && ok "workflow-fast.md 判定节全 id 格式断言在位" || bad "判定节全 id 断言缺失"
grep -q "golden-lookup.sh" skills/harness-create/references/workflow-fast.md \
  && grep -q "未命中（NONE）跳过本指引" skills/harness-create/references/workflow-fast.md \
  && ok "workflow-fast.md 步骤 2 检索注入措辞在位" || bad "步骤 2 检索注入措辞缺失"
! grep -q "tests/fixtures/pr-security-reviewer" skills/harness-create/references/workflow-fast.md \
  && ok "workflow-fast.md fixtures 硬编码已清" || bad "workflow-fast.md 仍残留 fixtures 硬编码"
grep -q "golden-lookup.sh" agents/fast-lane-builder.md \
  && ! grep -q "tests/fixtures" agents/fast-lane-builder.md \
  && ok "builder 输入④检索化 + 无 fixtures 硬编码" || bad "builder 输入④未检索化或残留硬编码"
grep -q "golden-lookup.sh" skills/skill-foundry/references/workflow-fast.md \
  && grep -q "未命中（NONE）或 anchored_mode" skills/skill-foundry/references/workflow-fast.md \
  && ok "skill 线 fast 驱动检索注入措辞在位（对称 agent 线）" || bad "skill 线检索注入措辞缺失"
grep -q "golden-lookup.sh" agents/fast-skill-builder.md \
  && ! grep -q "tests/fixtures" agents/fast-skill-builder.md \
  && ok "skill builder 输入⑤检索化 + 无 fixtures 硬编码" || bad "skill builder 输入⑤未检索化或残留硬编码"
[[ -x scripts/golden-lookup.sh ]] && ok "golden-lookup.sh 可执行位" || bad "golden-lookup.sh 缺可执行位"

echo ""
echo "═══ golden-lookup-verify: PASS=$PASS FAIL=$FAIL ═══"
[[ $FAIL -eq 0 ]]
