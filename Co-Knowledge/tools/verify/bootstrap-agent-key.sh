#!/usr/bin/env bash
# 为 E2E/验收临时建一把 Agent Key。
#
# 两种用法：
#   1) 跑一条命令，退出时自动 revoke（推荐）：
#      tools/verify/bootstrap-agent-key.sh [容器名] [scopes] [kb_ids] -- \
#        python3 tools/verify/verify-agent-api.py
#      （命令通过 RKB_AGENT_TEST_KEY 拿到 Key）
#   2) 只打印 Key（调用方自行 revoke）：
#      KEY=$(tools/verify/bootstrap-agent-key.sh)
#      ...
#      docker exec <容器> python3 -m agent_api.cli revoke --prefix <prefix>
#
# stdout 只输出 Key 明文；其余日志走 stderr。
# 依赖容器内数据库已初始化（agent_api_key 表存在），且 RKB_AGENT_KEY_PEPPER 已配置。
set -euo pipefail

CONTAINER="${1:-rag-studio-rag-knowledge-base-1}"
SCOPES="${2:-kb:list,kb:search}"
KB_IDS="${3:-}"
shift 3 2>/dev/null || true
COMMAND=()
if [[ "${1:-}" == "--" ]]; then
  shift
  COMMAND=("$@")
fi

NAME="e2e-agent-smoke-$(date +%s)"
PREFIX=""

cleanup() {
  if [[ -n "$PREFIX" && ${#COMMAND[@]} -gt 0 ]]; then
    docker exec "$CONTAINER" python3 -m agent_api.cli revoke --prefix "$PREFIX" >/dev/null 2>&1 || true
  fi
}

ARGS=(create --name "$NAME" --scopes "$SCOPES" --rate-limit 0)
if [[ -n "$KB_IDS" ]]; then
  ARGS+=(--kb-ids "$KB_IDS")
fi

OUT="$(docker exec "$CONTAINER" python3 -m agent_api.cli "${ARGS[@]}")"
PREFIX="$(printf '%s\n' "$OUT" | awk '/key_prefix:/ {print $2}')"
KEY="$(printf '%s\n' "$OUT" | awk '/ragk_/ {print $1}' | tail -1)"
if [[ -z "$KEY" || -z "$PREFIX" ]]; then
  echo "failed to create agent key:" >&2
  printf '%s\n' "$OUT" >&2
  exit 1
fi

if [[ ${#COMMAND[@]} -gt 0 ]]; then
  trap cleanup EXIT
  echo "created $PREFIX (scopes=$SCOPES), will revoke on exit" >&2
  export RKB_AGENT_TEST_KEY="$KEY"
  "${COMMAND[@]}"
else
  echo "created $PREFIX (scopes=$SCOPES); revoke manually:" >&2
  echo "  docker exec $CONTAINER python3 -m agent_api.cli revoke --prefix $PREFIX" >&2
  printf '%s\n' "$KEY"
fi
