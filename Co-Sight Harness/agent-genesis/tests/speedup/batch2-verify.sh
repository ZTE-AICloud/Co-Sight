#!/usr/bin/env bash
# 提速方案批次 2 验证门（OPT-2 批内并行 Write——M8 批次闭合检查）
# 用法: bash tests/speedup/batch2-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
has() { # has <描述> <finding子串> <json>
  if echo "$3" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
fs=[f['check'] for r in d['results'] for f in r.get('findings',[])]
assert any('$2' in x for x in fs), fs" 2>/dev/null; then ok "$1"; else bad "$1 —— findings: $(echo "$3" | python3 -I -c "import json,sys; print([f['check'] for r in json.load(sys.stdin)['results'] for f in r.get('findings',[])])" 2>/dev/null)"; fi
}
none_has() { # none_has <描述> <finding子串> <json>
  if echo "$3" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
fs=[f['check'] for r in d['results'] for f in r.get('findings',[])]
assert not any('$2' in x for x in fs), fs" 2>/dev/null; then ok "$1"; else bad "$1"; fi
}

# mk_bp2 <batches-yaml 或 "-"> <文件规格: path:deps[:copy] 多组用 | 分隔>
mk_bp2() {
  local batches="$1" filespec="$2"
  python3 -I - "$TMP/bp2.md" "$batches" "$filespec" <<'PY'
import sys
out, batches, filespec = sys.argv[1], sys.argv[2], sys.argv[3]
brief = "步骤序列表承载固定执行顺序：输入完整性检查→三维并行安全扫描→独立复核→结构化报告输出，每步声明输入输出契约与自查项"
file_blocks = []
for spec in filter(None, filespec.split("|")):
    parts = spec.split(":")
    path, deps = parts[0], parts[1] if len(parts) > 1 and parts[1] else ""
    copy = len(parts) > 2 and parts[2] == "copy"
    if copy:
        file_blocks.append(f"""
```yaml
file:
  path: {path}
  type: other
  generation: copy
  source: assets/agent-definitions/critic.md
```
""")
    else:
        deps_yaml = f"[{deps}]" if deps else "[]"
        file_blocks.append(f"""
```yaml
file:
  path: {path}
  type: workflow_md
  deps: {deps_yaml}
  read_first: []
  materializes: [W1]
  brief: "{brief}（{path}）"
  invariants: []
  acceptance: []
  anti_patterns: []
```
""")
batches_yaml = ""
if batches != "-":
    batches_yaml = f"batches: {batches}\n"
doc = f"""---
plan_version: "2.0"
mode: greenfield
{batches_yaml}selected_patterns: [W1]
---

## 决策物化表

```yaml
materialization:
  - {{pattern_id: W1, target_files: [a.md]}}
```

## 文件清单

{''.join(file_blocks)}
"""
open(out, "w", encoding="utf-8").write(doc)
PY
}

cat > "$TMP/decision.md" <<'EOF'
---
decision_id: t-batch2
timestamp: "2026-10-12T00:00:00Z"
pipeline: agent-creation
selected_patterns: [W1]
build_type:
  type: single
---

## 结构决策

单 Agent，无 SubAgent。

## 决策物化

| W1 | 步骤序列表承载固定执行顺序（输入检查→处理→报告） | — |
EOF
run() { python3 scripts/validate-plan-v2.py --decision "$TMP/decision.md" --build-plan "$TMP/bp2.md" 2>&1; }

echo "══ M8 批次闭合检查 ══"
mk_bp2 "[[a.md],[b.md]]" "a.md|b.md:b.md-dep-a"
out=$(run); rc=$?
check "合法拓扑分层（deps 跨批）→ PASS" 0 "$rc"
none_has "无 M8 finding" "M8_" "$out"

mk_bp2 "[[a.md,b.md]]" "a.md|b.md:a.md"
out=$(run); rc=$?
check "交叉依赖同批 → FAIL" 1 "$rc"
has "报 M8_intra_batch_dep" "M8_intra_batch_dep: b.md 依赖同批文件 a.md" "$out"

mk_bp2 "[[a.md]]" "a.md|b.md:"
out=$(run); rc=$?
check "generate 文件漏派 → FAIL" 1 "$rc"
has "报 M8_file_not_batched" "M8_file_not_batched: generate 文件 b.md" "$out"

mk_bp2 "[[a.md,d.md]]" "a.md|d.md::copy"
out=$(run); rc=$?
check "copy 条目入批 → FAIL" 1 "$rc"
has "报 M8_copy_in_batch" "M8_copy_in_batch: copy 条目 d.md" "$out"

mk_bp2 "[[a.md,ghost.md]]" "a.md"
out=$(run); rc=$?
check "批次含未声明文件 → FAIL" 1 "$rc"
has "报 M8_unknown_file" "M8_unknown_file: 批次 0 含未声明文件 ghost.md" "$out"

mk_bp2 "-" "a.md|b.md:"
out=$(run); rc=$?
check "缺省 batches → PASS（兼容存量，M8 跳过）" 0 "$rc"

echo "══ 回归: bash -n/py_compile + registry + 既有三套件 ══"
syn=0
for f in scripts/gates/*.sh scripts/check-gate-registry.sh; do bash -n "$f" 2>/dev/null || { bad "bash -n: $f"; syn=1; }; done
python3 -m py_compile scripts/validate-plan-v2.py 2>/dev/null || { bad "py_compile: validate-plan-v2.py"; syn=1; }
[ "$syn" -eq 0 ] && ok "bash -n / py_compile 全链"
bash scripts/check-gate-registry.sh >/dev/null 2>&1 && ok "check-gate-registry PASS" || bad "check-gate-registry FAIL"
bash tests/speedup/batch1-verify.sh >/dev/null 2>&1 && ok "批次 1 套件回归 21/21" || bad "批次 1 套件回归失败"
bash tests/gates/stage1-verify.sh >/dev/null 2>&1 && ok "gate 治理阶段 1 套件回归" || bad "stage1 套件回归失败"
bash tests/gates/stage3-verify.sh >/dev/null 2>&1 && ok "gate 治理阶段 3 套件回归" || bad "stage3 套件回归失败"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
