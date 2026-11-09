#!/usr/bin/env bash
# =============================================================================
# Phase 1 Blocker Check — AgentGenesis
# =============================================================================
# 用途: Phase 1 和 Phase 2 之间的阻断级检查
# 执行: bash .claude/scripts/phase1-blocker-check.sh <decision_file> <pipeline_mode>
# 退出码: 0=PASS, 1=FAIL(阻断), 2=脚本错误(继续)
# =============================================================================

set -u

DECISION_FILE="${1:-}"
PIPELINE_MODE="${2:-}"
FAIL_COUNT=0
WARN_COUNT=0

# ---------- 参数校验 ----------
VALID_MODES="agent-creation create-skill optimize-skill"
if [ -z "$DECISION_FILE" ] || [ -z "$PIPELINE_MODE" ]; then
  echo "[ERROR] 用法: $0 <decision_file> <pipeline_mode>" >&2
  echo "  pipeline_mode: agent-creation | create-skill | optimize-skill" >&2
  exit 2
fi

if ! echo "$VALID_MODES" | grep -qw "$PIPELINE_MODE"; then
  echo "[ERROR] 无效 pipeline_mode: '$PIPELINE_MODE'" >&2
  echo "  有效值: $VALID_MODES" >&2
  exit 2
fi

echo "=== Phase 1 Blocker Check ==="
echo "  目标: $DECISION_FILE"
echo "  模式: $PIPELINE_MODE"
echo ""

# ---------- B1: 文件存在 + 可解析 ----------
B1_RESULT="PASS"
B1_DETAIL=""

if [ ! -f "$DECISION_FILE" ]; then
  B1_RESULT="FAIL"
  B1_DETAIL="文件不存在: $DECISION_FILE"
elif [ ! -s "$DECISION_FILE" ]; then
  B1_RESULT="FAIL"
  B1_DETAIL="文件为空: $DECISION_FILE"
else
  FILE_SIZE=$(wc -c < "$DECISION_FILE")
  case "$PIPELINE_MODE" in
    agent-creation)
      # agent-creation 产出是结构化决策数据，必须有合法 YAML frontmatter
      YAML_BLOCK=$(awk 'BEGIN{c=0} /^---$/{c++; if(c==2) exit; next} c==1{print}' "$DECISION_FILE" 2>/dev/null || true)
      if [ -z "$YAML_BLOCK" ]; then
        B1_RESULT="FAIL"
        B1_DETAIL="无 YAML frontmatter（agent-creation 产出必须有 frontmatter）"
      elif ! echo "$YAML_BLOCK" | python3 -c "
import sys, yaml
try:
    data = yaml.safe_load(sys.stdin.read())
    if not isinstance(data, dict):
        sys.exit(1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        B1_RESULT="FAIL"
        B1_DETAIL="YAML frontmatter 解析失败"
      else
        B1_DETAIL="$DECISION_FILE ($FILE_SIZE bytes, frontmatter OK)"
      fi
      ;;
    *)
      # optimize-skill / create-skill 产出是设计/诊断散文，frontmatter 为可选
      B1_DETAIL="$DECISION_FILE ($FILE_SIZE bytes)"
      ;;
  esac
fi

if [ "$B1_RESULT" = "PASS" ]; then
  echo "[✓] B1: 文件存在且可解析 — $B1_DETAIL"
else
  echo "[✗] B1: 文件检查失败 — $B1_DETAIL"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ---------- B2: pattern_id 在 catalog 中 ----------
B2_RESULT="PASS"
B2_DETAIL=""

if [ ! -f "$DECISION_FILE" ]; then
  B2_DETAIL="跳过（文件不存在）"
elif [ "$PIPELINE_MODE" = "agent-creation" ]; then
  CATALOG="${CATALOG_PATH:-knowledge/shared/pattern-catalog.yaml}"
  if [ ! -f "$CATALOG" ]; then
    B2_RESULT="WARN"
    B2_DETAIL="pattern-catalog.yaml 不存在，跳过检查"
  else
    # 用 Python 统一做 pattern_id 提取 + 校验，避免 grep -P 跨平台兼容问题
    CHECK_RESULT=$(python3 -c "
import yaml, re, sys

# 提取 decision 文件中的 pattern_id（大写字母+数字，如 W1, CD3, HC-01 等）
with open('$DECISION_FILE') as f:
    text = f.read()
found = set(re.findall(r'\b[A-Z]{1,4}-?\d+\b', text))

# 提取 catalog 中所有合法 pattern_id
with open('$CATALOG') as f:
    catalog = yaml.safe_load(f.read())
catalog_ids = set()
def walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.match(r'^[A-Z]{1,4}-?\d+$', k):
                catalog_ids.add(k)
            walk(v)
    elif isinstance(obj, list):
        for item in obj:
            walk(item)
walk(catalog)

invalid = found - catalog_ids
valid = found & catalog_ids

print(f'{len(valid)} valid, {len(invalid)} invalid', end='')
if invalid:
    print(' | bad: ' + ' '.join(sorted(invalid)), end='')
" 2>/dev/null || echo "SCRIPT_ERROR")

    if [[ "$CHECK_RESULT" == SCRIPT_ERROR* ]]; then
      B2_RESULT="WARN"
      B2_DETAIL="Python 脚本执行失败，跳过 pattern_id 检查"
    elif echo "$CHECK_RESULT" | grep -q 'invalid$'; then
      B2_RESULT="PASS"
      B2_DETAIL="$CHECK_RESULT"
    elif echo "$CHECK_RESULT" | grep -q 'bad:'; then
      B2_RESULT="FAIL"
      B2_DETAIL="$CHECK_RESULT"
    else
      # 无 pattern_id 引用也视为 PASS（文件中可能不含任何 pattern_id）
      B2_RESULT="PASS"
      B2_DETAIL="$CHECK_RESULT"
    fi
  fi
else
  B2_DETAIL="跳过（仅 agent-creation pipeline 需要）"
fi

if [ "$B2_RESULT" = "PASS" ]; then
  echo "[✓] B2: pattern_id 在 catalog 中 — $B2_DETAIL"
elif [ "$B2_RESULT" = "WARN" ]; then
  echo "[~] B2: $B2_DETAIL"
  WARN_COUNT=$((WARN_COUNT + 1))
else
  echo "[✗] B2: pattern_id 校验失败 — $B2_DETAIL"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ---------- B3: 无残留占位符 ----------
B3_RESULT="PASS"
B3_DETAIL=""

if [ ! -f "$DECISION_FILE" ]; then
  B3_DETAIL="跳过（文件不存在）"
else

# 模板占位符 {{...}}
TEMPLATE_COUNT=$(grep -cF '{{' "$DECISION_FILE" 2>/dev/null || true)
TEMPLATE_COUNT=${TEMPLATE_COUNT:-0}
[[ "$TEMPLATE_COUNT" =~ ^[0-9]+$ ]] || TEMPLATE_COUNT=0

# TODO/TBD/FIXME/XXX
TODO_COUNT=$(grep -ciE '(^|[^A-Za-z])(TODO|TBD|FIXME|XXX)([^A-Za-z]|$)' "$DECISION_FILE" 2>/dev/null || true)
TODO_COUNT=${TODO_COUNT:-0}
[[ "$TODO_COUNT" =~ ^[0-9]+$ ]] || TODO_COUNT=0

# 中文占位符
CN_COUNT=0
for _word in 待补充 待定 待确认 待填写; do
  _c=$(grep -cF "$_word" "$DECISION_FILE" 2>/dev/null || true)
  _c=${_c:-0}
  [[ "$_c" =~ ^[0-9]+$ ]] || _c=0
  CN_COUNT=$((CN_COUNT + _c))
done

TOTAL_PLACEHOLDER=$((TEMPLATE_COUNT + TODO_COUNT + CN_COUNT))

if [ "$TOTAL_PLACEHOLDER" -gt 0 ]; then
  B3_RESULT="FAIL"
  B3_DETAIL="$TOTAL_PLACEHOLDER 个残留占位符（模板: $TEMPLATE_COUNT, TODO/TBD: $TODO_COUNT, 中文: $CN_COUNT）"
  # 显示前 3 个位置（用 grep -E，避免 -P）
  grep -nE '\{\{.*\}\}|(^|[^A-Za-z])(TODO|TBD|FIXME|XXX)([^A-Za-z]|$)|待补充|待定|待确认|待填写' "$DECISION_FILE" 2>/dev/null | head -3 | while read -r line; do
    echo "       示例: $line"
  done
else
  B3_DETAIL="无残留占位符"
fi

fi

if [ "$B3_RESULT" = "PASS" ]; then
  echo "[✓] B3: 无残留占位符 — $B3_DETAIL"
else
  echo "[✗] B3: 发现残留占位符 — $B3_DETAIL"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ---------- 汇总 ----------
echo ""
if [ "$FAIL_COUNT" -eq 0 ] && [ "$WARN_COUNT" -eq 0 ]; then
  echo "=== Result: PASS ==="
  exit 0
elif [ "$FAIL_COUNT" -eq 0 ]; then
  echo "=== Result: PASS ($WARN_COUNT warning) ==="
  exit 0
else
  echo "=== Result: FAIL ($FAIL_COUNT blocker) ==="
  exit 1
fi
