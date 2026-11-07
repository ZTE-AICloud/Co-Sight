"""账号与登录会话领域（本地账号体系）。

本包只放**认证**（authentication）：账号、口令哈希、登录会话、`/auth/*` 接口。
不做角色/权限门禁与按用户数据隔离（见 ``docs/auth-login.md`` 的已知限制）。

注意：本包只处理账号与会话；数据库/ES 连接信息在
``infrastructure.db.connection_info`` 与 ``infrastructure.config.constants``，
两者互不影响。

``schema.py`` 必须保持**不 import FastAPI/DB**，供 CLI 在最小依赖下导入。
"""
