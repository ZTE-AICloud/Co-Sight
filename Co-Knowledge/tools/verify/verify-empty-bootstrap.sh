#!/usr/bin/env bash
# 空卷启动验证：默认 compose 能否只靠 deploy/init/pg/00-schema.sql 建起核心表。
#
# 跑法：bash tools/verify/verify-empty-bootstrap.sh
# 退出码：0 = PASS；非 0 = 失败（会打印实际计数）。
#
# 隔离：使用独立的 compose project 与临时 override（去掉宿主 5432 端口），
# 不触碰正在运行的 rag-studio 栈；退出时 down -v 清理。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
PROJECT="rag-studio-bootstrap-verify"
OVERRIDE="$(mktemp)"

cleanup() {
    docker compose -p "$PROJECT" --env-file "$REPO_ROOT/deploy/.env" \
        -f "$REPO_ROOT/deploy/docker-compose.yml" -f "$OVERRIDE" down -v >/dev/null 2>&1 || true
    rm -f "$OVERRIDE"
}
trap cleanup EXIT

cat > "$OVERRIDE" <<'YAML'
services:
  postgresql:
    ports: !override []
YAML

docker compose -p "$PROJECT" --env-file "$REPO_ROOT/deploy/.env" \
    -f "$REPO_ROOT/deploy/docker-compose.yml" -f "$OVERRIDE" \
    up -d --wait postgresql >/dev/null

run_sql() {
    docker exec "${PROJECT}-postgresql-1" psql -U rag -d rag_studio -At -c "$1"
}

# 只数 BASE TABLE：pg_stat_statements 会在 public 建 2 个视图，旧查询因此恒偏大。
public_tables="$(run_sql "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")"
kb_index_schema="$(run_sql "SELECT count(*) FROM information_schema.schemata WHERE schema_name='kb_index';")"
unique_indexes="$(run_sql "SELECT count(*) FROM pg_indexes WHERE indexname IN ('kb_kbase_kbase_id_uidx','kb_node_relation_kbase_node_uidx');")"
foreign_keys="$(run_sql "SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND contype='f';")"
table_comments="$(run_sql "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname NOT LIKE 'pg_%' AND obj_description(c.oid,'pg_class') IS NOT NULL;")"
new_names="$(run_sql "SELECT count(*) FROM pg_constraint WHERE conname IN ('operator_param_pkey','flow_draft_workflow_id_uidx','flow_release_workflow_version_uidx','flow_workflow_workflow_id_uidx');")"
checks="$(run_sql "SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND contype='c';")"

fail=0
[[ "$public_tables" == "22" ]] || { echo "FAIL public tables: $public_tables != 22"; fail=1; }
[[ "$kb_index_schema" == "1" ]] || { echo "FAIL kb_index schema: $kb_index_schema != 1"; fail=1; }
[[ "$unique_indexes" == "2" ]] || { echo "FAIL unique indexes: $unique_indexes != 2"; fail=1; }
[[ "$foreign_keys" == "11" ]] || { echo "FAIL foreign keys: $foreign_keys != 11"; fail=1; }
[[ "$table_comments" == "22" ]] || { echo "FAIL table comments: $table_comments != 22"; fail=1; }
[[ "$new_names" == "4" ]] || { echo "FAIL new constraint names: $new_names != 4"; fail=1; }
[[ "$checks" == "15" ]] || { echo "FAIL check constraints: $checks != 15"; fail=1; }

if [[ "$fail" -eq 0 ]]; then
    echo "PASS empty bootstrap: public=22, kb_index=1, unique_indexes=2, fks=11, comments=22, checks=15"
fi
exit "$fail"
