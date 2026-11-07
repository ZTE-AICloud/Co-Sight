#!/usr/bin/env bash
# 每日保留期清理：查询轨迹 30 天、会话 30 天、终态任务 90 天。
#
# 宿主 cron 示例（每天 03:17；路径按实际仓库位置替换）：
#   17 3 * * * /path/to/ragstudio/tools/ops/run-retention.sh \
#     >> /var/log/ragstudio-retention.log 2>&1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
. deploy/.env
set +a
export RKB_DB_HOST="${RKB_DB_HOST:-127.0.0.1}"

echo "=== $(date '+%F %T') retention start ==="
python3 tools/ops/prune-query-traces.py --apply --yes --older-than-days 30
python3 tools/ops/prune-auth-sessions.py --apply --yes --older-than-days 30
python3 tools/ops/prune-task-history.py --apply --yes --older-than-days 90
echo "=== $(date '+%F %T') retention done ==="
