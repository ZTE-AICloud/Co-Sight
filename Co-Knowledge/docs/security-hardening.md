# 凭据加密与非 superuser 应用角色

## 1. `model_registry.api_key` 静态加密

### 1.1 格式与算法

- AES-256-GCM，随机 12 字节 nonce，AAD = `model_registry.api_key.v1`；
- 落库格式：`enc:v1:<base64(nonce + ciphertext + tag)>`；
- 读侧：只接受带前缀的密文，无前缀视为非法密文；
- 写侧：自动加密；空值与已加密值幂等；
- 对外接口仍只返回 `apiKeyMasked` / `hasApiKey`，**不返回明文**。

实现：`backend/src/model/crypto.py`；
接线：`backend/src/model/repository_pg.py` 的 `_row_to_record` / `_insert_params` / `_update_params`。

### 1.2 密钥

| 来源 | 说明 |
|---|---|
| `RKB_SECRET_KEY` | 推荐。32 字节 base64 直接用；其它值按 SHA-256 派生 |
| `RKB_SECRET_KEY_FILE` | 默认 `/data/rkb/secret.key`；文件不存在时生成（0600） |
| 默认路径 | 在 `rkb-storage` 卷内，容器重建后仍在 |

> ⚠️ **密钥丢失 = 已加密凭据不可恢复**。多副本部署必须固定使用同一个
> `RKB_SECRET_KEY`。密钥文件不要提交进仓库。

## 2. 非 superuser 应用角色

### 2.1 角色与权限

应用（RKB）用 `RKB_DB_USER`（默认 `rag_app`）连接；运维仍用
`POSTGRES_USER`（superuser）。`rag_app`：

- **是**：LOGIN；`CONNECT, CREATE` on database；`USAGE, CREATE` on `public` / `kb_index`；
  `public` 静态表 DML；`public` 序列取号；`public` / `kb_index` 对象所有权
  （动态表需要 DROP/CREATE，`model_registry` 的 `CREATE INDEX IF NOT EXISTS` 需要 owner）。
- **不是**：superuser / createdb / createrole；不能建扩展、建库、建角色。

### 2.2 创建方式

空卷新部署由 `deploy/init/pg/05-app-role.sh`（`docker-entrypoint-initdb.d`
自动执行）创建角色并移交对象所有权。

### 2.3 切换

```bash
# deploy/.env
RKB_DB_USER=rag_app
RKB_DB_PASSWORD=<强口令>
# 然后重建 RKB
docker compose -f deploy/docker-compose.yml up -d --force-recreate rag-knowledge-base
```

未配置 `RKB_DB_USER` 时，compose 使用 `POSTGRES_USER`。

## 3. 部署前提

凭据加密与数据库角色策略是企业部署的安全基线，落地时需要同时满足：

1. **固定密钥**：生产环境显式设置 `RKB_SECRET_KEY`，或把 `RKB_SECRET_KEY_FILE`
   放在持久卷并纳入备份；不要在多个副本间使用不同密钥。
2. **最小权限连接**：应用使用 `rag_app`（或自定义的 `RKB_DB_USER`）连接数据库，
   运维账号只用于迁移、备份与排障。
3. **网络边界**：PostgreSQL 与 OpenSearch 只绑定回环或内网地址；对外只暴露
   `web` 的对外端口（默认 8080，容器内 80），并由反向代理终止 TLS。
4. **认证入口**：生产环境使用 `AUTH_MODE=local` 或 `gateway`，不要用 `none`；
   首次登录后立即更换管理员口令。见 [`auth-login.md`](auth-login.md) §5。
5. **密钥与口令管理**：`deploy/.env`、密钥文件、备份文件都不进入版本库；
   轮换 `RKB_SECRET_KEY` 前先评估已加密凭据的迁移方式。

## 4. 验证方法

部署后可按下列顺序核对加密与数据库角色是否生效：

```bash
# 1) 应用连接身份应为 rag_app，且不是 superuser
docker compose -f deploy/docker-compose.yml exec postgresql \
  psql -U "$POSTGRES_USER" -d rag_studio \
  -c "SELECT usename, usesuper FROM pg_stat_activity WHERE datname='rag_studio';"

# 2) 新建模型后，库内 api_key 应以 enc:v1: 开头
docker compose -f deploy/docker-compose.yml exec postgresql \
  psql -U "$POSTGRES_USER" -d rag_studio \
  -c "SELECT model_name, left(api_key, 7) FROM public.model_registry;"

# 3) 公开接口只返回掩码
curl -s "$BASE/api/co-knowledge/v1/models" | grep -E 'apiKeyMasked|hasApiKey'
```

密钥丢失时已加密凭据不可恢复；此时需要重新录入模型的 API Key。
