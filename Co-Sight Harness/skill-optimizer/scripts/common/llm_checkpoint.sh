#!/usr/bin/env bash
# llm_checkpoint.sh — LLM 断点哨兵通用工具
# 协议: framework_configs/llm_checkpoint_sentinel_v1.md
# 用法: source 这文件 → 调用 llm_checkpoint_exit 或 llm_checkpoint_resume
set -euo pipefail

# === 路径解析 ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_DIR="${SCRIPT_DIR}"

# === 颜色(可选) ===
if [[ -t 1 ]]; then
  C_BOLD='\033[1m'
  C_YEL='\033[33m'
  C_GRN='\033[32m'
  C_RST='\033[0m'
else
  C_BOLD=''; C_YEL=''; C_GRN=''; C_RST=''
fi

# === 退出码常量 ===
readonly EXIT_OK=0
readonly EXIT_LLM_CHECKPOINT=100

# === 通用函数 ===

# 写 LLM 任务文件并退出 100
# 用法: llm_checkpoint_exit <task_file> <task_json_payload>
llm_checkpoint_exit() {
  local task_file="$1"
  local response_var="$2"   # e.g. "llm_response_4.json"
  local resume_cmd="${3:-bash scripts/run.sh --resume}"

  # 写 task 文件(passed in as JSON)
  if [[ -n "${2:-}" ]] && [[ "$2" != "--payload-stdin" ]]; then
    :  # task_file 已是内容
  fi

  echo ""
  echo -e "${C_BOLD}${C_YEL}========================================${C_RST}"
  echo -e "${C_BOLD}${C_YEL}  [LLM 断点] 等待响应${C_RST}"
  echo -e "${C_YEL}  任务文件: $task_file${C_RST}"
  echo -e "${C_YEL}  请 CC 读取 → 推理 → 写入: $response_var${C_RST}"
  echo -e "${C_YEL}  续跑命令: $resume_cmd${C_RST}"
  echo -e "${C_BOLD}${C_YEL}========================================${C_RST}"
  echo ""
  exit $EXIT_LLM_CHECKPOINT
}

# 从 stdin 读 task JSON,写文件 + exit 100
# 用法: echo "$task_json" | llm_checkpoint_stdin <task_file> <response_var>
llm_checkpoint_stdin() {
  local task_file="$1"
  local response_var="$2"
  local resume_cmd="${3:-bash scripts/run.sh --resume}"

  cat > "$task_file"

  echo ""
  echo -e "${C_BOLD}${C_YEL}========================================${C_RST}"
  echo -e "${C_BOLD}${C_YEL}  [LLM 断点] 等待响应${C_RST}"
  echo -e "${C_YEL}  任务文件: $task_file${C_RST}"
  echo -e "${C_YEL}  请 CC 读取 → 推理 → 写入: $response_var${C_RST}"
  echo -e "${C_YEL}  续跑命令: $resume_cmd${C_RST}"
  echo -e "${C_BOLD}${C_YEL}========================================${C_RST}"
  echo ""
  exit $EXIT_LLM_CHECKPOINT
}

# 校验 LLM 响应存在(用于 step 入口)
# 用法: llm_checkpoint_validate <response_file> [required_fields_json]
# 返回: 0=响应存在且合法 / 1=响应不存在
llm_checkpoint_validate() {
  local response_file="$1"
  local required_fields="${2:-[]}"

  if [[ ! -f "$response_file" ]]; then
    return 1
  fi

  if [[ "$required_fields" != "[]" ]]; then
    for field in $(echo "$required_fields" | jq -r '.[]'); do
      if [[ "$(jq ".$field // empty" "$response_file" 2>/dev/null)" == "" ]]; then
        return 1
      fi
    done
  fi

  return 0
}

# 从 LLM 响应重试/重置 retry 计数
# 用法: llm_checkpoint_retry <retry_count_file> [max_retries=3]
# 返回: 0=可重试 / 1=超过重试上限
llm_checkpoint_retry() {
  local retry_count_file="$1"
  local max_retries="${2:-3}"

  local count
  count=$(cat "$retry_count_file" 2>/dev/null || echo 0)
  count=$((count + 1))
  echo "$count" > "$retry_count_file"

  if [[ "$count" -ge "$max_retries" ]]; then
    return 1
  fi
  return 0
}

# 重置 retry 计数(成功时)
# 用法: llm_checkpoint_reset_retry <retry_count_file>
llm_checkpoint_reset_retry() {
  local retry_count_file="$1"
  echo "0" > "$retry_count_file"
  return 0
}

# === 主函数:被 source 时不执行,直接定义函数 ===
# 被直接调用时,显示帮助
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  cat <<EOF
llm_checkpoint.sh — LLM 断点哨兵通用工具

协议: framework_configs/llm_checkpoint_sentinel_v1.md
退出码: 100 = LLM 等待(主控 if-else 检测)

用法(在 step 脚本中):
  source "\${SKILL_ROOT}/scripts/common/llm_checkpoint.sh"

  # 1. 写任务文件后退出等待
  echo '\$task_json' | llm_checkpoint_stdin "\$TASK_FILE" "llm_response_N.json"
  # ↑ 等价于 exit 100

  # 2. 校验响应存在性
  if llm_checkpoint_validate "\$RESP_FILE" '["required_field_1","required_field_2"]'; then
    :  # 响应合法
  else
    :  # 响应不存在或字段缺失
  fi

  # 3. 重试计数管理
  if ! llm_checkpoint_retry "\$RETRY_FILE" 3; then
    echo "重试超限" >&2
    exit 17
  fi
EOF
  exit 0
fi
