#!/usr/bin/env bash
# text2sql / text2sql_index 的应用角色授权（空卷初始化时执行一次）。
#
# 18-text2sql.sql 在 05-app-role.sh 之后执行，所以授权必须单独成一步。
# 应用角色需要：两个 schema 的 USAGE、现有表的 DML、发布/归档函数的 EXECUTE。
# text2sql 里的表由迁移 owner 维护，应用角色不建表；
# text2sql_index 相反——里面的 t2s_vec_* 表就是应用在版本构建时按数据源建的，
# 所以这里必须给 CREATE，并配 DEFAULT PRIVILEGES 让新建表自动可读写。
set -euo pipefail

APP_USER="${RKB_DB_USER:-}"

if [ -z "$APP_USER" ] || [ "$APP_USER" = "$POSTGRES_USER" ]; then
  echo "[init] RKB_DB_USER 为空或等于 POSTGRES_USER，跳过 text2sql 授权"
  exit 0
fi

echo "[init] 授予应用角色 text2sql / text2sql_index 权限: $APP_USER"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v app_user="$APP_USER" \
     -v db_owner="$POSTGRES_USER" <<'SQL'
GRANT USAGE ON SCHEMA text2sql TO :"app_user";
GRANT USAGE, CREATE ON SCHEMA text2sql_index TO :"app_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA text2sql TO :"app_user";
-- 动态向量表在建表语句里带 REFERENCES text2sql.t2s_knowledge(id)，建外键需要 REFERENCES 权限。
GRANT REFERENCES ON text2sql.t2s_knowledge TO :"app_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA text2sql_index TO :"app_user";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA text2sql TO :"app_user";

ALTER DEFAULT PRIVILEGES FOR ROLE :"db_owner" IN SCHEMA text2sql
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"db_owner" IN SCHEMA text2sql
    GRANT EXECUTE ON FUNCTIONS TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"db_owner" IN SCHEMA text2sql_index
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
SQL
