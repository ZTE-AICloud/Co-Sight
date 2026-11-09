#!/usr/bin/env bash
# G030 DSH 产物结构门禁验证
# 覆盖: 合法 bundle PASS / 无 dsh 目录跳过 / 重复 toolName / subagent 缺 persona /
#       Claude 残留 / 纯 dsh 生成 .claude 产物 / platforms=[dsh] 缺 dsh/ /
#       package.json 损坏 / patch 逃逸 / 行 id 重复 / 必填 config 缺失 / 技能未挂载 / 挂错包 /
#       CLAUDE.md 缺失 / install.sh 语法错 / g026 stdin 通道
# 用法: bash tests/gates/g030-dsh-output-verify.sh   （在插件根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
G030="scripts/gates/g030-dsh-output.sh"
PKG_NAME="@cosight/agent-demo"

assert_failure() { # assert_failure <json> <type>
  local out="$1" want="$2"
  if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
fs={f.get('type') for f in d.get('failures') or []}
assert d['verdict']=='FAIL', d
assert '$want' in fs, fs
" 2>/dev/null; then
    ok "failure 含 $want"
  else
    bad "failure 未含 $want（实际: $out）"
  fi
}

# ── 基础夹具（合法 DSH bundle）──
make_fixture() { # make_fixture <dir>
  local root="$1"
  rm -rf "$root"
  mkdir -p "$root/dsh/skills/demo-skill" "$root/dsh/rules"
  printf '# Demo Agent\n\n测试用。\n' > "$root/CLAUDE.md"
  cat > "$root/dsh/package.json" <<'JSON'
{
  "name": "@cosight/agent-demo",
  "version": "1.0.0",
  "description": "demo",
  "type": "module",
  "files": ["cordis.patch.yml", "README.md", "install.sh", "skills", "rules"],
  "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}
}
JSON
  cat > "$root/dsh/cordis.patch.yml" <<'YAML'
- insert:
    - id: preset-demo
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: demo
        name: Demo Agent
        description: 演示
        order: 50
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config:
              prefix: |
                你是 Demo Agent。
          - id: tool-fs
            name: '@deepseek-ai/dsh-tool-fs'
          - id: instructions
            name: '@deepseek-ai/dsh-agent-instructions'
            config:
              maxBytes: 65536
          - id: tool-fs-search
            name: '@deepseek-ai/dsh-tool-fs-search'
            config:
              sampleOverCapGlobResults: false
          - id: tool-todo
            name: '@deepseek-ai/dsh-tool-todo'
            config:
              allowParallelInProgress: false
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config:
              customSkillDirs:
                - !!js process.getBuiltinModule('node:path').join(
                    process.getBuiltinModule('node:path').dirname(
                      process.getBuiltinModule('node:module')
                        .createRequire(baseUrl).resolve('@cosight/agent-demo/package.json')),
                    'skills')
          - id: tool-subagent-reviewer
            name: '@deepseek-ai/dsh-tool-subagent'
            config:
              provider: spawn
              toolName: subagent_reviewer
              maxDepth: 2
              persona: |
                你是审查者。
              toolFilter:
                allow: [read, grep]
YAML
  cat > "$root/dsh/install.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
PROFILE="${1:-web}"
dsh plugin --profile "$PROFILE" add "$(cd "$(dirname "$0")" && pwd)"
SH
  chmod +x "$root/dsh/install.sh"
  cat > "$root/dsh/README.md" <<'MD'
# Demo Agent

## 安装

在本目录执行 `./install.sh web`，重启 dsh 后在 UI 选择 Demo Agent。

## 使用

与 Agent 对话即可。

## 能力差异

DSH 与 Claude Code 的能力不完全对等，迁移时需注意下列差异：

- 无 settings.json 等价物：权限与工具开关改由 preset 的 plugins 行声明
- hooks 不生成：事件钩子能力在 DSH 侧暂无对应实现，需要时改用技能显式调用
- 子代理通过 preset 内的 tool-subagent 行提供，不再依赖 agents/ 目录
MD
  cat > "$root/dsh/skills/demo-skill/SKILL.md" <<'MD'
---
name: demo-skill
description: 演示技能
---

# demo

内容。
MD
  printf '# 规则\n\n规则文件在 dsh/rules/，按需 read。\n' > "$root/dsh/rules/style.md"
}

plan_with() { # plan_with <file> <platforms 逗号分隔>
  printf -- '---\nplatforms: [%s]\n---\n\n# plan\n' "$2" > "$1"
}

run_gate() { # run_gate <out-dir> [extra args...]
  local dir="$1"; shift
  bash "$G030" --output-dir "$dir" "$@" </dev/null 2>&1
}

BASE="$TMP/base"
make_fixture "$BASE"

echo "══ 1. 合法 bundle ══"
out=$(run_gate "$BASE"); rc=$?
check "无 build-plan 且 dsh/ 存在 → PASS" 0 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='PASS', d
assert not d['failures'], d
assert not d['concerns'], d
" 2>/dev/null; then
  ok "verdict=PASS 且无 failures/concerns"
else
  bad "PASS 载荷异常: $out"
fi

plan_with "$TMP/plan-dsh.md" dsh
out=$(run_gate "$BASE" --build-plan "$TMP/plan-dsh.md"); rc=$?
check "platforms=[dsh] → PASS" 0 "$rc"

echo "══ 2. 平台不适用时跳过 ══"
mkdir -p "$TMP/claude-only"
out=$(run_gate "$TMP/claude-only"); rc=$?
check "无 dsh/ 且无 build-plan → PASS(跳过)" 0 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='PASS' and not d['failures'], d
" 2>/dev/null; then ok "不适用时不产生 failure"; else bad "跳过载荷异常: $out"; fi

plan_with "$TMP/plan-claude.md" claude-code
out=$(run_gate "$TMP/claude-only" --build-plan "$TMP/plan-claude.md"); rc=$?
check "platforms=[claude-code] → PASS(跳过)" 0 "$rc"

plan_with "$TMP/plan-dsh-no-dir.md" dsh
out=$(run_gate "$TMP/claude-only" --build-plan "$TMP/plan-dsh-no-dir.md"); rc=$?
check "platforms=[dsh] 但缺 dsh/ → rc=2" 2 "$rc"
assert_failure "$out" missing_dir

echo "══ 3. preset 结构 ══"
D="$TMP/mut"; make_fixture "$D"
python3 - "$D/dsh/cordis.patch.yml" <<'PY'
import sys
p = sys.argv[1]; t = open(p, encoding="utf-8").read()
# 追加第二个子代理行，toolName 与第一个重复
extra = """          - id: tool-subagent-writer
            name: '@deepseek-ai/dsh-tool-subagent'
            config:
              provider: spawn
              toolName: subagent_reviewer
              persona: |
                你是作者。
"""
t = t.replace("              toolFilter:\n                allow: [read, grep]\n",
              "              toolFilter:\n                allow: [read, grep]\n" + extra)
open(p, "w", encoding="utf-8").write(t)
PY
out=$(run_gate "$D"); rc=$?
check "重复 toolName → rc=2" 2 "$rc"
assert_failure "$out" duplicate_tool_name

make_fixture "$D"
python3 - "$D/dsh/cordis.patch.yml" <<'PY'
import sys
p = sys.argv[1]; lines = open(p, encoding="utf-8").read().splitlines(True)
out = [ln for ln in lines if "persona: |" not in ln and "你是审查者。" not in ln]
open(p, "w", encoding="utf-8").writelines(out)
PY
out=$(run_gate "$D"); rc=$?
check "tool-subagent 缺 persona → rc=2" 2 "$rc"
assert_failure "$out" subagent_field_missing

make_fixture "$D"
python3 - "$D/dsh/cordis.patch.yml" <<'PY'
import sys
p = sys.argv[1]; t = open(p, encoding="utf-8").read()
t = t.replace("- id: tool-fs\n", "- id: persona\n")   # 行 id 重复
open(p, "w", encoding="utf-8").write(t)
PY
out=$(run_gate "$D"); rc=$?
check "行 id 重复 → rc=2" 2 "$rc"
assert_failure "$out" duplicate_row_id

# DSH 0.2 必填 config：漏写时宿主会把 preset 标记 broken（UI 不可选）
make_fixture "$D"
python3 - "$D/dsh/cordis.patch.yml" <<'PY'
import sys
p = sys.argv[1]; lines = open(p, encoding="utf-8").read().splitlines(True)
open(p, "w", encoding="utf-8").writelines(ln for ln in lines if "maxBytes:" not in ln)
PY
out=$(run_gate "$D"); rc=$?
check "agent-instructions 缺 maxBytes → rc=2" 2 "$rc"
assert_failure "$out" required_row_config_missing

make_fixture "$D"
python3 - "$D/dsh/cordis.patch.yml" <<'PY'
import sys
p = sys.argv[1]; t = open(p, encoding="utf-8").read()
t = t.replace("""            name: '@deepseek-ai/dsh-tool-todo'
            config:
              allowParallelInProgress: false
""", """            name: '@deepseek-ai/dsh-tool-todo'
""")
open(p, "w", encoding="utf-8").write(t)
PY
out=$(run_gate "$D"); rc=$?
check "tool-todo 整块缺 config → rc=2" 2 "$rc"
assert_failure "$out" required_row_config_missing

echo "══ 4. skills 挂载 ══"
make_fixture "$D"
python3 - "$D/dsh/cordis.patch.yml" <<'PY'
import sys
p = sys.argv[1]; lines = open(p, encoding="utf-8").read().splitlines(True)
skip = False; out = []
for ln in lines:
    if ln.strip().startswith("- !!js process.getBuiltinModule"):
        skip = True
    if skip:
        if ln.rstrip().endswith(",'skills')") or ln.rstrip().endswith("'skills')"):
            skip = False
        continue
    out.append(ln)
open(p, "w", encoding="utf-8").writelines(out)
PY
out=$(run_gate "$D"); rc=$?
check "有技能但未挂载 customSkillDirs → rc=2" 2 "$rc"
assert_failure "$out" skills_not_mounted

make_fixture "$D"
python3 - "$D/dsh/package.json" "$D/dsh/cordis.patch.yml" <<'PY'
import sys
pkg, patch = sys.argv[1], sys.argv[2]
t = open(pkg, encoding="utf-8").read().replace("@cosight/agent-demo", "@cosight/agent-renamed")
open(pkg, "w", encoding="utf-8").write(t)
PY
out=$(run_gate "$D"); rc=$?
check "挂载解析的包与 package.json 不一致 → rc=2" 2 "$rc"
assert_failure "$out" skills_mount_wrong_package

make_fixture "$D"
python3 - "$D/dsh/skills/demo-skill/SKILL.md" <<'PY'
import sys
p = sys.argv[1]
open(p, "w", encoding="utf-8").write("---\ndescription: 缺 name\n---\n\n# demo\n")
PY
out=$(run_gate "$D"); rc=$?
check "技能 frontmatter 缺 name → rc=2" 2 "$rc"
assert_failure "$out" skill_name_invalid

echo "══ 5. package.json / patch 形态 ══"
make_fixture "$D"
printf '{not json' > "$D/dsh/package.json"
out=$(run_gate "$D"); rc=$?
check "package.json 非法 JSON → rc=2" 2 "$rc"
assert_failure "$out" invalid_json

make_fixture "$D"
python3 - "$D/dsh/package.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d["dsh"]["bundle"]["patch"] = "../../evil.yml"
json.dump(d, open(p, "w", encoding="utf-8"))
PY
out=$(run_gate "$D"); rc=$?
check "patch 路径逃逸 → rc=2" 2 "$rc"
assert_failure "$out" bundle_patch_escape

make_fixture "$D"
rm -f "$D/dsh/cordis.patch.yml"
out=$(run_gate "$D"); rc=$?
check "缺 cordis.patch.yml → rc=2" 2 "$rc"
assert_failure "$out" missing_file

echo "══ 6. 禁止产物 / Claude 残留（仅纯 dsh）══"
make_fixture "$D"; mkdir -p "$D/.claude/skills/foo"
out=$(run_gate "$D" --build-plan "$TMP/plan-dsh.md"); rc=$?
check "platforms=[dsh] 生成 .claude/skills → rc=2" 2 "$rc"
assert_failure "$out" forbidden_artifact

make_fixture "$D"; mkdir -p "$D/.claude/skills/foo"
out=$(run_gate "$D"); rc=$?
check "无 platforms 但 dsh/ 存在 → .claude/skills 不判 forbidden" 0 "$rc"

make_fixture "$D"
printf '\n参考 .claude/skills/rag-knowledge-search 的写法。\n' >> "$D/dsh/rules/style.md"
out=$(run_gate "$D"); rc=$?
check "dsh/rules 残留 .claude/skills → rc=2" 2 "$rc"
assert_failure "$out" claude_reference

make_fixture "$D"
printf '\nRead 后调用 TodoWrite 记录。\n' >> "$D/dsh/skills/demo-skill/SKILL.md"
out=$(run_gate "$D"); rc=$?
check "技能内残留 TodoWrite → rc=2" 2 "$rc"
assert_failure "$out" claude_reference

echo "══ 7. install.sh / README / CLAUDE.md ══"
make_fixture "$D"
printf '#!/usr/bin/env bash\nif then\n' > "$D/dsh/install.sh"
out=$(run_gate "$D"); rc=$?
check "install.sh 语法错误 → rc=2" 2 "$rc"
assert_failure "$out" install_script_invalid

make_fixture "$D"; rm -f "$D/dsh/install.sh"
out=$(run_gate "$D"); rc=$?
check "缺 install.sh → rc=2" 2 "$rc"
assert_failure "$out" missing_file

make_fixture "$D"; rm -f "$D/CLAUDE.md"
out=$(run_gate "$D"); rc=$?
check "缺 CLAUDE.md → rc=2" 2 "$rc"
assert_failure "$out" missing_file

make_fixture "$D"
python3 - "$D/dsh/README.md" <<'PY'
import sys
p = sys.argv[1]
open(p, "w", encoding="utf-8").write("# Demo\n\n## 安装\n\n./install.sh web\n")
PY
out=$(run_gate "$D"); rc=$?
check "README 无能力差异节 → PASS + concern" 0 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
cs={c.get('type') for c in d.get('concerns') or []}
assert d['verdict']=='PASS', d
assert 'readme_capability_section_missing' in cs, cs
" 2>/dev/null; then ok "concern 含 readme_capability_section_missing"; else bad "concern 异常: $out"; fi

echo "══ 8. g026 stdin 通道 ══"
make_fixture "$D"
out=$(echo "{\"output_dir\":\"$D\",\"build_plan\":\"$TMP/plan-dsh.md\"}" | bash "$G030" 2>&1); rc=$?
check "仅 stdin 提供 output_dir → PASS" 0 "$rc"
out=$(echo '{}' | bash "$G030" 2>&1); rc=$?
check "stdin 无 output_dir → rc=2" 2 "$rc"
assert_failure "$out" input_error

echo
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
