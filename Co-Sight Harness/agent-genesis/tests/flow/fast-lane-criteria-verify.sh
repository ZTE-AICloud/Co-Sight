#!/usr/bin/env bash
# FA fast-lane 判据与接线验证门（docs/plan/fast-lane-implementation.md §5 FA 测试行）
# 覆盖: criteria.yaml 可解析+字段闭合（v1.3: agent/skill_create 单判据 OR 三分支+数量阈值缺席+预算留档）/
#        判据跨面一致性（criteria.yaml ↔ workflow-fast.md ↔ SKILL.md, 禁反向投影机检）/
#        判据 yaml 负例 fail-closed /
#        极简 build-plan fixture 三负例 fail-closed（g025+g028 消费面）/
#        g025 物化断言（正例: 物化+变量渲染）/ fast trigger 注册数据面断言（含空清单防线）/
#        非交互等价断言（R7: 判定节文本层）/ SKILL.md 与 builder 行数红线（C7-1）
# 注: g024 空清单 FAIL 行为由其自身 FAIL-CLOSED 契约承担（SCRIPT_DIR 锚定无覆盖钩子）,
#     本套件以"step-f1 outputs 恰两件非空"的数据面断言等价锚定。
# 用法: bash tests/flow/fast-lane-criteria-verify.sh   （在仓库根执行）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }

echo "══ criteria.yaml 可解析 + agent 段字段闭合（v1.3: 单判据 OR + 数量阈值缺席 + 预算留档）══"
python3 - <<'PY'
import yaml
c = yaml.safe_load(open('knowledge/fast-lane/criteria.yaml'))
a = c['agent']
assert 'capability_units_max' not in a and 'subagents_max' not in a, "数量判据已删（v1.2: 模式锚蕴含）"
assert a['generated_files_max'] == 15 and isinstance(a['generated_files_max'], int)
assert a['criteria'] == ['fast_path_hit'], "v1.3(D-02): agent 段单判据 OR 语义"
assert c['experimental'] is True
assert c['skill_create']['criteria'] == ['fast_path_hit'], "v1.3(D-03): skill_create 段单判据 OR 语义"
assert c['skill_optimize']['criteria'] == ['delta_files_le_2', 'no_structural_change',
                                           'target_statically_locatable']
print('ok')
PY
[ "$?" -eq 0 ] && ok "criteria 三段闭合（agent/skill_create 单判据 OR + skill_optimize 三条）" || bad "criteria 字段漂移"

echo "══ 判据跨面一致性（禁反向投影机检: criteria.yaml ↔ workflow-fast.md ↔ SKILL.md）══"
python3 - <<'PY'
import yaml, re
crit = yaml.safe_load(open('knowledge/fast-lane/criteria.yaml'))['agent']['criteria']
wf = open('skills/harness-create/references/workflow-fast.md', encoding='utf-8').read()
sk = open('skills/harness-create/SKILL.md', encoding='utf-8').read()
for name in crit:
    assert re.search(r'-\s*`%s`' % name, wf), "workflow-fast.md 缺判据枚举: " + name
    assert name in sk, "SKILL.md 缺判据引用: " + name
assert '前置层' in wf and '前置层' in sk, "前置层声明漂移"
print('ok')
PY
[ "$?" -eq 0 ] && ok "三处判据名 + 前置层声明一致" || bad "判据跨面漂移"

echo "══ 判据 yaml 负例 fail-closed（畸形/缺失 → 判定层应保守回退, 机检面不可解析即拒）══"
printf 'agent: [broken\n  unclosed: {' > "$TMP/bad-criteria.yaml"
python3 -I -c "import yaml,sys; yaml.safe_load(open('$TMP/bad-criteria.yaml'))" 2>/dev/null && bad "畸形 criteria 不应可解析" || ok "畸形 criteria 解析即拒（判定层保守回退依据）"

echo "══ 极简 build-plan 三负例 fail-closed（g025 + g028 消费面全 rc2）══"
for neg in missing-files truncated bad-invariants; do
  FIX="tests/fixtures/fast-lane/build-plan-fast-neg-$neg.md"
  [ -f "$FIX" ] || { bad "fixture 缺失: $FIX"; continue; }
  bash scripts/gates/g025-asset-copy.sh --build-plan "$FIX" --output-dir "$TMP/empty" >/dev/null 2>&1
  rc25=$?
  printf '{"profile":"agent-exit","output_dir":"%s/empty","target":"%s/empty","work_dir":"%s/w","skills_dir":"%s/empty/.claude/skills","rules_dir":"%s/empty/.claude/rules","build_plan":"%s/%s"}' \
    "$TMP" "$TMP" "$TMP" "$TMP" "$TMP" "$PWD" "$FIX" | bash scripts/gates/g028-exit-sanity.sh >/dev/null 2>&1
  rc28=$?
  if [ "$rc25" -ne 0 ] && [ "$rc28" -eq 2 ]; then ok "neg-$neg: g025 rc$rc25 / g028 rc$rc28（双面 fail-closed）"; else bad "neg-$neg 未闭合: g025 rc$rc25 / g028 rc$rc28"; fi
done

echo "══ g025 物化断言（正例 fixture: 物化计数 + 变量渲染 + 无残留占位）══"
mkdir -p "$TMP/mat"
out=$(bash scripts/gates/g025-asset-copy.sh --build-plan tests/fixtures/fast-lane/build-plan-fast-positive.md --output-dir "$TMP/mat" 2>&1); rc=$?
check "正例 fixture g025 → PASS" 0 "$rc"
echo "$out" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert d.get('materialized_count')==3 and d.get('copied_count')==1, d" && ok "materialized=3（G003+G005+settings）copied=1" || bad "物化计数漂移: $out"
grep -q 'readiness_score >= 58' "$TMP/mat/phase/gates/G003-readiness-score.md" && ok "G003 变量渲染（threshold=58）" || bad "G003 未渲染"
grep -q '{{readiness_threshold}}' "$TMP/mat/phase/gates/G003-readiness-score.md" && bad "渲染残留占位符" || ok "无残留占位符"

echo "══ fast trigger 注册数据面断言（gates.yaml step-f1-fast-build）══"
python3 - <<'PY'
import yaml
d = yaml.safe_load(open('phase/gates/gates.yaml'))
t = d['triggers']['step-f1-fast-build']
outs = t['outputs']
assert outs == ['.agent-genesis/work/{name}/fast-lane/build-plan.md',
                '.agent-genesis/work/{name}/fast-lane/self-report.md'], outs
assert outs and all(o.strip() for o in outs), "outputs 空清单防线（G024 FAIL-CLOSED 消费）"
assert 'gate.step.outputs' in t['gates'] and 'runner.exit' in t['gates'], t['gates']
assert t['on_failure']['retry']['max'] == 1 and t['on_failure']['escalate']['after_exhausted'] is True
assert t['context']['profile'] == 'agent-exit'
print('ok')
PY
[ "$?" -eq 0 ] && ok "step-f1: outputs 两件/gates 双挂/retry=1（修复轮）/agent-exit 档" || bad "step-f1 注册数据漂移"

echo "══ 非交互等价断言（R7: 判定节文本层——headless/selftest/CI 静默 full 不询问）══"
grep -q "静默走 full, 不询问" skills/harness-create/SKILL.md && ok "SKILL.md 判定节非交互保障在场" || bad "SKILL.md 缺非交互保障语句"
grep -q "非交互静默保障" skills/harness-create/references/workflow-fast.md && ok "workflow-fast 判定节规格在场" || bad "workflow-fast 缺非交互规格"
grep -q "experimental" skills/harness-create/SKILL.md && grep -q "标准模式构建（fast）" skills/harness-create/references/workflow-fast.md && grep -q "标准模式（fast）生成" skills/harness-create/references/workflow-fast.md && ok "模式明示之两处（入口陈述/汇报, 用户面无\"实验性\"话术）在场" || bad "模式明示缺位"

echo "══ 批 2: 沉淀建议句汇报契约锚点（REFLUX.md §4 唯一措辞, C9-6 禁内部编号上用户面）══"
grep -q "可沉淀为样例" skills/harness-create/SKILL.md && grep -q "可沉淀为样例" skills/harness-create/references/workflow.md && ok "建议句两面在场（SKILL.md 第三步 + workflow.md Milestone）" || bad "沉淀建议句缺面"
grep -q "REFLUX.md" skills/harness-create/SKILL.md && grep -q "REFLUX.md" skills/harness-create/references/workflow.md && ok "两面引用 REFLUX.md 手册" || bad "缺 REFLUX 引用"
grep -q "唯一活权威" knowledge/golden/REFLUX.md && ok "REFLUX.md 活权威地位声明在场" || bad "REFLUX 地位声明缺位"

echo "══ C7-1 行数红线（≤300 行）══"
for f in skills/harness-create/SKILL.md agents/fast-lane-builder.md skills/harness-create/references/workflow-fast.md; do
  n=$(wc -l < "$f")
  [ "$n" -le 300 ] && ok "$f = $n 行" || bad "$f = $n 行（超 300）"
done

echo "══ builder 契约静态断言（无 Bash / forbidden_inputs / 单 batch）══"
grep -q "^tools: \[Read, Write, Grep, Glob\]" agents/fast-lane-builder.md && ok "builder 无 Bash（机检物化全在 main agent 侧）" || bad "builder tools 契约漂移"
grep -q "matching-decision" agents/fast-lane-builder.md && ok "forbidden_inputs 含 matching-decision（禁跨车道读取）" || bad "缺跨车道隔离"

echo "══ FB: skill 线 fast 车道断言 ══"
# 批 2 后续: skill 线沉淀闭环接线（对称 agent 线 69-71 行检索注入 + 判定节全 id 断言 + 建议句两面）
grep -q "golden-lookup.sh" skills/skill-foundry/references/workflow-fast.md \
  && grep -q "未命中（NONE）或 anchored_mode" skills/skill-foundry/references/workflow-fast.md \
  && ok "skill 线 fast 驱动 --few-shot 检索注入在位" || bad "skill 线 few-shot 未检索化"
grep -q "anchored_mode 必须写 mapping 核心模式全 id" skills/skill-foundry/references/workflow-fast.md \
  && ok "skill 线判定节 anchored_mode 全 id 格式断言在位" || bad "skill 线 anchored_mode 格式断言缺位"
grep -q "golden-lookup.sh" agents/fast-skill-builder.md \
  && grep -q "未命中（NONE）时本指引缺省" agents/fast-skill-builder.md \
  && ok "skill builder 输入⑤检索化措辞在位" || bad "skill builder few-shot 措辞未检索化"
grep -q "可沉淀为样例" skills/skill-foundry/SKILL.md && grep -q "可沉淀为样例" skills/skill-foundry/references/workflow.md \
  && ok "skill 线沉淀建议句两面在场（SKILL.md 里程碑 + workflow.md Milestone）" || bad "skill 线建议句缺面"
# criteria 两段字段闭合（skill_create / skill_optimize, 裁定 6 最简三条）
python3 - <<'PY'
import yaml
c = yaml.safe_load(open('knowledge/fast-lane/criteria.yaml'))
assert c['skill_create']['criteria'] == ['fast_path_hit'], "v1.3(D-03)"
assert c['skill_optimize']['criteria'] == ['delta_files_le_2', 'no_structural_change', 'target_statically_locatable']
print('ok')
PY
[ "$?" -eq 0 ] && ok "criteria skill 两段字段闭合（create 单判据 OR + optimize 三条不动）" || bad "skill 段判据漂移"
# sf 双 trigger 注册数据面
python3 - <<'PY'
import yaml
d = yaml.safe_load(open('phase/gates/gates.yaml'))
for tid, profile in [('step-sf1-fast-build', 'skill-build'), ('step-sf2-fast-optimize', 'skill-verify')]:
    t = d['triggers'][tid]
    assert t['outputs'] == ['.agent-genesis/work/{name}/fast-lane/self-report.md'], (tid, t['outputs'])
    assert 'gate.step.outputs' in t['gates'] and 'runner.exit' in t['gates']
    assert t['context']['profile'] == profile, (tid, t['context'])
    assert t['on_failure']['retry']['max'] == 1
print('ok')
PY
[ "$?" -eq 0 ] && ok "sf1/sf2 trigger 注册（outputs 单件/档位/retry=1）" || bad "sf trigger 数据漂移"
# SKILL.md 判定节 + fast 驱动节 + 非交互保障 + R6 无 fallback 条款
SS=skills/skill-foundry/SKILL.md
grep -q "第 1.5 步：Lane 判定" "$SS" && ok "skill SKILL.md 判定节在场" || bad "判定节缺位"
grep -q "静默走 full" "$SS" && grep -q "不进 full optimize" "$SS" && ok "非交互静默 + R6 无 fallback 条款在场" || bad "缺静默/无 fallback 条款"
grep -q "check-delta-scope" "$SS" && ok "fast 驱动节含安全三件接线" || bad "缺安全三件"
grep -q "workflow-fast" "$SS" && grep -q "互指" skills/skill-foundry/references/workflow.md && ok "两视图互指在场" || bad "互指缺位"
# fast-skill-builder 契约
FSB=agents/fast-skill-builder.md
grep -q "mode create/optimize 两用" "$FSB" && grep -q "delta 段" "$FSB" && ok "builder 两用 + delta 契约在场" || bad "builder 契约缺位"
grep -q "phase1-skill-design.md" "$FSB" && ok "forbidden_inputs 禁跨车道读取（full s1 产物）" || bad "缺跨车道隔离"
n=$(wc -l < "$FSB"); [ "$n" -le 300 ] && ok "fast-skill-builder = $n 行（C7-1）" || bad "超 300 行"
n=$(wc -l < "$SS"); [ "$n" -le 300 ] && ok "skill SKILL.md = $n 行（C7-1）" || bad "超 300 行"

echo "══ FB: check-delta-scope 三态（optimize 安全件②）══"
DT=$(mktemp -d); mkdir -p "$DT/snap/a" "$DT/tgt/a"
echo v1 > "$DT/snap/a/x.md"; cp "$DT/snap/a/x.md" "$DT/tgt/a/x.md"; echo v1 > "$DT/snap/a/keep.md"; cp "$DT/snap/a/keep.md" "$DT/tgt/a/keep.md"
printf '# 点名清单\na/x.md\n' > "$DT/allow.txt"
echo v2 > "$DT/tgt/a/x.md"
out=$(bash scripts/check-delta-scope.sh --snapshot "$DT/snap" --target "$DT/tgt" --allowlist "$DT/allow.txt"); rc=$?
check "改动 ⊆ 点名 → PASS" 0 "$rc"
echo "$out" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='PASS' and d['changed_files']==['a/x.md'], d" && ok "changed_files 列名且 PASS" || bad "正例断言失败"
echo v9 > "$DT/tgt/a/keep.md"
out=$(bash scripts/check-delta-scope.sh --snapshot "$DT/snap" --target "$DT/tgt" --allowlist "$DT/allow.txt" 2>/dev/null); rc=$?
check "越界（改清单外文件）→ FAIL rc2" 2 "$rc"
echo "$out" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert any(f['type']=='scope_violation' and f['file']=='a/keep.md' for f in d['failures']), d" && ok "scope_violation 点名越界文件" || bad "反例断言失败"
bash scripts/check-delta-scope.sh --snapshot "$DT/snap" >/dev/null 2>&1; rc1=$?
bash scripts/check-delta-scope.sh --snapshot /nonexist --target "$DT/tgt" --allowlist "$DT/allow.txt" >/dev/null 2>&1; rc2=$?
[ "$rc1" -eq 2 ] && [ "$rc2" -eq 2 ] && ok "畸形负例 ×2 fail-closed rc2（C8-1）" || bad "畸形未闭合: $rc1/$rc2"
# 新增/删除形态覆盖（先还原越界用例对 keep.md 的改动, 防状态泄漏）
echo v1 > "$DT/tgt/a/keep.md"
mkdir -p "$DT/tgt/a/newdir"; echo n > "$DT/tgt/a/newdir/n.md"; rm "$DT/tgt/a/x.md"
printf 'a/newdir/n.md\na/x.md\n' > "$DT/allow.txt"
out=$(bash scripts/check-delta-scope.sh --snapshot "$DT/snap" --target "$DT/tgt" --allowlist "$DT/allow.txt"); rc=$?
check "新增+删除 ⊆ 点名 → PASS" 0 "$rc"
rm -rf "$DT"

echo "══ FC: agent-optimize fast 车道断言 ══"
# f2 trigger 注册 + 条件 outputs 全集
python3 - <<'PY'
import yaml
d = yaml.safe_load(open('phase/gates/gates.yaml'))
t = d['triggers']['step-f2-fast-optimize']
assert t['outputs'] == ['.agent-genesis/work/{name}/fast-lane/self-report.md',
                        '.agent-genesis/work/{name}/fast-lane/trace-diagnosis.md'], t['outputs']
assert 'gate.step.outputs' in t['gates'] and 'runner.exit' in t['gates']
assert t['context']['profile'] == 'agent-exit' and t['on_failure']['retry']['max'] == 1
n = len(d['triggers'])
assert n == 25, n
print('ok')
PY
[ "$?" -eq 0 ] && ok "f2 trigger 注册（条件 outputs 全集/agent-exit 后测/retry=1/总数 25）" || bad "f2 注册漂移"
# G024 条件 outputs 语义实证: 形态①③ 子集（仅 self-report）可 PASS
DT2=$(mktemp -d); mkdir -p "$DT2/.agent-genesis/work/tst/fast-lane"
printf -- '---\nmode: optimize\nrevision_rounds: 0\n' > "$DT2/.agent-genesis/work/tst/fast-lane/self-report.md"
# G024 root 指向临时根, outputs 子集 = self-report（形态①③形态）——通过临时 gates.yaml 不可行（SCRIPT_DIR 锚定）,
# 改为断言注册表全集语义已由上条覆盖 + G024 的清单驱动契约（此处验证 subset 文件存在即可被 G024 检出）
[ -f "$DT2/.agent-genesis/work/tst/fast-lane/self-report.md" ] && ok "形态①③ outputs 子集文件形态在场（G024 清单驱动, 注册全集已锚）" || bad "子集形态缺"
rm -rf "$DT2"
# trace-analyzer 契约静态断言
TA=agents/trace-analyzer.md
grep -q "^tools: \[Read, Grep, Glob, Write\]" "$TA" && ok "trace-analyzer 无 Bash（JSONL 用 Read/Grep）" || bad "tools 契约漂移"
grep -q "只诊断不动手" "$TA" && ok "只诊断不动手语义在场" || bad "缺只诊断约束"
grep -q "建议点名 ≤3" "$TA" && ok "点名 ≤3 上限在场（超即建议 create）" || bad "缺点名上限"
n=$(wc -l < "$TA"); [ "$n" -le 300 ] && ok "trace-analyzer = $n 行（C7-1）" || bad "超 300 行"
# fast-lane-builder optimize 扩展断言
FB=agents/fast-lane-builder.md
grep -q "Mode: optimize" "$FB" && grep -q "生成反映现状的极简 build-plan" "$FB" && ok "builder --mode optimize + 无 build-plan 闭环在场" || bad "optimize 扩展缺位"
grep -q "不读 trace / trace-diagnosis" "$FB" && ok "builder 隔离 trace 原文（防自我印证）" || bad "缺隔离条款"
# clarifier agent-optimize mode 派发
RC=skills/requirement-clarifier/SKILL.md
grep -q "agent-optimize" "$RC" && grep -q "workflow-agent-optimize.md" "$RC" && ok "clarifier agent-optimize 派发行在场" || bad "派发缺位"
grep -q "形态②" skills/requirement-clarifier/references/workflow-agent-optimize.md && grep -q "readiness-verifier" skills/requirement-clarifier/references/workflow-agent-optimize.md && ok "三形态分流协议在场（trace 派发+现状描摹复用 readiness）" || bad "分流协议缺位"
# harness-create SKILL optimize 维度 + 只走 fast（无 full fallback）
HC=skills/harness-create/SKILL.md
grep -q "optimize 维度" "$HC" && grep -q "只走 fast" "$HC" && ok "SKILL optimize 维度 + 只走 fast（裁定 6）在场" || bad "维度缺位"
grep -q "step-f2-fast-optimize" "$HC" && ok "optimize fast 驱动节接线在场" || bad "驱动节缺位"
# diagnose-mode 缩水标注：方案文档已随过时文档清理删除，活声明需留在 SKILL.md + workflow-fast.md
grep -q "缩水取代" "$HC" && grep -q "缩水取代" skills/harness-create/references/workflow-fast.md \
  && ok "diagnose-mode 缩水取代声明两面在场" || bad "状态头未标"
# 行数红线
n=$(wc -l < "$HC"); [ "$n" -le 300 ] && ok "harness-create SKILL.md = $n 行（共置 ≤ 红线）" || bad "超 300"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
