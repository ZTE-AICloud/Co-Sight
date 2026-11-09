#!/usr/bin/env bash
# g023 cross 模式「脚本内静态路径拼接字面量」扫描验证门（contract-drift-fix-plan F5 锚点）
# 覆盖: join 链缺失→FAIL 点名字面量 / join 链存在→无 finding / 绝对路径跳过 /
#       动态段($ {})跳过 / 非路径 join 跳过 / 修复后翻转 PASS / 无脚本产物 no-op
# 用法: bash tests/gates/g023-cross-path-scan-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
G023="scripts/gates/g023-invariants.sh"

# ── 产物搭建（事故形态: join(dirname(__file__), "templates", "report.html.template") 断链）──
mkdir -p "$TMP/prod/scripts/lib"
cat > "$TMP/prod/scripts/scan.py" <<'EOF'
import os
TPL = os.path.join(os.path.dirname(__file__), "templates", "report.html.template")
EOF
cat > "$TMP/prod/scripts/ok.py" <<'EOF'
import os
HELPER = os.path.join(os.path.dirname(__file__), "lib", "helper.py")
EOF
cat > "$TMP/prod/scripts/abs.py" <<'EOF'
import os
X = os.path.join("/etc", "absent.xyz")
EOF
cat > "$TMP/prod/scripts/dyn.sh" <<'EOF'
#!/bin/bash
cat "$HERE/templates/x.py" > /dev/null
EOF
cat > "$TMP/prod/scripts/nonpath.py" <<'EOF'
TAG = os.path.join("alpha", "bravo")
EOF
touch "$TMP/prod/scripts/lib/helper.py"

mk_plan() { # mk_plan <输出路径>（仅声明脚本产物）
  {
    for f in scripts/scan.py scripts/ok.py scripts/abs.py scripts/dyn.sh scripts/nonpath.py; do
      printf -- '```yaml\npath: %s\ntype: script\n```\n\n' "$f"
    done
  } > "$1"
}

echo "══ 断链拦截: join 链缺失 → FAIL 且点名字面量 ══"
mk_plan "$TMP/bp.md"
out=$(bash "$G023" --mode cross --build-plan "$TMP/bp.md" --output-dir "$TMP/prod" </dev/null 2>&1); rc=$?
check "cross rc=2" 2 "$rc"
if echo "$out" | python3 -I -c "
import json,sys
d=json.load(sys.stdin)
fs=d.get('findings') or []
assert d['verdict']=='FAIL' and len(fs)==1, fs
assert fs[0]=='脚本路径: scripts/scan.py → templates/report.html.template 不存在', fs[0]
" 2>/dev/null; then
  ok "恰 1 条 finding, 点名 scripts/scan.py → templates/report.html.template（其余四脚本零误报）"
else
  bad "finding 不符 —— got: $out"
fi

echo "══ 修复翻转: 补上缺失文件 → PASS ══"
mkdir -p "$TMP/prod/scripts/templates" && touch "$TMP/prod/scripts/templates/report.html.template"
out=$(bash "$G023" --mode cross --build-plan "$TMP/bp.md" --output-dir "$TMP/prod" </dev/null 2>&1); rc=$?
check "修复后 cross rc=0" 0 "$rc"

echo "══ 无脚本产物: 第 4 节 no-op ══"
mkdir -p "$TMP/prod2"
printf 'x\n' > "$TMP/prod2/CLAUDE.md"
printf -- '```yaml\npath: CLAUDE.md\ntype: claude_md\n```\n' > "$TMP/bp2.md"
out=$(bash "$G023" --mode cross --build-plan "$TMP/bp2.md" --output-dir "$TMP/prod2" </dev/null 2>&1); rc=$?
check "纯文档产物 cross rc=0（脚本扫描不误伤）" 0 "$rc"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
