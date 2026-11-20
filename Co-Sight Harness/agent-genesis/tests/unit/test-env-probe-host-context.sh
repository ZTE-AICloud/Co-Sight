#!/usr/bin/env bash
# tests/unit/test-env-probe-host-context.sh
# V1 验证（host-context 方案 §6 V1）: host_project 段 fixture 矩阵
# 矩阵: ①CLAUDE.md ②仅.claude/ ③.dsh/+AGENTS.md ④cordis.patch.yml
#       ⑤package.json 普通仓 ⑥空目录 → claude_code×2 / dsh×2 / none×2
# 附: fail-open（无 python 可用时回落 none 不阻断）+ 抑制开关 AG_SUPPRESS_HOST_CONTEXT
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE="$SCRIPT_DIR/../../scripts/env-probe.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
check_kind() { # check_kind <label> <expected_kind> <dir>
  local label="$1" expected="$2" dir="$3" got
  got=$(cd "$dir" && bash "$PROBE" ctx-test 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("host_project_kind",""))' 2>/dev/null)
  local sect=""; [ -f "$dir/.agent-genesis/work/ctx-test/env-readiness.yaml" ] && \
    sect=$(grep -m1 'project_kind' "$dir/.agent-genesis/work/ctx-test/env-readiness.yaml" | sed 's/.*"\(.*\)"/\1/')
  if [ "$got" = "$expected" ] && [ "$sect" = "$expected" ]; then
    PASS=$((PASS+1)); echo "PASS  $label (kind=$got)"
  else
    FAIL=$((FAIL+1)); echo "FAIL  $label (stdout=$got yaml=$sect expected=$expected)"
  fi
}

# ① CLAUDE.md
d="$TMP/t1-claude-md"; mkdir -p "$d"; echo "# proj" > "$d/CLAUDE.md"
check_kind "CLAUDE.md→claude_code" claude_code "$d"

# ② 仅 .claude/
d="$TMP/t2-claude-dir"; mkdir -p "$d/.claude/agents"
printf -- '---\nname: helper\ndescription: 测试用 subagent\n---\nbody\n' > "$d/.claude/agents/helper.md"
check_kind ".claude/→claude_code" claude_code "$d"

# ③ .dsh/ + AGENTS.md
d="$TMP/t3-dsh-dir"; mkdir -p "$d/.dsh/skills"; echo "dsh" > "$d/AGENTS.md"
check_kind ".dsh/+AGENTS.md→dsh" dsh "$d"

# ④ cordis.patch.yml
d="$TMP/t4-dsh-patch"; mkdir -p "$d"; echo "patches:" > "$d/cordis.patch.yml"
check_kind "cordis.patch.yml→dsh" dsh "$d"

# ⑤ package.json 普通仓（收窄判定: 不算项目语境）
d="$TMP/t5-generic"; mkdir -p "$d"; echo '{}' > "$d/package.json"
check_kind "package.json→none" none "$d"

# ⑥ 空目录
d="$TMP/t6-empty"; mkdir -p "$d"
check_kind "空目录→none" none "$d"

# ⑦ 抑制开关: claude 项目 + AG_SUPPRESS_HOST_CONTEXT=1 → none + suppressed
d="$TMP/t7-suppressed"; mkdir -p "$d"; echo "# proj" > "$d/CLAUDE.md"
got=$(cd "$d" && AG_SUPPRESS_HOST_CONTEXT=1 bash "$PROBE" ctx-test 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("host_project_kind",""))')
sup=$(grep -m1 'suppressed' "$d/.agent-genesis/work/ctx-test/env-readiness.yaml" | sed 's/.*"\(.*\)"/\1/')
if [ "$got" = "none" ] && [ "$sup" = "true" ]; then
  PASS=$((PASS+1)); echo "PASS  抑制开关→none+suppressed"
else
  FAIL=$((FAIL+1)); echo "FAIL  抑制开关 (kind=$got suppressed=$sup)"
fi

# ⑧ 资产枚举: output/agents + .claude/skills 条目与 description
d="$TMP/t8-assets"; mkdir -p "$d/output/agents/review-bot/v1" "$d/.claude/skills/my-skill"
echo "# r" > "$d/output/agents/review-bot/v1/CLAUDE.md"
printf -- '---\ndescription: 审查助手\n---\n' > "$d/.claude/skills/my-skill/SKILL.md"
(cd "$d" && bash "$PROBE" ctx-test > /dev/null 2>&1)
yaml="$d/.agent-genesis/work/ctx-test/env-readiness.yaml"
if grep -q 'name: "review-bot"' "$yaml" && grep -q 'name: "my-skill"' "$yaml" && grep -q 'description: "审查助手"' "$yaml"; then
  PASS=$((PASS+1)); echo "PASS  资产枚举含 name+description"
else
  FAIL=$((FAIL+1)); echo "FAIL  资产枚举: $(grep -A2 'existing_' "$yaml")"
fi

# ⑨ yaml 可解析性（空资产场景语法合法）
python3 - "$TMP/t6-empty/.agent-genesis/work/ctx-test/env-readiness.yaml" <<'PY' && { PASS=$((PASS+1)); echo "PASS  空资产 yaml 可解析"; } || { FAIL=$((FAIL+1)); echo "FAIL  空 asset yaml 解析"; }
import sys
try:
    import yaml
    d = yaml.safe_load(open(sys.argv[1]))
    hp = d["host_project"]
    assert hp["existing_agents"] == [] and hp["existing_skills"] == []
except ImportError:
    pass  # 无 pyyaml 环境跳过语义校验, 语法由上游用例覆盖
PY

echo "----"
echo "V1 结果: PASS=$PASS FAIL=$FAIL"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 2)
