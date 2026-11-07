#!/usr/bin/env bash
# 起 E2E 一次性栈：web@18080 + fake-model-gateway@18081 + PG/OpenSearch + RKB。
#
# 用法：
#   E2E_RUN_ID=local-1 bash e2e/scripts/stack-up.sh
#   E2E_BUILD=1 bash e2e/scripts/stack-up.sh   # 本地没有镜像时允许构建（慢）
#
# 默认 --no-build：CI 应预构建/缓存镜像；本机通常已有 ragstudio/web 与
# ragstudio/rag-knowledge-base 镜像。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$REPO_ROOT"

E2E_RUN_ID="${E2E_RUN_ID:-local-$(date +%s)}"
E2E_RUN_ID="$(printf '%s' "$E2E_RUN_ID" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-')"
E2E_WEB_PORT="${E2E_WEB_PORT:-18080}"
E2E_MOCK_PORT="${E2E_MOCK_PORT:-18081}"
E2E_PROJECT="rag-studio-e2e-${E2E_RUN_ID}"

export E2E_RUN_ID E2E_WEB_PORT E2E_MOCK_PORT E2E_PROJECT
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-E2eTestPass123!}"
export POSTGRES_USER="${POSTGRES_USER:-rag}"
export POSTGRES_DB="${POSTGRES_DB:-rag_studio}"
# 非 superuser 应用角色（空卷由 deploy/init/pg/05-app-role.sh 创建）。
export RKB_DB_USER="${RKB_DB_USER:-rag_app}"
export RKB_DB_PASSWORD="${RKB_DB_PASSWORD:-E2eAppPass123!}"
export AUTH_MODE="${AUTH_MODE:-none}"
# AUTH_MODE=local 的 auth E2E 用；AUTH_MODE=none/gateway 时这些值不会被读取。
export RKB_ADMIN_USERNAME="${RKB_ADMIN_USERNAME:-e2e-admin}"
export RKB_ADMIN_PASSWORD="${RKB_ADMIN_PASSWORD:-E2eAdminPass123!}"
# E2E 不做首次改密（强制改密流程由单测覆盖；否则 admin 登录后无法 seed 模型）
export RKB_ADMIN_MUST_CHANGE="${RKB_ADMIN_MUST_CHANGE:-false}"
export RKB_AUTH_COOKIE_SECURE="${RKB_AUTH_COOKIE_SECURE:-false}"
export MEM_LIMIT="${MEM_LIMIT:-}"
export TZ="${TZ:-Asia/Shanghai}"

COMPOSE=(docker compose -p "$E2E_PROJECT"
  -f deploy/docker-compose.yml
  -f deploy/docker-compose.e2e.yml
  --profile e2e)

state_file="$REPO_ROOT/e2e/.e2e-state.env"
cat > "$state_file" <<EOF
E2E_RUN_ID=$E2E_RUN_ID
E2E_PROJECT=$E2E_PROJECT
E2E_WEB_PORT=$E2E_WEB_PORT
E2E_MOCK_PORT=$E2E_MOCK_PORT
E2E_BASE_URL=http://127.0.0.1:$E2E_WEB_PORT
E2E_MOCK_BASE_URL=http://127.0.0.1:$E2E_MOCK_PORT
EOF

echo "[e2e] project=$E2E_PROJECT web=$E2E_WEB_PORT mock=$E2E_MOCK_PORT"

up_args=(up -d --wait)
if [ "${E2E_BUILD:-0}" != "1" ]; then
  up_args+=(--no-build)
fi

if ! "${COMPOSE[@]}" "${up_args[@]}"; then
  echo "[e2e] 栈启动失败，最近日志：" >&2
  "${COMPOSE[@]}" logs --tail=120 >&2 || true
  exit 1
fi

wait_http() {
  local url="$1" name="$2" deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      echo "[e2e] $name 就绪"
      return 0
    fi
    sleep 2
  done
  echo "[e2e] $name 未就绪: $url" >&2
  "${COMPOSE[@]}" logs --tail=120 >&2 || true
  return 1
}

wait_http "http://127.0.0.1:${E2E_WEB_PORT}/api/co-knowledge/v1/health" "RKB /health"
wait_http "http://127.0.0.1:${E2E_MOCK_PORT}/__mock__/health" "fake-model-gateway"

echo "[e2e] 就绪。接下来："
echo "  E2E_BASE_URL=http://127.0.0.1:${E2E_WEB_PORT} \\"
echo "  E2E_MOCK_BASE_URL=http://127.0.0.1:${E2E_MOCK_PORT} \\"
echo "  E2E_MODEL_MODE=mock npx playwright test --grep @fast"
