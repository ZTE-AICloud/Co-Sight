#!/usr/bin/env bash
# tests/unit/test-g028-host-extend.sh
# V4 验证（host-context 方案 §6 V4）: G028 agent-exit 档 host_extend 豁免键四象限
#   ① 无根 CLAUDE.md + host_extend=true  → PASS（豁免生效——合法宿主场景）
#   ② 无根 CLAUDE.md + 豁免缺省          → FAIL（现状行为不变——地板拦截）
#   ③ 有根 CLAUDE.md + host_extend=true  → PASS
#   ④ 有根 CLAUDE.md + 豁免缺省          → PASS（现状行为不变）
#   ⑤ 豁免开启但产物带占位符             → FAIL（豁免≠跳检——g005 仍对声明文件生效）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
G028="$SCRIPT_DIR/../../scripts/gates/g028-exit-sanity.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0

make_fixture() { # make_fixture <dir> <with_claude_md: 0|1> <placeholder: 0|1>
  local d="$1" withcm="$2" ph="$3"
  mkdir -p "$d/output/.claude/agents" "$d/work" "$d/skills" "$d/rules"
  [ "$withcm" = "1" ] && printf "# host project

这是一个合法宿主项目的根说明文档, 长度超过一百字节以满足 g021 地板的最低体积要求, 内容为占位语义。
" > "$d/output/CLAUDE.md"
  if [ "$ph" = "1" ]; then
    printf -- '---\nname: new-agent\ndescription: 测试\nforbidden_inputs:
  - work/
  - human-review.md\ntools:\n  - Read\n---\nTODO_PLACEHOLDER_UNFILLED\n' > "$d/output/.claude/agents/new-agent.md"
  else
    printf -- '---\nname: new-agent\ndescription: 宿主增补测试 subagent\nforbidden_inputs:
  - work/
  - human-review.md\ntools:\n  - Read\n---\n# new-agent\n职责: 校验用例。\n' > "$d/output/.claude/agents/new-agent.md"
  fi
  cat > "$d/work/build-plan.md" <<'EOF'
# 极简 build-plan（形态④宿主增补）

```yaml
path: .claude/agents/new-agent.md
type: agent
generation: generate
invariants:
  - type: frontmatter_field_nonempty
    field: description
```
EOF
}

run_case() { # run_case <label> <expect: PASS|FAIL> <dir> <host_extend: 0|1>
  local label="$1" expect="$2" d="$3" he="$4" verdict
  local input="{\"gates\":[\"runner.exit\"],\"profile\":\"agent-exit\",\"output_dir\":\"$d/output\",\"work_dir\":\"$d/work\",\"skills_dir\":\"$d/skills\",\"rules_dir\":\"$d/rules\",\"build_plan\":\"$d/work/build-plan.md\""
  [ "$he" = "1" ] && input+=', "host_extend": true'
  input+='}'
  verdict=$(echo "$input" | bash "$G028" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("verdict",""))' 2>/dev/null)
  # verdict: PASS=全过 / FAIL=有 failure（g028 汇总口径见脚本 result 段）
  if [ "$verdict" = "$expect" ]; then
    PASS=$((PASS+1)); echo "PASS  $label (verdict=$verdict)"
  else
    FAIL=$((FAIL+1)); echo "FAIL  $label (verdict=$verdict expected=$expect)"
    echo "$input" | bash "$G028" 2>&1 | tail -3
  fi
}

# ① 无根 CLAUDE.md + 豁免
d="$TMP/c1"; make_fixture "$d" 0 0; run_case "①无CLAUDE.md+host_extend→PASS" PASS "$d" 1
# ② 无根 CLAUDE.md + 缺省
d="$TMP/c2"; make_fixture "$d" 0 0; run_case "②无CLAUDE.md+缺省→FAIL(地板)" FAIL "$d" 0
# ③ 有根 CLAUDE.md + 豁免
d="$TMP/c3"; make_fixture "$d" 1 0; run_case "③有CLAUDE.md+host_extend→PASS" PASS "$d" 1
# ④ 有根 CLAUDE.md + 缺省
d="$TMP/c4"; make_fixture "$d" 1 0; run_case "④有CLAUDE.md+缺省→PASS(现状)" PASS "$d" 0
# ⑤ 豁免开启但占位符产物 → g005 仍生效
d="$TMP/c5"; make_fixture "$d" 0 1; run_case "⑤豁免+占位符→FAIL(g005生效)" FAIL "$d" 1

echo "----"
echo "V4-G028 结果: PASS=$PASS FAIL=$FAIL"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 2)
