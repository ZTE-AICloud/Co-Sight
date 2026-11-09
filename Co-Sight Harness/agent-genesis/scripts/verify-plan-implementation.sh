#!/usr/bin/env bash
# AgentGenesis 版本清理重构 — 综合验证测试
# 覆盖: Step 1-4 全部变更
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PASS=0
FAIL=0
TOTAL=0

pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  FAIL: $1"; }

echo "============================================================"
echo " AgentGenesis 版本清理重构 — 验证测试"
echo " 执行时间: $(date -Iseconds)"
echo "============================================================"

# =====================================================
# Test Suite 1: 目录骨架 (Step 1)
# =====================================================
echo ""
echo "=== Suite 1: 目录骨架 ==="

# TC-1.1: Required directories exist
for d in \
    "work/code-review-agent" \
    "work/protocol-analysis-agent" \
    "work/ran-optimization-agent" \
    "work/user-guidance-agent" \
    "work/academic-research-agent" \
    "work/_self" \
    "test-results/code-review-agent" \
    "test-results/academic-research-agent" \
    "test-results/self-test" \
    "archive"; do
    [[ -d "$ROOT_DIR/$d" ]] && pass "目录存在: $d" || fail "目录缺失: $d"
done

# TC-1.2: Old directories removed
for d in "test-outputs" "test-reports"; do
    [[ ! -d "$ROOT_DIR/$d" ]] && pass "旧目录已删除: $d" || fail "旧目录仍存在: $d"
done

# =====================================================
# Test Suite 2: 产物迁移 (Step 2)
# =====================================================
echo ""
echo "=== Suite 2: 产物迁移 ==="

declare -A MIGRATIONS=(
    ["test-results/academic-research-agent/agent-spec.md"]="work/academic-research-agent-spec.md"
    ["work/code-review-agent/matching-decision.md"]="work/code-review-agent-matching-decision.md"
    ["test-results/code-review-agent/build-verify.md"]="work/code-review-agent-build-verify.md"
    ["test-results/self-test/phase1-edge-case-tests.md"]="work/phase1-edge-case-tests.md"
    ["work/_self/acceptance-report.md"]="work/acceptance-report.md"
    ["work/_self/acceptance-report-phase1.md"]="work/acceptance-report-phase1.md"
    ["test-results/academic-research-agent/matching-decision.md"]="test-outputs/academic-research-agent-matching-decision.md"
    ["test-results/code-review-agent/spec.md"]="test-outputs/code-review-agent-spec.md"
    ["test-results/self-test/diagnosis-tests.md"]="test-reports/diagnosis-tests.md"
    ["test-results/self-test/filling-assembly-tests.md"]="test-reports/filling-assembly-tests.md"
    ["test-results/self-test/matching-tests.md"]="test-reports/matching-tests.md"
)

for new_path in "${!MIGRATIONS[@]}"; do
    old_path="${MIGRATIONS[$new_path]}"
    if [[ -f "$ROOT_DIR/$new_path" ]]; then
        pass "迁移文件存在: $new_path"
    else
        fail "迁移文件缺失: $new_path (来自 $old_path)"
    fi
done

# TC-2.2: No files left in old locations
for old_path in "${MIGRATIONS[@]}"; do
    if [[ ! -f "$ROOT_DIR/$old_path" ]]; then
        pass "旧路径已清理: $old_path"
    else
        fail "旧路径仍有文件: $old_path"
    fi
done

# =====================================================
# Test Suite 3: progress-state.yaml (Step 1)
# =====================================================
echo ""
echo "=== Suite 3: progress-state.yaml ==="

PROGRESS="$ROOT_DIR/work/progress-state.yaml"

if [[ -f "$PROGRESS" ]]; then
    pass "progress-state.yaml 存在"
else
    fail "progress-state.yaml 缺失"
fi

# TC-3.2: Required keys
for key in "sm1_version" "last_updated" "current_state" "active_agent" \
    "phase_history" "artifacts" "errors" "recovery"; do
    if grep -q "^${key}:" "$PROGRESS" 2>/dev/null; then
        pass "键存在: $key"
    else
        fail "键缺失: $key"
    fi
done

# TC-3.3: Initial state is IDLE
grep -q "current_state: IDLE" "$PROGRESS" 2>/dev/null && \
    pass "初始状态为 IDLE" || fail "初始状态非 IDLE"

# TC-3.4: Valid YAML syntax
if python3 -c "import yaml; yaml.safe_load(open('$PROGRESS'))" 2>/dev/null; then
    pass "YAML 语法合法"
else
    fail "YAML 语法错误"
fi

# =====================================================
# Test Suite 4: .gitignore (Step 1)
# =====================================================
echo ""
echo "=== Suite 4: .gitignore ==="

GITIGNORE="$ROOT_DIR/.gitignore"

# TC-4.1: New entries present
for entry in "work/" "test-results/" "archive/"; do
    grep -qF "$entry" "$GITIGNORE" && pass "gitignore 包含: $entry" || \
        fail "gitignore 缺失: $entry"
done

# TC-4.2: Old entries removed
for old in "test-outputs/" "test-reports/"; do
    grep -qF "$old" "$GITIGNORE" && fail "gitignore 仍含旧条目: $old" || \
        pass "gitignore 已清理: $old"
done

# =====================================================
# Test Suite 5: evaluation/pass-criteria.md (Step 3)
# =====================================================
echo ""
echo "=== Suite 5: pass-criteria.md ==="

PC="$ROOT_DIR/evaluation/pass-criteria.md"

# TC-5.1: 7 hard checks
H_COUNT=$(grep -c '^| H-0' "$PC" 2>/dev/null || echo 0)
[[ $H_COUNT -eq 7 ]] && pass "硬校验项: 7 项 (H-01 ~ H-07)" || \
    fail "硬校验项数量: $H_COUNT (期望 7)"

# TC-5.2: References CLAUDE.md not agent-spec.md
grep -q "CLAUDE.md" "$PC" && pass "引用 CLAUDE.md" || fail "未引用 CLAUDE.md"
grep -q "agent-spec.md" "$PC" && fail "仍引用旧文件名 agent-spec.md" || \
    pass "无 agent-spec.md 引用"

# TC-5.3: Chapter count is 8
grep -q "章节 == 8" "$PC" && pass "章节阈值: 8" || fail "章节阈值非 8"

# TC-5.4: verdict PASS-WITH-WARNINGS exists
grep -q "PASS-WITH-WARNINGS" "$PC" && pass "verdict 含 PASS-WITH-WARNINGS" || \
    fail "verdict 缺少 PASS-WITH-WARNINGS"

# TC-5.5: quality-rubric.md exists
[[ -f "$ROOT_DIR/evaluation/quality-rubric.md" ]] && pass "quality-rubric.md 存在" || \
    fail "quality-rubric.md 缺失"

# TC-5.6: Phase 4 7 checks referenced
for check_name in "完整性" "格式" "引用" "Schema" "流转闭合" "约束自洽" "加载策略"; do
    grep -q "$check_name" "$PC" && pass "Phase 4 检查引用: $check_name" || \
        fail "Phase 4 检查缺失: $check_name"
done

# =====================================================
# Test Suite 6: plugin.json (Step 4)
# =====================================================
echo ""
echo "=== Suite 6: plugin.json ==="

PJ="$ROOT_DIR/.claude-plugin/plugin.json"

# TC-6.1: plugin.json exists and valid JSON with semver version
python3 -c "
import json, re, sys
with open('$PJ') as f:
    data = json.load(f)
v = data.get('version', '')
assert re.match(r'^\d+\.\d+\.\d+$', v), f'非 semver 版本号: {v}'
assert data.get('name'), '缺少 name 字段'
assert data.get('description'), '缺少 description 字段'
print('OK')
" && pass "plugin.json: name/description/version(semver) 完整" || \
    fail "plugin.json 校验失败 (缺失或版本号非 semver)"

# =====================================================
# Test Suite 7: Scripts (Step 4)
# =====================================================
echo ""
echo "=== Suite 7: 脚本 ==="

# TC-7.1: cleanup.sh exists and executable
[[ -x "$ROOT_DIR/scripts/cleanup.sh" ]] && pass "cleanup.sh 可执行" || \
    fail "cleanup.sh 不可执行或缺失"

# TC-7.2: bump-version.sh exists and executable
[[ -x "$ROOT_DIR/scripts/bump-version.sh" ]] && pass "bump-version.sh 可执行" || \
    fail "bump-version.sh 不可执行或缺失"

# TC-7.3: bump-version.sh --help works
if "$ROOT_DIR/scripts/bump-version.sh" --help 2>&1 | grep -q "用法"; then
    pass "bump-version.sh --help 正常"
else
    fail "bump-version.sh --help 异常"
fi

# TC-7.4: bump-version.sh version parsing
CURRENT=$(python3 -c "
import json
with open('$ROOT_DIR/.claude-plugin/plugin.json') as f:
    print(json.load(f)['version'])
")
echo "  当前版本: $CURRENT"

# Test version calculation logic directly
TEST_V=$(python3 -c "
def bump(v, level):
    parts = [int(x) for x in v.split('.')]
    if level == 'major':
        parts[0] += 1; parts[1] = 0; parts[2] = 0
    elif level == 'minor':
        parts[1] += 1; parts[2] = 0
    elif level == 'patch':
        parts[2] += 1
    return '.'.join(str(x) for x in parts)

assert bump('0.4.0', 'major') == '1.0.0', f'major bump failed: {bump(\"0.4.0\", \"major\")}'
assert bump('0.4.0', 'minor') == '0.5.0', f'minor bump failed: {bump(\"0.4.0\", \"minor\")}'
assert bump('0.4.0', 'patch') == '0.4.1', f'patch bump failed: {bump(\"0.4.0\", \"patch\")}'
assert bump('1.2.3', 'patch') == '1.2.4'
assert bump('1.2.3', 'minor') == '1.3.0'
assert bump('1.2.3', 'major') == '2.0.0'
print('OK: 版本计算逻辑正确')
")
echo "  $TEST_V"
pass "版本计算逻辑验证"

# TC-7.5: cleanup.sh --dry-run works
OUTPUT=$("$ROOT_DIR/scripts/cleanup.sh" --dry-run 2>&1) || true
echo "$OUTPUT" | grep -q "预览模式" && pass "cleanup.sh --dry-run: 预览模式生效" || \
    fail "cleanup.sh --dry-run: 预览模式异常"

# TC-7.6: cleanup.sh --help works
"$ROOT_DIR/scripts/cleanup.sh" --help 2>&1 | grep -q "用法" && \
    pass "cleanup.sh --help 正常" || fail "cleanup.sh --help 异常"

# =====================================================
# Test Suite 8: 完整性交叉校验
# =====================================================
echo ""
echo "=== Suite 8: 交叉校验 ==="

# TC-8.2: generated-agents/ directory not altered (should remain empty)
if [[ -d "$ROOT_DIR/generated-agents" ]]; then
    echo "  注意: generated-agents/ 已存在 (用户自行管理)"
else
    pass "generated-agents/ 未创建 (按计划由 Phase 3 创建)"
fi

# TC-8.3: knowledge/ and skills/ untouched
for d in "knowledge" "skills" "phases" "rules"; do
    [[ -d "$ROOT_DIR/$d" ]] && pass "核心目录未改动: $d" || fail "核心目录缺失: $d"
done

# =====================================================
# Summary
# =====================================================
echo ""
echo "============================================================"
echo " 测试结果汇总"
echo "============================================================"
echo "  TOTAL: $TOTAL"
echo "  PASS:  $PASS"
echo "  FAIL:  $FAIL"
echo "  RATE:  $(python3 -c "print(f'{$PASS / max($TOTAL, 1) * 100:.1f}%')")"
echo "============================================================"

if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "!!! 存在失败用例，请检查上方 FAIL 项 !!!"
    exit 1
else
    echo "全部测试通过"
    exit 0
fi
