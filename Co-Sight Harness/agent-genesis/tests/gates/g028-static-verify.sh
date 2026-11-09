#!/usr/bin/env bash
# G028 验证门——module.agent.static（步 1.2）+ module.skill.static（步 2.1: SK-S1/S2）
# 覆盖: 新模块正/反/畸形三态; execution-report 裁撤形态断言（executor v2: 只写不检,
# 存在性归 G024 兜底）; 畸形输入负例 ≥3（C8-1/C8-4 fail-closed）; C8-2 仓外运行;
# 出口减负两层化正/反例（部分形态 PASS / 缺 CLAUDE.md FAIL——清单复检已撤出, 2026-10-16）
# 用法: bash tests/gates/g028-static-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
G028="$REPO_ROOT/scripts/gates/g028-exit-sanity.sh"
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

# ── 合成正例产物（全形态超集——合法超集, 过地板 + 方案保真两层即可; 非标准清单强检。
#    2026-10-16 出口减负: required_files 全清单复检已从 g028 撤出, 全形态仍保留以
#    覆盖引用闭合/agent_static 等扫描面）──
build_product() { # build_product <out_dir> <work_dir> [with_progress:1|0]
  local OUT="$1" WORK="$2" WITH_PROGRESS="${3:-1}"
  mkdir -p "$OUT/phase/02-workflows" "$OUT/phase/gates" "$OUT/phase/review" \
           "$OUT/.claude/skills/pr-review/scripts" "$OUT/.claude/agents" \
           "$OUT/.claude/rules" "$OUT/evaluation"
  cat > "$OUT/proposal-spec.md" <<'EOF'
# 构建方案

## 概述
对 pull request 做安全维度扫描。

## 核心能力
- 密钥硬编码扫描
- 注入特征扫描
- 独立复核

## 交付计划
产物落 .claude/agents 与 phase/ 目录。

## 风险
- 扫描规则误报
- 大 diff 超时

## 审批要点
- spot_check: 抽查 3 条规则
- yes_no: 是否启用强制阻断
EOF
  cat > "$OUT/CLAUDE.md" <<'EOF'
# pr-security-scan

安全扫描 harness。总览与调度说明。

## 结构
- workflow: phase/02-workflows/main-flow.md
- 审查: phase/review/matching-decision-review.md
- 门禁: phase/gates/G003-readiness-score.md 与 phase/gates/G005-no-placeholders.md
- 技能: .claude/skills/pr-review/SKILL.md
- 规则: .claude/rules/coding-style.md
EOF
  cat > "$OUT/phase/02-workflows/main-flow.md" <<'EOF'
# 主流程

步骤 1: 调度 .claude/skills/pr-review/SKILL.md 执行扫描。
步骤 2: 汇总结果写入报告。
EOF
  printf '# G003 readiness\n\nreadiness_score >= 58 时放行。\n' > "$OUT/phase/gates/G003-readiness-score.md"
  printf '# G005 no placeholders\n\n占位符计数为零时放行。\n' > "$OUT/phase/gates/G005-no-placeholders.md"
  cat > "$OUT/phase/gates/gates.yaml" <<'EOF'
gates:
  - id: G003
    type: condition_check
  - id: G005
    type: condition_check
EOF
  printf '# 审查规则\n\n逐条核对 findings 证据。\n' > "$OUT/phase/review/matching-decision-review.md"
  cat > "$OUT/.claude/skills/pr-review/SKILL.md" <<'EOF'
---
name: pr-review
description: "对 pull request diff 做安全维度扫描，输出 findings 清单。"
---
# PR Review

用法: bash scripts/run.sh <diff-file>，输出 findings。
EOF
  printf '#!/bin/bash\necho "scan"\n' > "$OUT/.claude/skills/pr-review/scripts/run.sh"
  chmod +x "$OUT/.claude/skills/pr-review/scripts/run.sh"
  cat > "$OUT/.claude/agents/scan-worker.md" <<'EOF'
---
name: scan-worker
description: "按规则清单扫描 diff，产出 scan-findings.json。"
tools: [Read, Grep, Write]
forbidden_inputs:
  - reviewed-findings.json
---
# Scan Worker

只读扫描，不读复核者结论。
EOF
  for r in anti-patterns durable-context skill-routing coding-style security testing review-discipline; do
    printf '> This file extends common/%s.md\n\n# %s\n' "$r" "$r" > "$OUT/.claude/rules/$r.md"
  done
  printf '{}\n' > "$OUT/.claude/settings.json"
  printf '# 通过标准\n\n扫描类结果为零 critical 即通过。\n' > "$OUT/evaluation/pass-criteria.md"
  mkdir -p "$WORK"
  if [ "$WITH_PROGRESS" = "1" ]; then
    printf '{"done":[],"failed":[]}\n' > "$WORK/progress.json"
    printf '# execution-report\n\n## overall\nCOMPLETED\n\n## per_file_status\nall done\n\n## blockers\nnone\n' > "$WORK/phase4-execution-report.md"
  fi
}

build_build_plan() { # build_build_plan <bp_path>
  cat > "$1" <<'EOF'
# build-plan

files:

```yaml
path: CLAUDE.md
type: doc
```

```yaml
path: .claude/skills/pr-review/SKILL.md
type: skill
```
EOF
}

g028_input() { # g028_input <out> <work> <bp> — 打印 agent-exit 档 stdin JSON
  printf '{"profile":"agent-exit","build_plan":"%s","output_dir":"%s","target":"%s","work_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' \
    "$3" "$1" "$1" "$2" "$1" "$1"
}

echo "══ module.agent.static 正例（全静态信号闭合 + 轻检 full 形态 → PASS）══"
OUT="$TMP/out-ok"; WORK="$TMP/work-ok"; BP="$TMP/bp-ok.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "全闭合产物 agent-exit 档 PASS" 0 "$rc"
check_json "verdict=PASS" "d['verdict']=='PASS'" "$out"
check_json "无 agent_static findings" "not any(f.get('module')=='agent_static' for f in d['failures'])" "$out"
check_json "无 report_presence findings" "not any(f.get('module')=='report_presence' for f in d['failures'])" "$out"
out=$(g026_in=$(g028_input "$OUT" "$WORK" "$BP" | python3 -I -c "import json,sys; print(json.dumps({'gates':['G028'], **json.load(sys.stdin)}))"); \
      echo "$g026_in" | bash "$REPO_ROOT/scripts/gates/g026-batch-gates.sh"); rc=$?
check "g026 批跑: sunset 后编号写法必 unknown（注册表仅语义键）" 3 "$rc"
check_json "unknown_gate_script 兜底" "any(f.get('type')=='unknown_gate_script' for f in d['failures'])" "$out"

echo "══ module.agent.static 反例 ══"
OUT="$TMP/out-noexec"; WORK="$TMP/work-noexec"; BP="$TMP/bp-noexec.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
chmod -x "$OUT/.claude/skills/pr-review/scripts/run.sh"
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "脚本无可执行位 → FAIL" 2 "$rc"
check_json "script_not_executable 点名文件" "any(f.get('module')=='agent_static' and f.get('type')=='script_not_executable' and f.get('path','').endswith('run.sh') for f in d['failures'])" "$out"

OUT="$TMP/out-nofield"; WORK="$TMP/work-nofield"; BP="$TMP/bp-nofield.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
python3 - "$OUT/.claude/agents/scan-worker.md" <<'PY'
import sys
p = sys.argv[1]
t = open(p, encoding="utf-8").read()
t = t.replace("forbidden_inputs:\n  - reviewed-findings.json\n", "")
open(p, "w", encoding="utf-8").write(t)
PY
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "agent 缺 forbidden_inputs → FAIL" 2 "$rc"
check_json "frontmatter_field_missing 点名字段" "any(f.get('type')=='frontmatter_field_missing' and f.get('field')=='forbidden_inputs' for f in d['failures'])" "$out"

OUT="$TMP/out-emptyfield"; WORK="$TMP/work-emptyfield"; BP="$TMP/bp-emptyfield.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
python3 - "$OUT/.claude/agents/scan-worker.md" <<'PY'
import sys
p = sys.argv[1]
t = open(p, encoding="utf-8").read()
t = t.replace("forbidden_inputs:\n  - reviewed-findings.json\n", "forbidden_inputs: []\n")
open(p, "w", encoding="utf-8").write(t)
PY
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "forbidden_inputs 空数组 → FAIL" 2 "$rc"
check_json "frontmatter_field_empty 点名字段" "any(f.get('type')=='frontmatter_field_empty' and f.get('field')=='forbidden_inputs' for f in d['failures'])" "$out"

echo "══ module.agent.static 畸形产物（fail-closed 不静默）══"
OUT="$TMP/out-badfm"; WORK="$TMP/work-badfm"; BP="$TMP/bp-badfm.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
printf -- '---\nname: [unbalanced\n  description: broken\n---\nbody\n' > "$OUT/.claude/skills/pr-review/SKILL.md"
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "SKILL.md frontmatter 畸形 YAML → FAIL" 2 "$rc"
check_json "frontmatter_unparseable 报错位置" "any(f.get('type')=='frontmatter_unparseable' and 'SKILL.md' in f.get('path','') for f in d['failures'])" "$out"

OUT="$TMP/out-nofm"; WORK="$TMP/work-nofm"; BP="$TMP/bp-nofm.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
printf '# 无 frontmatter 的 agent 定义\n\n正文。\n' > "$OUT/.claude/agents/scan-worker.md"
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "agent 无 frontmatter → FAIL" 2 "$rc"
check_json "frontmatter_missing 报错位置" "any(f.get('type')=='frontmatter_missing' and f.get('path','').endswith('scan-worker.md') for f in d['failures'])" "$out"

echo "══ execution-report 不机检（executor v2 裁撤: report 只写不检, 存在性归 G024 兜底）══"
OUT="$TMP/out-rp"; WORK="$TMP/work-rp"; BP="$TMP/bp-rp.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
rm "$WORK/phase4-execution-report.md"
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "full 形态 report 缺失 → 不拦 PASS（report 不再机检）" 0 "$rc"
check_json "无 report 相关 failure" "not any('report' in json.dumps(f) for f in d.get('failures',[]))" "$out"

OUT="$TMP/out-emptyrp"; WORK="$TMP/work-emptyrp"; BP="$TMP/bp-emptyrp.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
: > "$WORK/phase4-execution-report.md"
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "report 空文件 → 不拦 PASS（同上）" 0 "$rc"
check_json "无 report 相关 failure（空文件）" "not any('report' in json.dumps(f) for f in d.get('failures',[]))" "$out"

OUT="$TMP/out-fast"; WORK="$TMP/work-fast"; BP="$TMP/bp-fast.md"
build_product "$OUT" "$WORK" 0; build_build_plan "$BP"
out=$(g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "fast 形态（无 progress.json）无 report → PASS（轻检不触发）" 0 "$rc"
check_json "无 report_presence findings" "not any(f.get('module')=='report_presence' for f in d['failures'])" "$out"

echo "══ module.skill.static（2.1: SK-S1/S2 移植, 行为等价基线=skill-verifier 内联版; SK-S3 归并 g005）══"
# 正例: 主交付 skill 形态（SKILL.md 在 OUTPUT_DIR 根, frontmatter 三字段 + ≥50 行 + 引用闭合）
SKOUT="$TMP/skill-pos"
mkdir -p "$SKOUT/references" "$SKOUT/scripts" "$SKOUT/.claude/skills" "$SKOUT/.claude/rules"
{
  printf -- '---\nname: mini\ndescription: "最小技能。"\nversion: "1.0.0"\n---\n# Mini\n'
  printf '正文行。\n%.0s' $(seq 1 60)
  printf '详见 references/guide.md；入口 bash scripts/go.sh。\n'
} > "$SKOUT/SKILL.md"
printf '# Guide\n\n内容。\n' > "$SKOUT/references/guide.md"
printf '#!/bin/bash\necho hi\n' > "$SKOUT/scripts/go.sh"; chmod +x "$SKOUT/scripts/go.sh"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s","rules_dir":"%s"}' \
      "$SKOUT" "$SKOUT/.claude/skills" "$SKOUT/.claude/rules" | bash "$G028"); rc=$?
check "skill 正例（SK-S1/S2 全闭合）→ PASS" 0 "$rc"
check_json "无 skill_static failures" "not any(f.get('module')=='skill_static' for f in d['failures'])" "$out"
out=$(printf '{"profile":"skill-verify","output_dir":"%s"}' "$SKOUT" | bash "$G028"); rc=$?
check "skill-verify 档同一正例 → PASS（采信链同源, 只读幂等）" 0 "$rc"

# SK-S1 反例: version 缺失 + 行数不足
SK1="$TMP/skill-s1"
mkdir -p "$SK1"
printf -- '---\nname: mini\ndescription: "缺 version。"\n---\n# Mini\n短文件。\n' > "$SK1/SKILL.md"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' "$SK1" "$SK1" "$SK1" | bash "$G028"); rc=$?
check "version 缺失 + <50 行 → FAIL rc2" 2 "$rc"
check_json "frontmatter_field_missing:version + skill_md_too_short" \
  "any(f.get('type')=='frontmatter_field_missing' and f.get('field')=='version' for f in d['failures']) and any(f.get('type')=='skill_md_too_short' for f in d['failures'])" "$out"

# SK-S2 反例: 引用断裂 + 脚本语法错 + 绝对路径
SK2="$TMP/skill-s2"
mkdir -p "$SK2/references" "$SKOUT/scripts" "$SK2/scripts"
{
  printf -- '---\nname: mini\ndescription: "引用断裂样例。"\nversion: "1.0.0"\n---\n# Mini\n'
  printf '正文行。\n%.0s' $(seq 1 55)
  printf '看 references/ghost.md；跑 bash scripts/broken.sh；路径 /home/nobody/data。\n'
} > "$SK2/SKILL.md"
printf '#!/bin/bash\nif then\n' > "$SK2/scripts/broken.sh"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' "$SK2" "$SK2" "$SK2" | bash "$G028"); rc=$?
check "SK-S2 三反例 → FAIL rc2" 2 "$rc"
check_json "broken_reference + script_syntax_error + absolute_path_found" \
  "any(f.get('type')=='broken_reference' and f.get('ref')=='references/ghost.md' for f in d['failures']) and any(f.get('type')=='script_syntax_error' for f in d['failures']) and any(f.get('type')=='absolute_path_found' for f in d['failures'])" "$out"

# 畸形: SKILL.md 缺失 / 无 frontmatter / frontmatter 非映射
SK3="$TMP/skill-empty"; mkdir -p "$SK3"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' "$SK3" "$SK3" "$SK3" | bash "$G028"); rc=$?
check "SKILL.md 缺失 → FAIL rc2（fail-closed 不静默跳过）" 2 "$rc"
check_json "skill_md_missing" "any(f.get('type')=='skill_md_missing' for f in d['failures'])" "$out"
SK4="$TMP/skill-nofm"; mkdir -p "$SK4"
{ printf '# Mini\n'; printf '正文行。\n%.0s' $(seq 1 60); } > "$SK4/SKILL.md"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' "$SK4" "$SK4" "$SK4" | bash "$G028"); rc=$?
check "无 frontmatter → FAIL rc2" 2 "$rc"
check_json "frontmatter_missing" "any(f.get('module')=='skill_static' and f.get('type')=='frontmatter_missing' for f in d['failures'])" "$out"
SK5="$TMP/skill-badfm"; mkdir -p "$SK5"
{ printf -- '---\n- just\n- a list\n---\n# Mini\n'; printf '正文行。\n%.0s' $(seq 1 60); } > "$SK5/SKILL.md"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' "$SK5" "$SK5" "$SK5" | bash "$G028"); rc=$?
check "frontmatter 非映射 → FAIL rc2" 2 "$rc"
check_json "frontmatter_unparseable" "any(f.get('type')=='frontmatter_unparseable' and '映射' in (f.get('detail') or '') for f in d['failures'])" "$out"

# SK-S3 双轨防线: 占位符由 g005 拦（module=g005）, skill_static 无占位符检查类型
SK6="$TMP/skill-todo"; mkdir -p "$SK6"
{ printf -- '---\nname: mini\ndescription: "含 TODO。"\nversion: "1.0.0"\n---\n# Mini\n'; printf '正文行。\n%.0s' $(seq 1 60); printf 'TODO: 待实现。\n'; } > "$SK6/SKILL.md"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' "$SK6" "$SK6" "$SK6" | bash "$G028"); rc=$?
check "占位符 TODO → g005 拦截 FAIL rc2" 2 "$rc"
check_json "failures 来自 g005 而非 skill_static（无双轨）" \
  "any(f.get('module')=='g005' for f in d['failures']) and not any(f.get('module')=='skill_static' for f in d['failures'])" "$out"

echo "══ skill-build 档 g014 条件启用（纯 skill 交付物无 .claude/ 子目录）══"
SK7="$TMP/skill-pure"; mkdir -p "$SK7/templates"
{ printf -- '---\nname: pure\ndescription: "无 .claude 子目录的纯 skill 交付物。"\nversion: "1.0.0"\n---\n# Pure\n'; printf '正文行。\n%.0s' $(seq 1 58); printf '资产表引用仓库机检: bash scripts/check-gate-registry.sh。\n'; } > "$SK7/SKILL.md"
printf '# 报告模板\n' > "$SK7/templates/verify-report.md"
out=$(printf '{"profile":"skill-build","output_dir":"%s"}' "$SK7" | bash "$G028"); rc=$?
check "纯 skill 交付物（无 skills_dir 键）→ PASS（g014 条件跳过）" 0 "$rc"
check_json "无 missing_input/g014 failures" "not any(f.get('module')=='g014' for f in d.get('failures',[]))" "$out"
out=$(printf '{"profile":"skill-build","output_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' "$SK7" "$SK7" "$SK7" | bash "$G028"); rc=$?
check "skills_dir 键提供但目录不存在 → FAIL rc2（g014 fail-closed 不变）" 2 "$rc"
check_json "g014 missing_input" "any(f.get('module')=='g014' and f.get('type')=='missing_input' for f in d['failures'])" "$out"

echo "══ SK-S2 scripts 提及边界（无 scripts/ 目录 → 仓库路径提及不检, 收官构建实测确立）══"
out=$(printf '{"profile":"skill-build","output_dir":"%s"}' "$SK7" | bash "$G028"); rc=$?
check "纯 skill 交付物提及仓库 scripts 路径 → 不误报" 0 "$rc"
check_json "无 broken_reference" "not any(f.get('type')=='broken_reference' for f in d.get('failures',[]))" "$out"

echo "══ FA 极简 build-plan 正例（fast 车道关键回归锚——裁定 1: G028 agent-exit 档零改动消费）══"
FAOUT="$TMP/fa-out"; FAWORK="$TMP/fa-work"; FABP="$REPO_ROOT/tests/fixtures/fast-lane/build-plan-fast-positive.md"
build_product "$FAOUT" "$FAWORK" 1
[ -f "$FABP" ] && ok "fixture 在场: tests/fixtures/fast-lane/build-plan-fast-positive.md" || bad "fixture 缺失"
out=$(bash "$REPO_ROOT/scripts/gates/g025-asset-copy.sh" --build-plan "$FABP" --output-dir "$FAOUT" 2>&1); rc=$?
check "g025 物化极简 build-plan 的 copy/template 条目 → PASS" 0 "$rc"
echo "$out" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert d.get('materialized_count')==3 and d.get('copied_count')==1, d" && ok "物化 3（G003+G005+settings）/ 拷 1（security.md）" || bad "物化计数漂移"
grep -qE '\{\{[^}]*\}\}|TODO|TBD|FIXME|XXX|待补充|待定|待填写' "$FAOUT/phase/gates/G005-no-placeholders.md" && \
  bad "G005 模板物化产物自含被检字样（自指矛盾复发——模板资产须为无字样描述法）" || \
  ok "G005 物化产物零字样（自指矛盾防复发锚）"
out=$(printf '{"profile":"agent-exit","build_plan":"%s","output_dir":"%s","target":"%s","work_dir":"%s","skills_dir":"%s/.claude/skills","rules_dir":"%s/.claude/rules"}' \
      "$FABP" "$FAOUT" "$FAOUT" "$FAWORK" "$FAOUT" "$FAOUT" | bash "$G028"); rc=$?
check "极简 build-plan（fast 形态: basis=[] / 单行物化 / copy+template 条目）agent-exit 档 → 零 FAIL 零 concerns（rc=0; G0 补 extends 头后 assets/rules 复制件不再产 rule_missing_extends concern——原期望 rc=1 锚的是旧资产凹点）" 0 "$rc"
check_json "failures 为空（PASS, 拦截面零命中）" "d['failures']==[]" "$out"

echo "══ 出口减负两层化（2026-10-16: 标准清单复检撤出, 地板只保 CLAUDE.md）══"
# (a) 部分形态产物（CLAUDE.md + 1 skill, 无 phase//evaluation/）→ agent-exit PASS（新语义正例）
POUT="$TMP/out-partial"; PWORK="$TMP/work-partial"; PBP="$TMP/bp-partial.md"
mkdir -p "$POUT/.claude/skills/mini" "$POUT/.claude/rules" "$PWORK"
printf '# mini-agent\n\n运行时入口总览（部分形态合成用例, 无 phase/ 与 evaluation/ 目录）。\n本文件满足 g021 字节地板, 内容仅为占位描述, 不含任何路径式引用。\n' > "$POUT/CLAUDE.md"
printf -- '---\nname: mini\ndescription: "部分形态用例附属 skill。"\n---\n# Mini\n\n正文。\n' > "$POUT/.claude/skills/mini/SKILL.md"
cat > "$PBP" <<'EOF'
# build-plan（部分形态合成）

files:

```yaml
path: CLAUDE.md
type: doc
```

```yaml
path: .claude/skills/mini/SKILL.md
type: skill
```
EOF
out=$(g028_input "$POUT" "$PWORK" "$PBP" | bash "$G028"); rc=$?
check "部分形态产物（无 phase//evaluation/）agent-exit → PASS（清单复检已撤, 方案保真即可）" 0 "$rc"
check_json "无 file_list failures" "not any(f.get('module')=='file_list' for f in d['failures'])" "$out"

# (b) 缺 CLAUDE.md → agent-exit FAIL missing_entry_file（地板守住）
NOUT="$TMP/out-noentry"; NWORK="$TMP/work-noentry"; NBP="$TMP/bp-noentry.md"
mkdir -p "$NOUT/.claude/skills/mini" "$NOUT/.claude/rules" "$NWORK"
printf -- '---\nname: mini\ndescription: "无入口用例附属 skill。"\n---\n# Mini\n\n正文。\n' > "$NOUT/.claude/skills/mini/SKILL.md"
cat > "$NBP" <<'EOF'
# build-plan（无入口合成）

files:

```yaml
path: .claude/skills/mini/SKILL.md
type: skill
```
EOF
out=$(g028_input "$NOUT" "$NWORK" "$NBP" | bash "$G028"); rc=$?
check "缺 CLAUDE.md → agent-exit FAIL（plan-independent 地板）" 2 "$rc"
check_json "missing_entry_file 点名 CLAUDE.md" "any(f.get('module')=='file_list' and f.get('type')=='missing_entry_file' and f.get('path')=='CLAUDE.md' for f in d['failures'])" "$out"

# (c) CLAUDE.md 空文件 → empty_entry_file（地板非空半边）
EOUT="$TMP/out-emptyentry"; EWORK="$TMP/work-emptyentry"; EBP="$TMP/bp-emptyentry.md"
mkdir -p "$EOUT/.claude/skills/mini" "$EOUT/.claude/rules" "$EWORK"
: > "$EOUT/CLAUDE.md"
printf -- '---\nname: mini\ndescription: "空入口用例附属 skill。"\n---\n# Mini\n\n正文。\n' > "$EOUT/.claude/skills/mini/SKILL.md"
cat > "$EBP" <<'EOF'
# build-plan（空入口合成）

files:

```yaml
path: CLAUDE.md
type: doc
```

```yaml
path: .claude/skills/mini/SKILL.md
type: skill
```
EOF
out=$(g028_input "$EOUT" "$EWORK" "$EBP" | bash "$G028"); rc=$?
check "CLAUDE.md 空文件 → agent-exit FAIL（地板非空半边）" 2 "$rc"
check_json "empty_entry_file 点名 CLAUDE.md" "any(f.get('module')=='file_list' and f.get('type')=='empty_entry_file' and f.get('path')=='CLAUDE.md' for f in d['failures'])" "$out"

echo "══ 畸形输入负例（C8-1/C8-4, ≥3, 全部 exit=2 + input_error）══"
out=$(printf 'not json' | bash "$G028"); rc=$?
check "非 JSON → rc2" 2 "$rc"
check_json "input_error 类型" "d['failures'][0]['type']=='input_error'" "$out"
out=$(printf '{"profile":"agent-exi' | bash "$G028"); rc=$?
check "截断 JSON → rc2" 2 "$rc"
check_json "input_error 类型" "d['failures'][0]['type']=='input_error'" "$out"
out=$(echo '{"profile":"fast-lane","output_dir":"x"}' | bash "$G028"); rc=$?
check "非法 profile → rc2" 2 "$rc"
check_json "input_error 报 profile" "d['failures'][0]['type']=='input_error' and 'profile' in json.dumps(d['failures'][0])" "$out"
out=$(echo '{"profile":"agent-exit","build_plan":"x","output_dir":"y","skills_dir":"s","rules_dir":"r"}' | bash "$G028"); rc=$?
check "agent-exit 缺 work_dir → rc2" 2 "$rc"
check_json "missing_keys 列明 work_dir" "any(f.get('type')=='input_error' and 'work_dir' in json.dumps(f) for f in d['failures'])" "$out"
out=$(echo '{"profile":123,"output_dir":"x"}' | bash "$G028"); rc=$?
check "profile 数字类型 → rc2" 2 "$rc"

echo "══ C8-2 仓外运行 ══"
OUT="$TMP/out-repo"; WORK="$TMP/work-repo"; BP="$TMP/bp-repo.md"
build_product "$OUT" "$WORK" 1; build_build_plan "$BP"
out=$(cd "$TMP" && g028_input "$OUT" "$WORK" "$BP" | bash "$G028"); rc=$?
check "仓外 cwd 跑 agent-exit 档 PASS" 0 "$rc"

echo "══ g022 裁撤后形态（executor v2: report 不再机检, 脚本已删）══"
if [ ! -f "$REPO_ROOT/scripts/gates/g022-execution-report.sh" ]; then
  ok "g022-execution-report.sh 已物理删除"
else
  bad "g022-execution-report.sh 仍存在（应随 executor v2 裁撤）"
fi
W="$TMP/work-g022"; mkdir -p "$W"
printf '# execution-report\n\n## overall\nCOMPLETED\n\n## per_file_status\nall done\n\n## blockers\nnone\n' > "$W/phase4-execution-report.md"
out=$(echo '{"gates":["G999-no-such"],"work_dir":"'"$W"'"}' | bash "$REPO_ROOT/scripts/gates/g026-batch-gates.sh"); rc=$?
check "legacy G022 经批跑 → FAIL rc3（registry 无条目, 不静默）" 3 "$rc"
check_json "unknown_gate_script" "any(f.get('type')=='unknown_gate_script' for f in d['failures'])" "$out"
# agent-exit 档不含任何 report 检查模块（execution-report 只写不检）
W2="$TMP/work-nog022"; OUT2="$TMP/out-nog022"; BP2="$TMP/bp-nog022.md"
build_product "$OUT2" "$W2" 1; build_build_plan "$BP2"
out=$(g028_input "$OUT2" "$W2" "$BP2" | bash "$G028"); rc=$?
check "agent-exit 档无 report 机检（report 缺段不拦）→ PASS" 0 "$rc"
check_json "无 report 相关 failure 类型" "not any('report' in json.dumps(f) for f in d.get('failures',[]))" "$out"

echo "══ bash -n ══"
if bash -n "$G028" && bash -n "$0"; then
  ok "g028 / 本套件 bash -n 通过"
else
  bad "bash -n 失败"
fi

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
