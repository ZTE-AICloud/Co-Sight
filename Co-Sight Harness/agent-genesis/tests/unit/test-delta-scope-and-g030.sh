#!/usr/bin/env bash
# tests/unit/test-delta-scope-and-g030.sh
# V4 验证（host-context 方案 §6 V4）:
#   A. check-delta-scope 新增文件语义:
#      A1 快照树+新增1文件+allowlist 含 → PASS
#      A2 同场景 allowlist 缺该文件     → FAIL scope_violation
#      A3 修改既有文件+allowlist 缺     → FAIL（现状行为回归确认）
#   B. G030 直调（形态④ dsh 分支后测）:
#      B1 合法 bundle fixture → PASS
#      B2 缺 cordis.patch.yml → FAIL
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DELTA="$SCRIPT_DIR/../../scripts/check-delta-scope.sh"
G030="$SCRIPT_DIR/../../scripts/gates/g030-dsh-output.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS  $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL  $1 — $2"; }

# ── A. check-delta-scope ──
d="$TMP/a1"; mkdir -p "$d/snapshot/sub" "$d/target/sub"
echo "old" > "$d/snapshot/sub/keep.md";  echo "old" > "$d/target/sub/keep.md"
echo "new" > "$d/target/sub/added.md"            # 新增 1 文件
printf 'sub/added.md\n' > "$d/allow.txt"
out=$(bash "$DELTA" --snapshot "$d/snapshot" --target "$d/target" --allowlist "$d/allow.txt" 2>&1) \
  && echo "$out" | grep -q '"verdict": "PASS"' && ok "A1 新增+allowlist含→PASS" || bad "A1" "$out"

printf '# only other\n' > "$d/allow2.txt"
out=$(bash "$DELTA" --snapshot "$d/snapshot" --target "$d/target" --allowlist "$d/allow2.txt" 2>&1) \
  && bad "A2" "应当 FAIL: $out" || echo "$out" | grep -q 'scope_violation' \
  && ok "A2 新增+allowlist缺→FAIL scope_violation" || bad "A2" "$out"

echo "changed" > "$d/target/sub/keep.md"          # 改既有文件, 不在 allowlist
out=$(bash "$DELTA" --snapshot "$d/snapshot" --target "$d/target" --allowlist "$d/allow.txt" 2>&1) \
  && bad "A3" "应当 FAIL: $out" || echo "$out" | grep -q 'scope_violation' \
  && ok "A3 改既有+allowlist缺→FAIL(回归)" || bad "A3" "$out"

# ── B. G030 ──
mk_bundle() { # mk_bundle <dir> <with_patch: 0|1>  # 形态依据 assets/templates/dsh + dsh.yaml preset 骨架
  local d="$1" wp="$2"
  mkdir -p "$d/dsh"
  cat > "$d/dsh/package.json" <<'EOF'
{
  "name": "ctx-test-bundle",
  "version": "1.0.0",
  "type": "module",
  "dsh": {
    "bundle": {
      "patch": "./cordis.patch.yml"
    }
  }
}
EOF
  [ "$wp" = "1" ] && cat > "$d/dsh/cordis.patch.yml" <<'EOF'
- insert:
    - id: preset-ctx-test
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: ctx-test
        name: 语境测试
        description: 测试用 preset
        order: 50
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config:
              persona: |
                你是测试助手。
          - id: agent-instructions
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
          - id: tool-subagent-helper
            name: '@deepseek-ai/dsh-tool-subagent'
            config:
              provider: spawn
              toolName: subagent_helper
              maxDepth: 2
              persona: |
                <role>辅助校验角色。</role>
EOF
  echo '#!/usr/bin/env bash' > "$d/dsh/install.sh"
  printf '# README — ctx-test bundle\n\n## 能力差异\n无 .claude 原生等价物, 详见 dsh.yaml。\n' > "$d/dsh/README.md"
  printf '# ctx-test agent 运行时入口\n\n本文件为 DSH agent-instructions 读取的宿主目录说明, 占位正文。\n' > "$d/CLAUDE.md"
}

d="$TMP/b1"; mk_bundle "$d" 1
out=$(bash "$G030" --output-dir "$d" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "B1 合法 bundle→PASS" || bad "B1" "$out"

d="$TMP/b2"; mk_bundle "$d" 0
out=$(bash "$G030" --output-dir "$d" 2>&1); rc=$?
[ $rc -eq 2 ] && ok "B2 缺 cordis.patch.yml→FAIL" || bad "B2" "rc=$rc $out"

echo "----"
echo "V4-delta/G030 结果: PASS=$PASS FAIL=$FAIL"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 2)
