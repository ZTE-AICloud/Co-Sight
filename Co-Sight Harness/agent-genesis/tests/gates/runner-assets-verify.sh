#!/usr/bin/env bash
# 步 1.4 runner.assets 模板物化验证门（docs/plan/deterministic-gate-refactor.md 阶段一 1.4）
# 覆盖: 模板+变量→渲染产物正例 / 零变量模板 / copy 回归 / C8 畸形输入负例 ≥3 / C8-2 位置无关
# 用法: bash tests/gates/runner-assets-verify.sh   （在仓库根执行）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
G025="$REPO_ROOT/scripts/gates/g025-asset-copy.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi }
check_json() {
  if echo "$3" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert ($2), d" 2>/dev/null; then
    ok "$1"
  else
    bad "$1 —— got: $(echo "$3" | head -c 300)"
  fi
}

echo "══ 正例: 模板+变量→渲染产物 ══"
mkdir -p "$TMP/out"
cat > "$TMP/plan-ok.md" <<'EOF'
---
plan_version: "2.0"
mode: greenfield
template_variables:
  readiness_threshold: 58
  write_scope_dir: reports/
---

## 文件清单

```yaml
path: phase/gates/G003-readiness-score.md
type: other
generation: template
source: assets/templates/gates/G003-readiness-score.md
```

```yaml
path: .claude/settings.json
type: settings
generation: template
source: assets/templates/settings/settings.json.template
```

```yaml
path: .claude/rules/security.md
type: rule
generation: copy
source: knowledge/assets/rules/security.md
```
EOF
out=$(bash "$G025" --build-plan "$TMP/plan-ok.md" --output-dir "$TMP/out" 2>&1); rc=$?
check "模板物化+copy 混合 plan → PASS" 0 "$rc"
check_json "materialized_count == 2" "d.get('materialized_count')==2" "$out"
check_json "copied_count == 1" "d.get('copied_count')==1" "$out"
grep -q 'readiness_score >= 58' "$TMP/out/phase/gates/G003-readiness-score.md" && \
  ok "G003 渲染产物含变量替换值 (58)" || bad "G003 渲染产物未替换 readiness_threshold"
grep -q '{{readiness_threshold}}' "$TMP/out/phase/gates/G003-readiness-score.md" && \
  bad "G003 渲染产物残留 {{readiness_threshold}} 占位" || ok "G003 渲染产物无残留占位符"
python3 -I -c "import json; d=json.load(open('$TMP/out/.claude/settings.json')); assert d['permissions']['additionalDirectories']==['reports/'], d" && \
  ok "settings.json 物化产物为合法 JSON 且 write_scope_dir 已注入" || \
  bad "settings.json 物化产物 JSON 非法或变量未注入"
diff -q "$TMP/out/.claude/rules/security.md" "$REPO_ROOT/knowledge/assets/rules/security.md" >/dev/null && \
  ok "copy 条目回归: 逐字一致" || bad "copy 条目回归失败"

echo "══ 正例: 零变量模板（{{}} 字面量透传——内联载体, 不依赖 G005 资产）══"
# 载体说明: G005 模板已改无字样描述法（2026-10-15 自指矛盾修复）, 透传行为断言
# 改用内联 mktemp 模板——用例本意是测 g025 对零变量模板的透传行为, 不是测 G005 资产
mkdir -p "$TMP/out2" "$TMP/tpldir"
printf '# 内联零变量载体\n\n双花括号空形态: {{}}\n' > "$TMP/tpldir/zerovar.md"
cat > "$TMP/plan-zerovar.md" <<EOF
---
plan_version: "2.0"
mode: greenfield
template_variables: {}
---

\`\`\`yaml
path: docs/zerovar.md
type: other
generation: template
source: $TMP/tpldir/zerovar.md
\`\`\`
EOF
out=$(bash "$G025" --build-plan "$TMP/plan-zerovar.md" --output-dir "$TMP/out2" 2>&1); rc=$?
check "零变量模板 → PASS" 0 "$rc"
grep -q '内联零变量载体' "$TMP/out2/docs/zerovar.md" && \
  ok "渲染产物落地" || bad "渲染产物缺失"
grep -qF '{{}}' "$TMP/out2/docs/zerovar.md" && \
  ok "{{}} 字面量（非变量形态）原样透传" || bad "{{}} 字面量被误改"

echo "══ C8 负例: 畸形输入 → input_error ══"
mkdir -p "$TMP/out3"

# 负例1: template 条目缺 source
cat > "$TMP/plan-n1.md" <<'EOF'
---
plan_version: "2.0"
mode: greenfield
template_variables: {readiness_threshold: 58}
---

```yaml
path: phase/gates/G003-readiness-score.md
type: other
generation: template
```
EOF
out=$(bash "$G025" --build-plan "$TMP/plan-n1.md" --output-dir "$TMP/out3" 2>&1); rc=$?
check "负例1 template 缺 source → rc=2" 2 "$rc"
check_json "负例1 type=input_error" "any(f.get('type')=='input_error' for f in d['failures'])" "$out"

# 负例2: 模板含未声明变量
cat > "$TMP/plan-n2.md" <<'EOF'
---
plan_version: "2.0"
mode: greenfield
template_variables: {}
---

```yaml
path: phase/gates/G003-readiness-score.md
type: other
generation: template
source: assets/templates/gates/G003-readiness-score.md
```
EOF
out=$(bash "$G025" --build-plan "$TMP/plan-n2.md" --output-dir "$TMP/out3" 2>&1); rc=$?
check "负例2 未声明变量 → rc=2" 2 "$rc"
check_json "负例2 input_error 点名 undeclared 变量" "any(f.get('type')=='input_error' and 'readiness_threshold' in f.get('undeclared',[]) for f in d['failures'])" "$out"
[ -f "$TMP/out3/phase/gates/G003-readiness-score.md" ] && bad "负例2 不应产出半成品" || ok "负例2 无半成品落盘"

# 负例3: template_variables 非映射（list）
cat > "$TMP/plan-n3.md" <<'EOF'
---
plan_version: "2.0"
mode: greenfield
template_variables: [readiness_threshold]
---

```yaml
path: phase/gates/G003-readiness-score.md
type: other
generation: template
source: assets/templates/gates/G003-readiness-score.md
```
EOF
out=$(bash "$G025" --build-plan "$TMP/plan-n3.md" --output-dir "$TMP/out3" 2>&1); rc=$?
check "负例3 template_variables 非映射 → rc=2" 2 "$rc"
check_json "负例3 type=input_error" "any(f.get('type')=='input_error' and 'template_variables' in f.get('detail','') for f in d['failures'])" "$out"

# 负例4: 模板源文件缺失
cat > "$TMP/plan-n4.md" <<'EOF'
---
plan_version: "2.0"
mode: greenfield
template_variables: {}
---

```yaml
path: phase/gates/G00X.md
type: other
generation: template
source: assets/templates/gates/nonexistent.md
```
EOF
out=$(bash "$G025" --build-plan "$TMP/plan-n4.md" --output-dir "$TMP/out3" 2>&1); rc=$?
check "负例4 模板源缺失 → rc=2" 2 "$rc"
check_json "负例4 type=template_source_missing" "any(f.get('type')=='template_source_missing' for f in d['failures'])" "$out"

# 负例5: build-plan 缺失
out=$(bash "$G025" --build-plan "$TMP/none.md" --output-dir "$TMP/out3" 2>&1); rc=$?
check "负例5 build-plan 缺失 → rc=2" 2 "$rc"
check_json "负例5 type=input_error" "any(f.get('type')=='input_error' for f in d['failures'])" "$out"

# 负例6: output-dir 缺失
out=$(bash "$G025" --build-plan "$TMP/plan-ok.md" --output-dir "$TMP/no-such-dir" 2>&1); rc=$?
check "负例6 output-dir 缺失 → rc=2" 2 "$rc"
check_json "负例6 type=input_error" "any(f.get('type')=='input_error' for f in d['failures'])" "$out"

echo "══ C8-2 位置无关: 仓外目录执行 ══"
out=$(cd "$TMP" && bash "$G025" --build-plan "$TMP/plan-ok.md" --output-dir "$TMP/out" 2>&1); rc=$?
check "仓外目录（mktemp）执行 → PASS" 0 "$rc"

echo ""
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
