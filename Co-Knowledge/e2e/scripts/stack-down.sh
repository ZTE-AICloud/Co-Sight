#!/usr/bin/env bash
# 停 E2E 一次性栈并删除卷。
#
#   bash e2e/scripts/stack-down.sh
#   E2E_KEEP=1 bash e2e/scripts/stack-down.sh   # 保留现场（排查失败）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$REPO_ROOT"

state_file="$REPO_ROOT/e2e/.e2e-state.env"
if [ -f "$state_file" ]; then
  # shellcheck disable=SC1090
  source "$state_file"
fi

E2E_RUN_ID="${E2E_RUN_ID:-local-$(date +%s)}"
E2E_RUN_ID="$(printf '%s' "$E2E_RUN_ID" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-')"
E2E_PROJECT="${E2E_PROJECT:-rag-studio-e2e-${E2E_RUN_ID}}"

if [ "${E2E_KEEP:-0}" = "1" ]; then
  echo "[e2e] E2E_KEEP=1，保留 project=$E2E_PROJECT"
  echo "[e2e] 手工清理：docker compose -p $E2E_PROJECT -f deploy/docker-compose.yml -f deploy/docker-compose.e2e.yml down -v --remove-orphans"
  exit 0
fi

docker compose -p "$E2E_PROJECT" \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.e2e.yml \
  --profile e2e \
  down -v --remove-orphans

rm -f "$state_file"
echo "[e2e] project=$E2E_PROJECT 已清理"
