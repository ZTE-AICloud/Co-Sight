#!/bin/bash
# 从部署容器读取模型网关配置，注入当前进程后再执行命令。
# 只把 key 放进子进程环境，不打印、不落盘。
set -euo pipefail
CONTAINER="${MODEL_ENV_CONTAINER:-rag-studio-rag-knowledge-base-1}"
export GENERATION_GATEWAY_URL="$(docker exec "$CONTAINER" printenv GENERATION_GATEWAY_URL)"
export GENERATION_MODEL="$(docker exec "$CONTAINER" printenv GENERATION_MODEL)"
export GENERATION_API_KEY="$(docker exec "$CONTAINER" printenv GENERATION_API_KEY)"
export MODEL_GATEWAY_REASONING_EFFORT="$(docker exec "$CONTAINER" printenv MODEL_GATEWAY_REASONING_EFFORT || true)"
export GENERATION_MAX_TOKENS="${GENERATION_MAX_TOKENS:-2048}"
export GENERATION_TEMPERATURE="${GENERATION_TEMPERATURE:-0}"
export GENERATION_TIMEOUT="${GENERATION_TIMEOUT:-180}"
# Python 不认 no_proxy 里的 10.*.*.* 通配，必须写具体 IP
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
export NO_PROXY="$no_proxy"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/backend/src:${PYTHONPATH:-}"
exec "$@"
