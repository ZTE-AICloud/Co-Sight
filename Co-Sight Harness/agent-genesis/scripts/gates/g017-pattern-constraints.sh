#!/bin/bash
# G017: Pattern Matching Sanity — 匹配决策三层确定性检查（C2 重写）
#
# 由 pattern-matcher 在 step-2 产出后自检调用（原 step-2b 独立节点已删——其 LLM 审查
# 更早由本脚本取代（readiness-verifier 角色错位修复，见
# docs/plan/pipeline-step-optimization-plan.md C2）。语义风险不进 LLM 自审，
# 以 CONCERNS 形式标注给 step-3 的 human-review.md，由 DC-001 人审裁决。
#
# 硬约束以本仓库知识库为准（knowledge/shared/cascading-matcher.yaml hard_constraints）：
#   HC-01 CD3 声明后必须有 K2/K3/K4 替代来源
#   HC-02 E 链不可跳跃（E2 依赖 E1；E3 依赖 E1+E2）
#   HC-03 W5 必须声明 base_topology
#   HC-04 MN-Hybrid 必须声明 phases 分段
#   HC-05 E2 + IH1 不兼容
#   HC-06 同一子维度互斥模式不能同时选中（确定性子集：同 dim 单元内 W1-W4 复选、
#         IT1-Forbidden × IT1-Enforced）
# 注意: 旧版脚本中的 "W4/W5/SM1 × MN-Deterministic" 互斥对来自插件缓存规则库，
#       本仓库 cascading-matcher.yaml 无此规则（W4/SM1 可作子结构嵌套），已移除。
#
# 检查层:
#   L1 结构: frontmatter 必填 + Tier-2 表格行合法（选中模式/置信度非空）
#   L2 目录: 选中模式 id 均存在于 pattern-catalog.yaml（防编造，S-05）；
#            非模式 id 的自由文本行 → CONCERNS（不 FAIL，兼容历史格式漂移）
#   L3 硬约束: 仅基于 Tier-2 选中集合 + Tier-0 判定（不 grep 全文，拒绝段不误伤）
#   v2 接线: frontmatter 含 selected_patterns+build_type 时调 validate-plan-v2.py，
#            其全部 FAIL findings 透传为 FAIL（validator 崩溃 → M0_validator_error）
# CONCERNS(非阻断): 关键维度(工作流/知识/交互) confidence=low /
#             cascade_opposed / 自报 HC 校验段含失败标记 / 非标准模式行
#
# 协议: stdin JSON {matching_decision, catalog?} → stdout JSON
# 退出码: 0=PASS 或 CONCERNS（CONCERNS 详情在 stdout，由 pattern-matcher 自检后写 phase2-review.md）
#         2=FAIL（L1/L2/L3 硬伤，就地修订 ≤2 轮，超限 ESCALATE）
# 输入: --input '<json>'（argv canonical，executor/自检 agent 白名单模式下管道被禁）
#       或 stdin JSON（main agent 直调兼容）——同 g026 先例
set -uo pipefail

if [ "${1:-}" = "--input" ]; then
  INPUT="${2:-}"
else
  # 有界 stdin 读: 开放 stdin 的后台场景不再无界挂死, 超时按空输入 fail-closed
  INPUT="$(timeout 10 cat 2>/dev/null || true)"
fi
DECISION=$(echo "$INPUT" | jq -r '.matching_decision // ""')
CATALOG=$(echo "$INPUT" | jq -r '.catalog // "knowledge/shared/pattern-catalog.yaml"')

if [ -z "$DECISION" ] || [ ! -f "$DECISION" ]; then
  echo '{"gate_id":"gate.match.contract","verdict":"FAIL","failures":[{"type":"missing_decision_file"}]}'
  exit 2
fi
if [ ! -f "$CATALOG" ]; then
  echo "{\"gate_id\":\"G017\",\"verdict\":\"FAIL\",\"failures\":[{\"type\":\"missing_catalog\",\"catalog\":\"$CATALOG\"}]}"
  exit 2
fi

TEXT=$(cat "$DECISION")
FAILURES_JSON="[]"
CONCERNS_JSON="[]"
add_failure() { FAILURES_JSON=$(echo "$FAILURES_JSON" | jq --argjson n "$1" '. + [$n]'); }
add_concern() { CONCERNS_JSON=$(echo "$CONCERNS_JSON" | jq --argjson n "$1" '. + [$n]'); }

# ─────────────────────────────────────────────
# L1: 结构校验
# ─────────────────────────────────────────────
FM=$(awk 'NR==1&&/^---$/{p=1;next} /^---$/{exit} p' "$DECISION")
echo "$FM" | grep -q '^decision_id:' || add_failure '{"type":"L1_missing_decision_id"}'
echo "$FM" | grep -q '^timestamp:'     || add_failure '{"type":"L1_missing_timestamp"}'
echo "$FM" | grep -q '^pipeline:'      || add_failure '{"type":"L1_missing_pipeline"}'

# Tier-2 表格行: 仅解析表格体（选中集合）；拒绝段为 bullet 列表，天然排除。
# 兼容无粗体格式（gate 治理阶段 3）: 先取含 ** 的行，无则回退取全部表格行——
# 跳过表头（表格首行）与分隔行，模式 id 直接从单元格提取——排版漂移不再误报
TIER2_ROWS=$(awk '/^## Tier 2/{f=1;next} /^## /{f=0} f' "$DECISION" | grep -E '^\|.*\*\*' || true)
if [ -z "$TIER2_ROWS" ]; then
  TIER2_ROWS=$(awk '/^## Tier 2/{f=1;next} /^## /{f=0} f && /^\|/{n++; if(n>1) print}' "$DECISION" | grep -vE '^\|[[:space:]]*[-:]+' || true)
fi
[ -z "$TIER2_ROWS" ] && add_failure '{"type":"L1_no_tier2_rows"}'

SELECTED_JSON="[]"
if [ -n "$TIER2_ROWS" ]; then
  while IFS= read -r row; do
    bold=$(echo "$row" | grep -oE '\*\*[^*|]+\*\*' | head -1 | tr -d '*')
    main="${bold%%（*}"   # 去掉全角括号注释，如 G1-Review-Gate（博弈语义）
    id=$(echo "$main" | grep -oE '^[A-Z]+[0-9]+' | head -1 || true)
    if [ -z "$id" ]; then
      # 无粗体回退: 模式 id 直接从行内单元格提取（W1/DT1/IH1 等形态）
      id=$(echo "$row" | grep -oE '\b[A-Z]+[0-9]+\b' | head -1 || true)
      [ -n "$id" ] && main=$id
    fi
    conf=$(echo "$row" | grep -oE '(^|\|)\s*(high|medium|low)\s*(\||$)' | grep -oE 'high|medium|low' | head -n 1 || true)
    [ -z "$conf" ] && conf=$(echo "$row" | grep -oE '\b(high|medium|low)\b' | head -n 1 || true)
    dim=$(echo "$row" | awk -F'|' '{gsub(/^[ *]+|[ *]+$/,"",$2); print $2}')
    if [ -z "$id" ]; then
      # 自由文本行（历史格式漂移），不判 FAIL，标注给人审
      add_concern "{\"type\":\"non_standard_pattern_row\",\"dim\":\"$dim\",\"raw\":\"${bold:0:60}\"}"
      continue
    fi
    [ -z "$conf" ] && add_failure "{\"type\":\"L1_missing_confidence\",\"pattern\":\"$id\"}"
    SELECTED_JSON=$(echo "$SELECTED_JSON" | jq --arg p "$main" --arg i "$id" --arg c "$conf" --arg d "$dim" '. + [{pattern:$p,id:$i,confidence:$c,dim:$d}]')
  done <<< "$TIER2_ROWS"
fi

# ─────────────────────────────────────────────
# L2: 目录一致性（防编造模式 id）
# ─────────────────────────────────────────────
CATALOG_IDS=$( { grep -oE '^    [A-Z][A-Za-z0-9]*:' "$CATALOG"; grep -oE '^  MN-[A-Za-z]+:' "$CATALOG"; } | tr -d ' :' | sort -u | tr '\n' ' ')
if [ "$SELECTED_JSON" != "[]" ]; then
  while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    case " $CATALOG_IDS " in
      *" $pid "*) ;;
      *) add_failure "{\"type\":\"L2_unknown_pattern\",\"pattern\":\"$pid\",\"catalog\":\"$(basename "$CATALOG")\"}" ;;
    esac
  done < <(echo "$SELECTED_JSON" | jq -r '.[].id' | sort -u)
fi

# ─────────────────────────────────────────────
# L3: 硬约束（仅基于选中集合 + Tier-0 判定）
# 规则来源: knowledge/shared/cascading-matcher.yaml hard_constraints（本仓库权威）
# ─────────────────────────────────────────────
IDS=$(echo "$SELECTED_JSON" | jq -r '.[].id' | sort -u | tr '\n' ' ')
has() { case " $IDS " in *" $1 "*) return 0;; *) return 1;; esac }

# HC-01: CD3 必须配对 K2/K3/K4 之一
if has CD3 && ! has K2 && ! has K3 && ! has K4; then
  add_failure '{"type":"HC01_CD3_without_K_source","rule":"CD3 声明后必须有 K2/K3/K4 替代来源"}'
fi
# HC-02: E 链不可跳跃（E2 依赖 E1；E3 依赖 E1+E2）
if has E2 && ! has E1; then add_failure '{"type":"HC02_E2_without_E1"}'; fi
if has E3 && { ! has E1 || ! has E2; }; then add_failure '{"type":"HC02_E3_without_E1E2"}'; fi
# HC-03: W5 叠加层必须声明 base_topology
if has W5 && ! echo "$TEXT" | grep -q "base_topology"; then
  add_failure '{"type":"HC03_W5_without_base_topology"}'
fi
# HC-04: MN-Hybrid 必须声明 phases 分段
TIER0_MN=$(awk '/^## Tier 0/{f=1;next} /^## /{f=0} f' "$DECISION" | grep -oE 'MN-(Exploratory|Deterministic|Hybrid)' | head -1 || true)
if [ "$TIER0_MN" = "MN-Hybrid" ] && ! echo "$TEXT" | grep -qE "phases|分段"; then
  add_failure '{"type":"HC04_hybrid_without_phases"}'
fi
# HC-05: E2 + IH1 不兼容
if has E2 && has IH1; then add_failure '{"type":"HC05_E2_IH1_incompatible"}'; fi
# HC-06 确定性子集: 同一 dim 单元内 W1-W4 复选（顶层分解互斥）；IT1 变体互斥
if [ "$SELECTED_JSON" != "[]" ]; then
  DUP_W=$(echo "$SELECTED_JSON" | jq -r '.[] | select(.id|test("^[W][1-4]$")) | .dim' | sort | uniq -d | head -1 || true)
  [ -n "$DUP_W" ] && add_failure "{\"type\":\"HC06_same_dim_mutex\",\"dim\":\"$DUP_W\",\"family\":\"W1-W4\"}"
  if echo "$SELECTED_JSON" | jq -r '.[].id' | grep -q "^IT1-Forbidden$" && echo "$SELECTED_JSON" | jq -r '.[].id' | grep -q "^IT1-Enforced$"; then
    add_failure '{"type":"HC06_IT1_variants_mutex"}'
  fi
fi

# ─────────────────────────────────────────────
# v2 结构/物化检查（build-plan-harness-contract v2.0 / D2；M4 物化覆盖率 / M5
# 角色与触发器枚举 / M6 拓扑一致性均由 validator 产出）
# 仅当 frontmatter 含 v2 标记（selected_patterns + build_type）时启用；
# legacy 决策（无 v2 字段）跳过，保持原行为。解析与判定复用
# scripts/validate-plan-v2.py（D1 golden 校验同一实现，防两边漂移）。
# ─────────────────────────────────────────────
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VALIDATOR="$SCRIPT_DIR/../validate-plan-v2.py"
if echo "$FM" | grep -q '^selected_patterns:' || echo "$FM" | grep -q '^build_type:'; then
  if echo "$FM" | grep -q '^selected_patterns:' && echo "$FM" | grep -q '^build_type:'; then
    if [ -f "$VALIDATOR" ]; then
      # validator rc=1 仍可能输出合法 JSON（findings 型 FAIL）——按输出形态区分:
      # 合法 JSON → 提取全部 FAIL findings 传播（不按 M 前缀过滤——原 `test("^M[456]_")`
      #   会丢弃 frontmatter 单侧漂移类 finding（selected_patterns 非空/非法 ID/rejected
      #   条目/build_type 枚举等），使 g017 存在 PASS 通道）；崩溃/非 JSON → M0_validator_error
      #   FAIL（拒绝静默跳过，原 `|| true` 吞崩溃使检查空转，gate 治理阶段 3 收紧）
      V2_RC=0
      V2_OUT=$(python3 "$VALIDATOR" --decision "$DECISION" --catalog "$CATALOG" 2>/dev/null) || V2_RC=$?
      V2_VALID=$(echo "$V2_OUT" | jq -r 'has("results")' 2>/dev/null || echo false)
      if [ "$V2_VALID" != "true" ]; then
        add_failure "$(jq -n --arg rc "$V2_RC" '{type:"M0_validator_error", detail:("validator 崩溃或输出非合法 JSON (rc=" + $rc + ")——v2 检查未执行, 拒绝静默跳过")}')"
      else
        V2_FAILS=$(echo "$V2_OUT" | jq -r '.results[0].findings[] | select(.severity == "FAIL") | .check' 2>/dev/null || true)
        if [ -n "$V2_FAILS" ]; then
          while IFS= read -r chk; do
            [ -z "$chk" ] && continue
            t="${chk%%:*}"; d="${chk#*: }"
            add_failure "$(jq -n --arg t "$t" --arg d "$d" '{type:$t, detail:$d}')"
          done <<< "$V2_FAILS"
        fi
      fi
    else
      add_failure '{"type":"M0_validator_missing","validator":"scripts/validate-plan-v2.py"}'
    fi
  else
    # v2 字段不完整（只有其一）→ 部分物化, 按硬伤处理
    add_failure '{"type":"M0_partial_v2_frontmatter","detail":"selected_patterns 与 build_type 必须同时出现"}'
  fi
fi

# ─────────────────────────────────────────────
# CONCERNS（非阻断，交 DC-001 人审）
# ─────────────────────────────────────────────
if [ "$SELECTED_JSON" != "[]" ]; then
  while IFS= read -r line; do
    dim=$(echo "$line" | jq -r '.dim'); conf=$(echo "$line" | jq -r '.confidence'); pat=$(echo "$line" | jq -r '.pattern')
    case "$dim" in
      *工作流*|*知识*|*交互*) [ "$conf" = "low" ] && add_concern "{\"type\":\"key_dim_low_confidence\",\"dim\":\"$dim\",\"pattern\":\"$pat\"}" ;;
    esac
  done < <(echo "$SELECTED_JSON" | jq -c '.[]')
fi
echo "$TEXT" | grep -q "cascade_opposed" && add_concern '{"type":"cascade_opposed_selection"}'
HC_SECTION=$(awk '/硬约束校验/{f=1;next} /^## /{f=0} f' "$DECISION" || true)
if [ -n "$HC_SECTION" ] && echo "$HC_SECTION" | grep -qE '✗|FAIL|违反'; then
  add_concern '{"type":"hc_self_check_failed"}'
fi

# ─────────────────────────────────────────────
# 结论
# ─────────────────────────────────────────────
FCOUNT=$(echo "$FAILURES_JSON" | jq 'length')
CCOUNT=$(echo "$CONCERNS_JSON" | jq 'length')
SELECTED_FLAT=$(echo "$SELECTED_JSON" | jq '[.[].pattern]')

if [ "$FCOUNT" -gt 0 ]; then
  jq -n --argjson f "$FAILURES_JSON" --argjson s "$SELECTED_FLAT" \
    '{gate_id:"gate.match.contract",verdict:"FAIL",selected:$s,failures:$f}'
  exit 2
fi
if [ "$CCOUNT" -gt 0 ]; then
  jq -n --argjson c "$CONCERNS_JSON" --argjson s "$SELECTED_FLAT" \
    '{gate_id:"gate.match.contract",verdict:"CONCERNS",selected:$s,concerns:$c}'
  exit 0
fi
jq -n --argjson s "$SELECTED_FLAT" '{gate_id:"gate.match.contract",verdict:"PASS",selected:$s}'
exit 0
