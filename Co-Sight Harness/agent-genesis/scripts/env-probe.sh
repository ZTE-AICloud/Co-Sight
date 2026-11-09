#!/usr/bin/env bash
# scripts/env-probe.sh
# P1: Step 0 归并入口（非节点）。从 workflow.md Step 0 抽出。
# - 输出 .agent-genesis/work/{name}/env-readiness.yaml
# - 失败：escalate always（缺工具/权限）
# - 协议: stdout JSON {env_readiness_path, status: PASS|FAIL, failures: [...]}
#
# 用法: bash scripts/env-probe.sh <name> [--host claude-code|dsh]
# 宿主判定优先级: --host > 环境变量 AG_HOST > DSH_HOME/~/.dsh 存在 > claude-code

set -uo pipefail

NAME="${1:?name required}"
shift || true

HOST_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST_OVERRIDE="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

WORK_DIR=".agent-genesis/work/${NAME}"
OUT="${WORK_DIR}/env-readiness.yaml"

mkdir -p "$WORK_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/python-bin.sh
source "${SCRIPT_DIR}/lib/python-bin.sh"

failures=()
recommended_missing=()

# 必需工具：bash / git 由流水线各处直接调用；python 由注入器与技能脚本调用。
for cmd in bash git; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    failures+=("{\"type\":\"missing_tool\",\"tool\":\"$cmd\"}")
  fi
done

if [ -z "${PYTHON_BIN:-}" ]; then
  failures+=("{\"type\":\"missing_tool\",\"tool\":\"python\",\"detail\":\"需要 Python >= 3.8；可用 AG_PYTHON 指定解释器\"}")
fi

# jq 被部分门禁脚本使用；缺失不阻断 Step 0，但记录为建议修复项。
if ! command -v jq >/dev/null 2>&1; then
  recommended_missing+=("{\"type\":\"missing_recommended_tool\",\"tool\":\"jq\",\"detail\":\"部分门禁脚本使用 jq；缺失时相关检查会失败\"}")
fi

# 宿主判定
if [ -n "$HOST_OVERRIDE" ]; then
  HOST="$HOST_OVERRIDE"
elif [ -n "${AG_HOST:-}" ]; then
  HOST="${AG_HOST}"
elif [ -n "${DSH_HOME:-}" ] || [ -d "${HOME}/.dsh" ]; then
  HOST="dsh"
else
  HOST="claude-code"
fi

# 插件形态感知只读检查（C8-2: 插件根从脚本位置推导, 不写死全局路径）
# - cache 安装态（~/.claude/plugins/cache 内）: 运行期插件根可写 = 已安装副本可能被
#   自改 → failure（修复应走 marketplace 更新）
# - directory 源/skills 态（就地加载的开发仓/用户 skills 目录）: 可写合法, 不检查
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
case "$PLUGIN_ROOT" in
  "$HOME/.claude/plugins/cache"/*)
    if [[ -w "$PLUGIN_ROOT" ]]; then
      failures+=("{\"type\":\"plugin_writable\",\"detail\":\"cache 安装态插件根应只读; 修改插件请走 marketplace 更新后重装\"}")
    fi ;;
  *) : ;;
esac

# 路径落地检查
mkdir -p "$WORK_DIR/gate-results"
touch "$OUT" || failures+=("{\"type\":\"output_unwritable\",\"path\":\"$OUT\"}")

TOOLS_YAML=""
for cmd in bash python git jq; do
  if [ "$cmd" = "python" ]; then
    if [ -n "${PYTHON_BIN:-}" ]; then TOOLS_YAML+="    python: true"$'\n'; else TOOLS_YAML+="    python: false"$'\n'; fi
  elif command -v "$cmd" >/dev/null 2>&1; then
    TOOLS_YAML+="    ${cmd}: true"$'\n'
  else
    TOOLS_YAML+="    ${cmd}: false"$'\n'
  fi
done

PYTHON_DESC="missing"
if [ -n "${PYTHON_BIN:-}" ]; then
  PYTHON_DESC="$("$PYTHON_BIN" -c 'import sys; print("%s %d.%d.%d" % (sys.executable, *sys.version_info[:3]))' 2>/dev/null || echo "$PYTHON_BIN")"
fi

# 写 env-readiness.yaml
{
  printf 'env_readiness:\n'
  printf '  generated_at: "%s"\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '  name: "%s"\n' "$NAME"
  printf '  host: "%s"\n' "$HOST"
  printf '  plugin_root: "%s"\n' "$PLUGIN_ROOT"
  printf '  python: "%s"\n' "$PYTHON_DESC"
  printf '  tools:\n%s' "$TOOLS_YAML"
  printf '  issues_count: %d\n' "${#failures[@]}"
  printf '  failures: [%s]\n' "$(IFS=,; echo "${failures[*]}")"
  printf '  recommended_missing: [%s]\n' "$(IFS=,; echo "${recommended_missing[*]}")"
} > "$OUT"

if [[ ${#failures[@]} -gt 0 ]]; then
  printf '{"env_readiness_path": "%s", "status": "FAIL", "host": "%s", "failures": [%s]}\n' \
    "$OUT" "$HOST" "$(IFS=,; echo "${failures[*]}")"
  exit 2
fi

printf '{"env_readiness_path": "%s", "status": "PASS", "host": "%s", "failures": []}\n' "$OUT" "$HOST"
