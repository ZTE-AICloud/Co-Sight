#!/usr/bin/env bash
# G029 知识库注入审计验证门
# 覆盖: 正常注入产物 PASS / workflow_id 被篡改→FAIL / 历史实现残留（旧服务名、
#       旧查询路径、旧鉴权变量）→FAIL / Agent API 契约（conversation_id、
#       Authorization Bearer）缺失→FAIL / MCP 残留→FAIL /
#       build-plan 声明 generate→FAIL、pre_staged→PASS /
#       manifest 缺失→fail-closed(FAIL, rc=2)
# 用法: bash tests/gates/g029-knowledge-injection-verify.sh   （在插件根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
G029="scripts/gates/g029-knowledge-injection-audit.sh"
WF="RAG_Workflow_780f"
SKILL=".claude/skills/rag-knowledge-search"

# ── 用真实注入器搭建产物（保证与被审计对象同源）──
mkdir -p "$TMP/out" "$TMP/work" "$TMP/in"
echo "{\"workflow_id\": \"$WF\"}" > "$TMP/in/knowledge.json"
if ! PYTHONPATH= python scripts/inject-input-assets.py \
      --input-dir "$TMP/in" --output-dir "$TMP/out" --work-dir "$TMP/work" >/dev/null; then
  echo "✗ 前置注入失败, 无法继续"; exit 1
fi
MANIFEST="$TMP/work/injected-assets.yaml"

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

echo "══ 1. 正常注入产物 ══"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "无 build-plan 时 PASS" 0 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='PASS' and d['checked_files']>=4, d
assert d['workflow_id']=='$WF', d
" 2>/dev/null; then
  ok "verdict=PASS 且往返 workflow_id 一致"
else
  bad "PASS 载荷异常: $out"
fi

echo "══ 2. workflow_id 字面量被篡改 → FAIL ══"
client="$TMP/out/$SKILL/scripts/rag_knowledge_search.py"
sed -i "s/$WF/RAG_Workflow_tampered/" "$client"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "篡改后 rc=2" 2 "$rc"
assert_failure "$out" workflow_id_mismatch
sed -i "s/RAG_Workflow_tampered/$WF/" "$client"

echo "══ 3. 历史实现残留（旧服务名/旧查询链路）→ FAIL ══"
printf '\n# old endpoint: zae-ragcomponentservice\n' >> "$client"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "残留后 rc=2" 2 "$rc"
assert_failure "$out" legacy_marker_found
sed -i '/old endpoint: zae-ragcomponentservice/d' "$client"

printf '\n# legacy path: /api/rkb/v1/query\n' >> "$client"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "旧查询路径残留 rc=2" 2 "$rc"
assert_failure "$out" legacy_marker_found
sed -i '/legacy path: \/api\/rkb\/v1\/query/d' "$client"

printf '\n# legacy auth: CO_KNOWLEDGE_AUTH_TOKEN\n' >> "$client"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "旧鉴权变量残留 rc=2" 2 "$rc"
assert_failure "$out" legacy_marker_found
sed -i '/legacy auth: CO_KNOWLEDGE_AUTH_TOKEN/d' "$client"

grep -q conversation_id "$client" || bad "客户端基线缺少 conversation_id"
sed -i 's/conversation_id/conversation_x/g' "$client"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "缺少 conversation_id rc=2" 2 "$rc"
assert_failure "$out" endpoint_invalid
sed -i 's/conversation_x/conversation_id/g' "$client"

sed -i 's/Authorization/Auth-Header/g' "$client"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "缺少 Authorization Bearer rc=2" 2 "$rc"
assert_failure "$out" endpoint_invalid
sed -i 's/Auth-Header/Authorization/g' "$client"

echo "══ 4. MCP 残留（skill 目录内出现 mcp.json）→ FAIL ══"
echo '{"mcpServers": {}}' > "$TMP/out/$SKILL/mcp.json"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "MCP 残留 rc=2" 2 "$rc"
assert_failure "$out" mcp_residue_found
rm -f "$TMP/out/$SKILL/mcp.json"

echo "══ 5. build-plan 对账 ══"
make_plan() { # make_plan <generation>
  {
    for f in SKILL.md scripts/execute.py scripts/rag_knowledge_search.py scripts/check_env.py; do
      printf -- '```yaml\npath: %s/%s\ngeneration: %s\nsource: %s/%s\n```\n\n' \
        "$SKILL" "$f" "$1" "$SKILL" "$f"
    done
  } > "$TMP/build-plan.md"
}
make_plan generate
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" --build-plan "$TMP/build-plan.md" </dev/null 2>&1); rc=$?
check "declaration=generate → rc=2" 2 "$rc"
assert_failure "$out" build_plan_generation_mismatch

make_plan pre_staged
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" --build-plan "$TMP/build-plan.md" </dev/null 2>&1); rc=$?
check "declaration=pre_staged → PASS" 0 "$rc"

: > "$TMP/empty-plan.md"
out=$(bash "$G029" --manifest "$MANIFEST" --output-dir "$TMP/out" --build-plan "$TMP/empty-plan.md" </dev/null 2>&1); rc=$?
check "build-plan 缺条目 → rc=2" 2 "$rc"
assert_failure "$out" build_plan_entry_missing

echo "══ 6. 输入缺失 fail-closed ══"
out=$(bash "$G029" --manifest "$TMP/absent.yaml" --output-dir "$TMP/out" </dev/null 2>&1); rc=$?
check "manifest 不存在 rc=2" 2 "$rc"
assert_failure "$out" input_error

out=$(echo '{}' | bash "$G029" 2>&1); rc=$?
check "无参数 rc=2" 2 "$rc"
assert_failure "$out" input_error

echo "══ 7. both 平台（双落点）══"
BOTH="$TMP/both"
mkdir -p "$BOTH/out" "$BOTH/work" "$BOTH/in"
echo "{\"workflow_id\": \"$WF\"}" > "$BOTH/in/knowledge.json"
if ! PYTHONPATH= python scripts/inject-input-assets.py \
      --input-dir "$BOTH/in" --output-dir "$BOTH/out" --work-dir "$BOTH/work" \
      --target-platform both >/dev/null; then
  bad "both 前置注入失败"
else
  out=$(bash "$G029" --manifest "$BOTH/work/injected-assets.yaml" --output-dir "$BOTH/out" </dev/null 2>&1); rc=$?
  check "both 双落点 PASS" 0 "$rc"
  if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='PASS' and d['checked_files']==8, d
" 2>/dev/null; then
    ok "checked_files=8（两侧各 4 个文件）"
  else
    bad "both 载荷异常: $out"
  fi

  dsh_client="$BOTH/out/dsh/skills/rag-knowledge-search/scripts/rag_knowledge_search.py"
  sed -i "s/$WF/RAG_Workflow_tampered/" "$dsh_client"
  out=$(bash "$G029" --manifest "$BOTH/work/injected-assets.yaml" --output-dir "$BOTH/out" </dev/null 2>&1); rc=$?
  check "仅 dsh 侧被篡改 rc=2" 2 "$rc"
  assert_failure "$out" workflow_id_mismatch
  sed -i "s/RAG_Workflow_tampered/$WF/" "$dsh_client"

  # 旧清单（只有 relative_dir）兼容
  python3 - "$BOTH/work/injected-assets.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
m = yaml.safe_load(open(p, encoding="utf-8"))
k = m["knowledge"]
k.pop("relative_dirs", None)
k["relative_dir"] = ".claude/skills/rag-knowledge-search"
yaml.safe_dump(m, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY
  out=$(bash "$G029" --manifest "$BOTH/work/injected-assets.yaml" --output-dir "$BOTH/out" </dev/null 2>&1); rc=$?
  check "旧清单 relative_dir 兼容 rc=2（另一侧文件落在白名单外）" 2 "$rc"
  assert_failure "$out" file_outside_skill_dir
fi

echo
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
