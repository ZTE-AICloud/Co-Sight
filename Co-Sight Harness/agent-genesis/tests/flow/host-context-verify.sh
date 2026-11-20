#!/usr/bin/env bash
# tests/flow/host-context-verify.sh
# host-context 方案落地静态一致性核验（V2/V3 静态面 + 红线核验; 单元/门禁行为面
# 由 tests/unit/test-env-probe-host-context.sh 与 test-g028-host-extend.sh /
# test-delta-scope-and-g030.sh 覆盖, 本脚本尾部串联）
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PASS=0; FAIL=0
has() { # has <label> <file> <fixed-string>
  if grep -qF "$3" "$2" 2>/dev/null; then PASS=$((PASS+1)); echo "PASS  $1"; else FAIL=$((FAIL+1)); echo "FAIL  $1 — $2 缺: $3"; fi
}

echo "== 澄清器 =="
has "SKILL.md 阶段1 宿主语境判定" skills/requirement-clarifier/SKILL.md "### 宿主语境判定"
has "SKILL.md 语义判定红线" skills/requirement-clarifier/SKILL.md "语义判定只产建议"
has "SKILL.md 抑制缺省" skills/requirement-clarifier/SKILL.md "suppressed_by: non_interactive"
has "workflow-agent 三段指引" skills/requirement-clarifier/references/workflow-agent.md "宿主语境三段"
has "workflow-skill 三段指引" skills/requirement-clarifier/references/workflow-skill.md "宿主语境三段"
for s in clarified-agent clarified-skill; do
  f="skills/requirement-clarifier/references/schemas/$s.schema.yaml"
  has "$s schema intent 段" "$f" "host_extend, modify_existing, explicit_create"
  has "$s schema project_context 段" "$f" "suppressed_by"
done

echo "== agent 线入口 =="
has "harness-create 语境路由节" skills/harness-create/SKILL.md "## 语境路由"
has "harness-create 判定即执行" skills/harness-create/SKILL.md "判定即执行, 不调 AskUserQuestion"
has "harness-create route-decision 留痕" skills/harness-create/SKILL.md "route-decision.yaml"
has "harness-create optimize 形态④" skills/harness-create/SKILL.md "形态④宿主增补"
has "workflow-fast 形态④行" skills/harness-create/references/workflow-fast.md "④ 宿主增补"
has "workflow-fast 只新增红线" skills/harness-create/references/workflow-fast.md "deletions=0 且 modifications=∅"
has "workflow-fast G028 豁免键" skills/harness-create/references/workflow-fast.md '"host_extend": true'

echo "== skill 线入口 =="
has "skill-foundry mode 表形态④" skills/skill-foundry/SKILL.md "形态④宿主增补"
has "skill-foundry 语境路由节" skills/skill-foundry/SKILL.md "## 语境路由"
has "skill-foundry 判据映射" skills/skill-foundry/SKILL.md "探针已验 host_project.in_project"
has "skill workflow-fast 形态④约束" skills/skill-foundry/references/workflow-fast.md "只新增红线"

echo "== builder 与下游 =="
has "fast-lane-builder 形态④" agents/fast-lane-builder.md "形态④宿主增补"
has "fast-lane-builder 极简build-plan声明新增" agents/fast-lane-builder.md "必须声明全部新增文件含宿主落点路径"
has "fast-skill-builder 形态④" agents/fast-skill-builder.md "形态④宿主增补"
has "pattern-matcher project_context" agents/pattern-matcher.md "宿主已有形态优先"
has "build-planner 追溯" agents/build-planner.md "derived_from"
has "agent-executor 约束同级" agents/agent-executor.md "视同"
has "skill-planner project_context" agents/skill-planner.md "宿主项目画像"

echo "== 门禁与脚本 =="
has "env-probe host_project 探测" scripts/env-probe.sh "detect_kind"
has "env-probe 抑制开关" scripts/env-probe.sh "AG_SUPPRESS_HOST_CONTEXT"
has "env-probe fail-open 注释" scripts/env-probe.sh "fail-open"
has "g028 豁免键实现" scripts/gates/g028-exit-sanity.sh "host_extend"
has "g028 豁免≠跳检注释" scripts/gates/g028-exit-sanity.sh "豁免 ≠ 跳检"
has "check-delta-scope 未改动(新增语义既有)" scripts/check-delta-scope.sh "新增"

echo "== 约定与零波及红线 =="
has "00-conventions route-decision 登记" phase/00-conventions.md "route-decision.yaml"
if ! grep -q "host_extend" phase/gates/gates.yaml; then PASS=$((PASS+1)); echo "PASS  gates.yaml 无 host_extend 键（零改动红线）"; else FAIL=$((FAIL+1)); echo "FAIL  gates.yaml 不应含 host_extend"; fi
if ! grep -q "host" hooks/hooks.json; then PASS=$((PASS+1)); echo "PASS  hooks.json 零改动红线"; else FAIL=$((FAIL+1)); echo "FAIL  hooks.json 应零改动"; fi

echo "== 行为面测试串联（V1 + V4）=="
for t in tests/unit/test-env-probe-host-context.sh tests/unit/test-g028-host-extend.sh tests/unit/test-delta-scope-and-g030.sh; do
  if bash "$t" > /tmp/hc-$(basename "$t").log 2>&1; then PASS=$((PASS+1)); echo "PASS  $t"; else FAIL=$((FAIL+1)); echo "FAIL  $t（见 /tmp/hc-$(basename "$t").log）"; fi
done

echo "----"
echo "host-context 静态+行为核验: PASS=$PASS FAIL=$FAIL"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 2)
