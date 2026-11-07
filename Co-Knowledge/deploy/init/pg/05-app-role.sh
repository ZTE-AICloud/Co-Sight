#!/usr/bin/env bash
# 创建**非 superuser** 应用角色（空卷初始化时执行一次）。
#
# 应用（RKB）用这个角色连接业务库；运维仍用 POSTGRES_USER（superuser）。
# 角色需要能：
#   * 连接 rag_studio；
#   * 在 kb_index 里建/删动态表（每个知识库一对表）；
#   * 对静态表做 DML；
#   * 建 model_registry 的索引（所以把 public/kb_index 的对象所有权交给它）。
# 它**不能**：建扩展、建库、建角色、访问其它库。
#
# 本脚本只在空卷初始化时执行一次。
set -euo pipefail

APP_USER="${RKB_DB_USER:-}"
APP_PASSWORD="${RKB_DB_PASSWORD:-}"

if [ -z "$APP_USER" ] || [ -z "$APP_PASSWORD" ]; then
  echo "[init] RKB_DB_USER/RKB_DB_PASSWORD 为空，跳过应用角色创建"
  exit 0
fi

if [ "$APP_USER" = "$POSTGRES_USER" ]; then
  echo "[init] RKB_DB_USER 与 POSTGRES_USER 相同，跳过应用角色创建"
  exit 0
fi

echo "[init] 创建非 superuser 应用角色: $APP_USER"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v app_user="$APP_USER" \
     -v app_password="$APP_PASSWORD" \
     -v db_name="$POSTGRES_DB" \
     -v db_owner="$POSTGRES_USER" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
              :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
              :'app_user', :'app_password')\gexec

GRANT CONNECT, CREATE ON DATABASE :"db_name" TO :"app_user";
GRANT USAGE, CREATE ON SCHEMA public TO :"app_user";
GRANT USAGE, CREATE ON SCHEMA kb_index TO :"app_user";

-- 静态表/序列：DML + 序列取号
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_user";

-- 动态表需要 DROP/CREATE：所有权交给应用角色。
-- ⚠️ 不能用 DO 块：psql 变量（:'app_user'）**不会**在 dollar-quoted 块里展开，
-- 实测报 `syntax error at or near ":"`。用 \gexec 生成语句。
SELECT format('ALTER TABLE %I.%I OWNER TO %I', schemaname, tablename, :'app_user')
FROM pg_tables WHERE schemaname IN ('public', 'kb_index')\gexec

SELECT format('ALTER SEQUENCE %I.%I OWNER TO %I', schemaname, sequencename, :'app_user')
FROM pg_sequences WHERE schemaname IN ('public', 'kb_index')\gexec

-- 审计触发器函数：运行期 DDL 会 CREATE OR REPLACE 它，owner 必须是应用角色。
SELECT format('ALTER FUNCTION public.set_updated_at() OWNER TO %I', :'app_user')
WHERE to_regprocedure('public.set_updated_at()') IS NOT NULL\gexec

ALTER SCHEMA kb_index OWNER TO :"app_user";

-- 以后由 superuser 建的对象也自动授权给应用角色。
ALTER DEFAULT PRIVILEGES FOR ROLE :"db_owner" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"db_owner" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
SQL
