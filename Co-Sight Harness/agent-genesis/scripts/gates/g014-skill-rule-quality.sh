#!/bin/bash
# scripts/gates/g014-skill-rule-quality.sh
# 检查: SKILL.md frontmatter 含 name: + description:; rule 文件含引用行
# 协议: stdin JSON → stdout JSON → exit 0(PASS)/2(FAIL)
# fail-closed（gate 治理方案阶段 1）: skills_dir / rules_dir 缺失或目录不存在
# 即 FAIL missing_input——禁止键缺失时静默跳检空转 PASS。
set -euo pipefail

INPUT=$(cat)
SKILLS_DIR=$(echo "$INPUT" | jq -r '.skills_dir // ""')
RULES_DIR=$(echo "$INPUT" | jq -r '.rules_dir // ""')

FAILURES_JSON="[]"
CONCERNS_JSON="[]"

add_failure() {
  FAILURES_JSON=$(echo "$FAILURES_JSON" | jq --argjson n "$1" '. + [$n]')
}

add_concern() {
  CONCERNS_JSON=$(echo "$CONCERNS_JSON" | jq --argjson n "$1" '. + [$n]')
}

# ── 输入 fail-closed ──
for entry in "skills_dir:$SKILLS_DIR" "rules_dir:$RULES_DIR"; do
  key="${entry%%:*}"
  dir="${entry#*:}"
  if [ -z "$dir" ] || [ "$dir" = "null" ] || [ ! -d "$dir" ]; then
    add_failure "$(jq -n --arg k "$key" --arg v "$dir" \
      '{type:"missing_input",key:$k,value:$v,detail:"输入键缺失或目录不存在——拒绝静默跳检"}')"
  fi
done

if [ "$(echo "$FAILURES_JSON" | jq 'length')" -gt 0 ]; then
  echo "{\"gate_id\":\"G014\",\"verdict\":\"FAIL\",\"failures\":$FAILURES_JSON}"
  exit 2
fi

# ── Check SKILL.md frontmatter（find 结果逐行读，路径含空格不碎）──
while IFS= read -r -d '' skill_md; do
  FM=$(awk 'BEGIN{p=0} /^---$/{p++; next} p==1{print} /^---$/{exit}' "$skill_md")
  if ! echo "$FM" | grep -q '^name:'; then
    add_failure "$(jq -n --arg f "$skill_md" '{type:"skill_missing_name",file:$f}')"
  fi
  if ! echo "$FM" | grep -q '^description:'; then
    add_failure "$(jq -n --arg f "$skill_md" '{type:"skill_missing_description",file:$f}')"
  fi
done < <(find "$SKILLS_DIR" -name 'SKILL.md' -print0 2>/dev/null)

# ── Check rule files for extends reference（CONCERNS 级: 不继承 common 层是合法选择，
#    不应阻断——gate 治理阶段 3 降严）──
while IFS= read -r -d '' rule_md; do
  if ! grep -qF '> This file extends' "$rule_md"; then
    add_concern "$(jq -n --arg f "$rule_md" '{type:"rule_missing_extends",file:$f}')"
  fi
done < <(find "$RULES_DIR" -name '*.md' -print0 2>/dev/null)

COUNT=$(echo "$FAILURES_JSON" | jq 'length')
if [ "$COUNT" -gt 0 ]; then
  echo "{\"gate_id\":\"G014\",\"verdict\":\"FAIL\",\"failures\":$FAILURES_JSON,\"concerns\":$CONCERNS_JSON}"
  exit 2
fi
CCOUNT=$(echo "$CONCERNS_JSON" | jq 'length')
if [ "$CCOUNT" -gt 0 ]; then
  echo "{\"gate_id\":\"G014\",\"verdict\":\"CONCERNS\",\"concerns\":$CONCERNS_JSON}"
  exit 0
fi
echo '{"gate_id":"gate.skill.quality","verdict":"PASS"}'
exit 0
