#!/usr/bin/env bash
# validate_topology.sh — 通用 5 项拓扑校验
# 模式: framework_configs/knowledge/patterns/topology_validation_v1.md
# 用法: bash validate_topology.sh <baseline> <applied> <changes> <report> <subsystem> [biz_if_field] [flow_type_field] [pair_fields]
#
# 通用性:
#   - 5 项校验逻辑通用(任何"在时序表中插入/修改行"的场景)
#   - 退出码:工具返回 0/1(0=通过,1=失败);失败时错误详情在 JSON 含 error_code 字段
#   - Skill 自己在 output-schema.md 映射 error_code → 具体业务退出码(18/19/20/21/15)
#   - C5 参数化:通过 --config 或 CLI 参数指定兜底字段名(避免绑死 "业务接口/业务流")
set -euo pipefail

# === 参数 ===
BASELINE_FILE="${1:?基线表 JSON}"
APPLIED_FILE="${2:?应用后 JSON}"
CHANGES_FILE="${3:?变更记录 JSON}"
REPORT_FILE="${4:?校验报告输出 JSON}"
SUBSYSTEM="${5:?当前子系统名}"
# 可选参数(用于 C5 通用化)
BIZ_IF_FIELD="${6:-业务接口(业务流)}"   # 默认兼容旧调用
FLOW_TYPE_FIELD="${7:-业务流变更类型}"
FAILBACK_KEYWORDS="${8:-待定|待补充|pending}"

# === 5 项校验 ===
ERRORS="[]"

# 辅助:追加错误
append_error() {
  local err="$1"
  ERRORS=$(echo "$ERRORS" | jq --arg e "$err" '. + [$e]')
}

# ----- C1: 变更组件完整性 -----
# 所有 change_rows.component_name 必须出现在 V3 的 src 或 tgt
c1_errors=$(jq -r --slurpfile chg "$CHANGES_FILE" '
  ($chg[0] // []) as $changes |
  [
    $changes[] |
    (.component_name // .组件 // "") as $comp |
    select($comp != "") |
    ($comp as $full |
     [$full, ($full | split(".") | last)] |
     (if any(. == $full) or any(. == ($full | split(".")[-1])) then empty
      else "C1: 变更组件 " + $full + " 未出现在 V3 表的 src/tgt" end)
    )
  ] | .[]
' "$APPLIED_FILE" 2>/dev/null || true)

while IFS= read -r err; do
  [[ -n "$err" ]] && append_error "$err"
done <<< "$c1_errors"

# ----- C2: anchor 范围 -----
# 所有 _is_inserted=true 行的 _anchor_row 必须在 baseline 范围内
baseline_count=$(jq '.rows | length' "$BASELINE_FILE" 2>/dev/null || echo 0)
c2_errors=$(jq -r --argjson max "$baseline_count" '
  [.[] | select(._is_inserted == true) |
   select(._anchor_row < 0 or ._anchor_row >= $max) |
   "C2: 插入行 anchor=" + (._anchor_row|tostring) + " 超出 baseline 范围 [0," + ($max-1|tostring) + "]"] |
  .[]
' "$APPLIED_FILE" 2>/dev/null || true)

while IFS= read -r err; do
  [[ -n "$err" ]] && append_error "$err"
done <<< "$c2_errors"

# ----- C3: 首末行流向 -----
# 首行 src 不能是当前子系统;末行 tgt 不能是当前子系统
first_src=$(jq -r '.rows[0]."源子系统.发送组件" // ""' "$APPLIED_FILE" 2>/dev/null || echo "")
last_tgt=$(jq -r '.rows[-1]."目标子系统.接收组件" // ""' "$APPLIED_FILE" 2>/dev/null || echo "")

if [[ -n "$first_src" && "$first_src" == "${SUBSYSTEM}."* ]]; then
  append_error "C3: 首行源组件 '$first_src' 属于当前子系统 ${SUBSYSTEM},消息链应从外部子系统进入"
fi
if [[ -n "$last_tgt" && "$last_tgt" == "${SUBSYSTEM}."* ]]; then
  append_error "C3: 末行目标组件 '$last_tgt' 属于当前子系统 ${SUBSYSTEM},消息链应发出到外部子系统"
fi

# ----- C4: 重复消息对 -----
c4_errors=$(jq -r '
  [.rows | to_entries | .[] |
   {key: (.value."源子系统.发送组件" + "|" + .value."目标子系统.接收组件" + "|" + (."业务接口(业务流)" // ""))}] |
  .[].key | split("|") | select(length == 3) | join("|")
' "$APPLIED_FILE" 2>/dev/null | sort | uniq -d || true)

while IFS= read -r line; do
  [[ -n "$line" ]] && append_error "C4: 重复消息对 '$line'"
done <<< "$c4_errors"

# ----- C5: 兜底一致性(参数化:适用于任何"含兜底标识的字段")-----
# 含兜底关键词(待定/待补充/pending)的行,关联标志字段必须 = 强制值
# 通用化:通过 CLI 参数指定 biz_if_field 和 flow_type_field
c5_errors=$(jq -r --arg bif "$BIZ_IF_FIELD" --arg ftf "$FLOW_TYPE_FIELD" --arg kw "$FAILBACK_KEYWORDS" '
  [.rows[] |
   select((.[$bif] // "") | test($kw)) |
   select((.[$ftf] // "") != "新增") |
   "C5: 行 seq=" + ((.seq // 0)|tostring) + " 字段 " + $bif + " 含兜底标识 但 " + $ftf + "=" + .[$ftf] + " (应=新增)"] |
  .[]
' "$APPLIED_FILE" 2>/dev/null || true)

while IFS= read -r err; do
  [[ -n "$err" ]] && append_error "$err"
done <<< "$c5_errors"

# === 输出报告 ===
err_count=$(echo "$ERRORS" | jq 'length')
if [[ "$err_count" -gt 0 ]]; then
  passed="false"
  # 通用退出码:仅 0/1,具体业务退出码由 Skill 自己在 output-schema.md 映射
  # 失败时,把首个 error_code 写入 JSON,供 Skill 端映射
  first_error_code="C_unknown"
  if echo "$ERRORS" | jq -e '.[0] | startswith("C1:")' >/dev/null 2>&1; then first_error_code="C1"
  elif echo "$ERRORS" | jq -e '.[0] | startswith("C2:")' >/dev/null 2>&1; then first_error_code="C2"
  elif echo "$ERRORS" | jq -e '.[0] | startswith("C3:")' >/dev/null 2>&1; then first_error_code="C3"
  elif echo "$ERRORS" | jq -e '.[0] | startswith("C4:")' >/dev/null 2>&1; then first_error_code="C4"
  elif echo "$ERRORS" | jq -e '.[0] | startswith("C5:")' >/dev/null 2>&1; then first_error_code="C5"
  fi
  exit_code=1   # 通用失败
else
  passed="true"
  first_error_code="OK"
  exit_code=0
fi

# 报告含 error_code 字段(Skill 可读取后映射到自己的退出码 18/19/20/21/15)
jq -n --arg p "$passed" --argjson e "$ERRORS" --arg ec "$first_error_code" \
  '{passed: ($p == "true"), errors: $e, error_count: ($e | length), error_code: $ec}' > "$REPORT_FILE"

echo "[validate_topology] passed=$passed errors=$err_count error_code=$first_error_code"
exit "$exit_code"
