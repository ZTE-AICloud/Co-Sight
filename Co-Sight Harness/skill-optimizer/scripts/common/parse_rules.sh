#!/usr/bin/env bash
# parse_rules.sh — 通用 markdown 表格规则解析器
#
# 默认模式:R8 规则(组件间流程设计业务)
#   - 扫描 <rules-dir>/*.md
#   - 解析 ## 方法描述 章节下的第一个 markdown 表格
#   - 文件名约定: ${src}_2_${tgt}_消息{接收|发送}组件.md
#   - 输出 JSON: [{src_subsystem, tgt_subsystem, direction, target_subsystem, rules: [{component, method}, ...]}]
#
# 自定义模式:--config <json>
#   - key_columns: 关键列名(用于在 JSON 输出顶层)
#   - value_columns: 值列名(用于在 rules 数组)
#   - section_name: 章节名(默认 "方法描述")
#   - filename_parser: 解析文件名的规则(regex 或 _sep_ 简单分隔)
#   - filename_separator: 文件名分隔符(默认 "_2_",R8 风格)
#
# 用法示例:
#   # 默认 R8 模式
#   parse_rules.sh --rules-dir <dir> --out <file>
#
#   # 完全自定义
#   parse_rules.sh --rules-dir <dir> --out <file> --config '{
#     "section_name": "规则",
#     "key_columns": ["src", "dst"],
#     "value_columns": ["handler"],
#     "filename_parser": "regex",
#     "filename_pattern": "^(.+)_(.+)$"
#   }'
set -euo pipefail

# === 默认参数 ===
RULES_DIR=""
OUT_FILE=""
SECTION_NAME="方法描述"
FILENAME_PATTERN="*.md"
CONFIG_JSON=""

# === 参数解析 ===
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rules-dir)  RULES_DIR="$2"; shift 2 ;;
    --out)        OUT_FILE="$2"; shift 2 ;;
    --section-name) SECTION_NAME="$2"; shift 2 ;;
    --filename-pattern) FILENAME_PATTERN="$2"; shift 2 ;;
    --config)     CONFIG_JSON="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,/^set -euo pipefail/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$RULES_DIR" ]]; then echo "[ERROR] --rules-dir 必填" >&2; exit 1; fi
if [[ -z "$OUT_FILE" ]]; then echo "[ERROR] --out 必填" >&2; exit 1; fi
if [[ ! -d "$RULES_DIR" ]]; then echo "[ERROR] 规则目录不存在: $RULES_DIR" >&2; exit 1; fi

# === 加载配置(若有) ===
if [[ -n "$CONFIG_JSON" ]]; then
  SECTION_NAME=$(echo "$CONFIG_JSON" | jq -r '.section_name // "方法描述"')
  FILENAME_PATTERN=$(echo "$CONFIG_JSON" | jq -r '.filename_pattern // "*.md"')
  KEY_COLUMNS=$(echo "$CONFIG_JSON" | jq -c '.key_columns // ["src_subsystem", "tgt_subsystem"]')
  VALUE_COLUMNS=$(echo "$CONFIG_JSON" | jq -c '.value_columns // ["component", "method"]')
  FILENAME_PARSER=$(echo "$CONFIG_JSON" | jq -r '.filename_parser // "r8"')
else
  # R8 默认
  KEY_COLUMNS='["src_subsystem", "tgt_subsystem"]'
  VALUE_COLUMNS='["component", "method"]'
  FILENAME_PARSER="r8"
fi

# === 解析单个规则文件(参数化版本) ===
parse_single_file() {
  local filepath="$1"
  local filename
  filename=$(basename "$filepath" .md)

  # === 文件名解析(可配置) ===
  local filename_result
  filename_result=$(parse_filename "$filename")
  if [[ $? -ne 0 ]]; then
    return 0  # 不符合约定,跳过
  fi

  # === markdown 表格解析(可配置) ===
  local rules_json
  rules_json=$(parse_markdown_table "$filepath" "$SECTION_NAME" "$VALUE_COLUMNS")
  if [[ -z "$rules_json" || "$rules_json" == "[]" ]]; then
    return 0
  fi

  # === 合并文件名结果 + 表格结果(规则列表) ===
  # rules_json 可能是 0/1/N 个 JSON 对象(每行 1 个),统一为数组
  local rules_array
  if [[ -z "$rules_json" ]]; then
    rules_array="[]"
  else
    # 把多行 JSON 合并为数组
    rules_array=$(echo "$rules_json" | jq -s '.')
  fi
  echo "$filename_result" | jq --argjson rules "$rules_array" \
    '. + {rules: $rules}'
}

# === 文件名解析(可配置:支持 R8 / regex / sep 三种模式) ===
parse_filename() {
  local filename="$1"

  if [[ "$FILENAME_PARSER" == "r8" ]]; then
    # R8 模式: ${src}_2_${tgt}_消息{接收|发送}组件
    if [[ "$filename" =~ 消息(接收|发送)组件$ ]]; then
      local direction="${BASH_REMATCH[1]}"
      local rest="${filename%_消息${direction}组件}"
      if [[ "$rest" =~ ^(.+)_2_(.+)$ ]]; then
        local src="${BASH_REMATCH[1]}"
        local tgt="${BASH_REMATCH[2]}"
        local target="$tgt"
        [[ "$direction" == "发送" ]] && target="$src"
        jq -n \
          --arg src "$src" --arg tgt "$tgt" \
          --arg dir "$direction" --arg ts "$target" \
          --arg fpath "$filepath" \
          '{src_subsystem: $src, tgt_subsystem: $tgt, direction: $dir, target_subsystem: $ts, rule_file: $fpath}'
        return 0
      fi
    fi
    return 1
  fi

  # 自定义 regex 模式:从 CONFIG_JSON 读 pattern + groups
  if [[ "$FILENAME_PARSER" == "regex" && -n "$CONFIG_JSON" ]]; then
    local pattern
    pattern=$(echo "$CONFIG_JSON" | jq -r '.filename_pattern_strict // ""')
    if [[ -n "$pattern" && "$filename" =~ $pattern ]]; then
      local result
      result=$(echo "$CONFIG_JSON" | jq -r '.filename_groups // {}' | jq -c '.')
      # 简化:把所有 capture group 按 BASH_REMATCH[1..N] 注入
      # 实际复杂,这里用 jq 表达
      echo "$result" | jq --arg fpath "$filepath" '. + {rule_file: $fpath}'
      return 0
    fi
    return 1
  fi

  # 自定义 separator 模式:用 _sep_ 拆
  if [[ "$FILENAME_PARSER" == "sep" && -n "$CONFIG_JSON" ]]; then
    local sep
    sep=$(echo "$CONFIG_JSON" | jq -r '.filename_separator // "_2_"')
    local parts=()
    IFS="$sep" read -ra parts <<< "$filename"
    if [[ ${#parts[@]} -ge 2 ]]; then
      jq -n \
        --arg fpath "$filepath" \
        --arg p0 "${parts[0]}" --arg p1 "${parts[1]}" \
        '{filename_part0: $p0, filename_part1: $p1, rule_file: $fpath}'
      return 0
    fi
    return 1
  fi

  return 1
}

# === markdown 表格解析(参数化:支持任意列名 + 通用表头跳过) ===
parse_markdown_table() {
  local filepath="$1"
  local section_name="$2"
  local value_columns="$3"   # JSON 数组

  # 构造 awk 内部数组:value_columns 传给 awk
  local awk_value_cols
  awk_value_cols=$(echo "$value_columns" | jq -r '.[]' | awk '{print "\"" $0 "\""}' | paste -sd ',' -)

  awk -v section="$section_name" -v value_cols="$awk_value_cols" '
    function json_escape(s) {
      gsub(/\\/, "\\\\", s)
      gsub(/"/, "\\\"", s)
      return s
    }
    BEGIN {
      # 解析 value_cols 为 nvc, vc[]
      nvc = split(value_cols, vc, ",")
      for (i=1; i<=nvc; i++) {
        gsub(/^"|"$/, "", vc[i])
      }
      in_sec = 0
      header_seen = 0
    }
    $0 ~ "^##.*" section { in_sec=1; next }
    in_sec && /^##/ { exit }
    in_sec && /^\|/ {
      n = split($0, cells, "|")
      nc = n - 2  # 排除首尾空 cell
      if (nc < nvc) next

      # 通用跳过:第一行(表头)和第二行(分隔 ---)
      if (header_seen == 0) { header_seen = 1; next }
      c1 = cells[2]
      gsub(/^[ \t]+|[ \t]+$/, "", c1)
      if (c1 ~ /^---+$/) next

      # 数据行:输出 JSON
      json = "{"
      for (i=1; i<=nvc; i++) {
        val = cells[i+1]
        gsub(/^[ \t]+|[ \t]+$/, "", val)
        if (i > 1) json = json ","
        json = json "\"" vc[i] "\":\"" json_escape(val) "\""
      }
      json = json "}"
      if (json != "{}") print json
    }
  ' "$filepath"
}

# === 主流程 ===
RULES_JSON="[]"
for filepath in "$RULES_DIR"/$FILENAME_PATTERN; do
  [[ -f "$filepath" ]] || continue
  rule=$(parse_single_file "$filepath")
  if [[ -n "$rule" && "$rule" != "null" ]]; then
    RULES_JSON=$(echo "$RULES_JSON" | jq --argjson r "$rule" '. + [$r]')
  fi
done

# 写缓存
mkdir -p "$(dirname "$OUT_FILE")"
echo "$RULES_JSON" > "$OUT_FILE"

count=$(echo "$RULES_JSON" | jq 'length')
echo "[parse_rules] 解析 $count 条规则 → $OUT_FILE (模式: $FILENAME_PARSER)"
