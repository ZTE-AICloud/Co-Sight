#!/usr/bin/env bash
# DSH 产物流程验证（Step 1b 注入 → g026 批跑 G029 + G030）
# 覆盖:
#   1. both 平台：两侧注入 + 合法 bundle → g026 PASS
#   2. dsh 残留 Claude 引用 → g026 FAIL(3) 且 failures 含 claude_reference
#   3. 纯 dsh：无 .claude 产物 → PASS；出现 .claude/settings.json → FAIL(3)
#   4. platforms=[dsh] 但缺 dsh/ → FAIL(3) missing_dir
# 用法: bash tests/flow/dsh-output-verify.sh   （在插件根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
G026="scripts/gates/g026-batch-gates.sh"
INJECT="scripts/inject-input-assets.py"
WF="RAG_Workflow_780f"

build_bundle() { # build_bundle <out_dir> <pkg_name>
  local root="$1" pkg="$2"
  mkdir -p "$root/dsh/skills" "$root/dsh/rules"
  printf '# Demo Agent\n\n测试用。\n' > "$root/CLAUDE.md"
  cat > "$root/dsh/package.json" <<JSON
{
  "name": "$pkg",
  "version": "1.0.0",
  "type": "module",
  "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}
}
JSON
  cat > "$root/dsh/cordis.patch.yml" <<YAML
- insert:
    - id: preset-demo
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: demo
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config:
              prefix: 你是 Demo Agent。
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config:
              customSkillDirs:
                - !!js process.getBuiltinModule('node:path').join(
                    process.getBuiltinModule('node:path').dirname(
                      process.getBuiltinModule('node:module')
                        .createRequire(baseUrl).resolve('$pkg/package.json')),
                    'skills')
          - id: tool-subagent-reviewer
            name: '@deepseek-ai/dsh-tool-subagent'
            config:
              provider: spawn
              toolName: subagent_reviewer
              persona: 你是审查者。
YAML
  cat > "$root/dsh/install.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
PROFILE="${1:-web}"
dsh plugin --profile "$PROFILE" add "$(cd "$(dirname "$0")" && pwd)"
SH
  cat > "$root/dsh/README.md" <<'MD'
# Demo Agent

## 安装

在本目录执行 `./install.sh web`，重启 dsh 后在 UI 选择 Demo Agent。

## 使用

与 Agent 对话即可。

## 能力差异

DSH 与 Claude Code 的能力不完全对等：

- 无 settings.json 等价物：权限与工具开关改由 preset plugins 行声明
- hooks 不生成：需要时改用技能显式调用
- 子代理通过 preset 内 tool-subagent 行提供，不再依赖 agents/ 目录
MD
  printf '# 规则\n\n规则文件在 dsh/rules/，按需 read。\n' > "$root/dsh/rules/style.md"
}

make_plan() { # make_plan <file> <platforms> <manifest>
  local plan="$1" platforms="$2" manifest="$3"
  {
    printf -- '---\nplatforms: [%s]\n---\n\n# build plan\n\n' "$platforms"
    python3 - "$manifest" <<'PY'
import sys, yaml
m = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for path in m["knowledge"]["files"]:
    print("```yaml")
    print(f"path: {path}")
    print("generation: pre_staged")
    print(f"source: {path}")
    print("```")
    print()
PY
  } > "$plan"
}

run_batch() { # run_batch <gates-json> <out> <plan> <skills_dir> <rules_dir> <manifest> <excluded-json>
  bash "$G026" --input "{\"gates\":$1,\"profile\":\"agent-exit\",\"build_plan\":\"$3\",\"output_dir\":\"$2\",\"target\":\"$2\",\"work_dir\":\"$TMP/work\",\"skills_dir\":\"$4\",\"rules_dir\":\"$5\",\"manifest\":\"$6\",\"excluded_paths\":$7}" </dev/null 2>&1
}

echo "══ 1. both 平台：两侧注入 + 合法 bundle ══"
OUT="$TMP/both"
mkdir -p "$OUT" "$TMP/work" "$TMP/in"
echo "{\"workflow_id\": \"$WF\"}" > "$TMP/in/knowledge.json"
if ! PYTHONPATH= python "$INJECT" --input-dir "$TMP/in" --output-dir "$OUT" \
      --work-dir "$TMP/work" --target-platform both >/dev/null; then
  echo "✗ 前置注入失败"; exit 1
fi
build_bundle "$OUT" "@cosight/agent-demo"
make_plan "$TMP/plan-both.md" both "$TMP/work/injected-assets.yaml"
out=$(run_batch '["gate.knowledge.injection","gate.dsh.output"]' "$OUT" "$TMP/plan-both.md" \
  "$OUT/.claude/skills" "$OUT/.claude/rules" "$TMP/work/injected-assets.yaml" \
  '[".claude/skills/rag-knowledge-search","dsh/skills/rag-knowledge-search"]'); rc=$?
check "g026 合并 PASS" 0 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='PASS', d
assert not d['failures'], d
" 2>/dev/null; then ok "无 failures"; else bad "合并载荷异常: $out"; fi
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
assert d['passed']==2 and d['failed']==0, d
" 2>/dev/null; then ok "两个子 gate 均通过"; else bad "子 gate 计数异常: $out"; fi

echo "══ 2. dsh 侧残留 Claude 引用 → FAIL ══"
printf '\n参考 .claude/skills/rag-knowledge-search 的写法。\n' >> "$OUT/dsh/rules/style.md"
out=$(run_batch '["gate.knowledge.injection","gate.dsh.output"]' "$OUT" "$TMP/plan-both.md" \
  "$OUT/.claude/skills" "$OUT/.claude/rules" "$TMP/work/injected-assets.yaml" \
  '[".claude/skills/rag-knowledge-search","dsh/skills/rag-knowledge-search"]'); rc=$?
check "合并 FAIL" 3 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
types={f.get('type') for f in d.get('failures') or []}
assert d['verdict']=='FAIL' and 'claude_reference' in types, d
" 2>/dev/null; then ok "failure 含 claude_reference"; else bad "失败载荷异常: $out"; fi

echo "══ 3. 纯 dsh 平台 ══"
PURE="$TMP/pure"
mkdir -p "$PURE" "$TMP/work-pure" "$TMP/in-pure"
echo "{\"workflow_id\": \"$WF\"}" > "$TMP/in-pure/knowledge.json"
if ! PYTHONPATH= python "$INJECT" --input-dir "$TMP/in-pure" --output-dir "$PURE" \
      --work-dir "$TMP/work-pure" --target-platform dsh >/dev/null; then
  echo "✗ 纯 dsh 前置注入失败"; exit 1
fi
build_bundle "$PURE" "@cosight/agent-pure"
make_plan "$TMP/plan-dsh.md" dsh "$TMP/work-pure/injected-assets.yaml"
out=$(run_batch '["gate.knowledge.injection","gate.dsh.output"]' "$PURE" "$TMP/plan-dsh.md" \
  "$PURE/dsh/skills" "$PURE/dsh/rules" "$TMP/work-pure/injected-assets.yaml" \
  '["dsh/skills/rag-knowledge-search"]'); rc=$?
check "纯 dsh g026 PASS" 0 "$rc"

mkdir -p "$PURE/.claude"
printf '{}\n' > "$PURE/.claude/settings.json"
out=$(run_batch '["gate.knowledge.injection","gate.dsh.output"]' "$PURE" "$TMP/plan-dsh.md" \
  "$PURE/dsh/skills" "$PURE/dsh/rules" "$TMP/work-pure/injected-assets.yaml" \
  '["dsh/skills/rag-knowledge-search"]'); rc=$?
check "纯 dsh 出现 .claude/settings.json → FAIL" 3 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
types={f.get('type') for f in d.get('failures') or []}
assert 'forbidden_artifact' in types, d
" 2>/dev/null; then ok "failure 含 forbidden_artifact"; else bad "失败载荷异常: $out"; fi
rm -rf "$PURE/.claude"

echo "══ 4. platforms=[dsh] 但缺 dsh/ ══"
EMPTY="$TMP/empty"
mkdir -p "$EMPTY"
make_plan "$TMP/plan-empty.md" dsh "$TMP/work-pure/injected-assets.yaml"
out=$(bash "$G026" --input "{\"gates\":[\"gate.dsh.output\"],\"profile\":\"agent-exit\",\"build_plan\":\"$TMP/plan-empty.md\",\"output_dir\":\"$EMPTY\",\"target\":\"$EMPTY\",\"work_dir\":\"$TMP/work\"}" </dev/null 2>&1); rc=$?
check "g026 FAIL" 3 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
types={f.get('type') for f in d.get('failures') or []}
assert 'missing_dir' in types, d
" 2>/dev/null; then ok "failure 含 missing_dir"; else bad "失败载荷异常: $out"; fi

echo
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
