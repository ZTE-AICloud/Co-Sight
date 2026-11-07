# 安全策略

## 报告漏洞

请**不要**在公开 Issue 中披露安全问题。优先使用 GitHub 的私密报告通道：

1. 打开仓库页面的 **Security** 选项卡；
2. 选择 **Report a vulnerability**；
3. 描述影响版本、复现步骤、影响与建议修复。

我们会在 5 个工作日内确认收到，并在修复可用后与你协调披露时间。

## 支持范围

安全修复只针对最新发布版本。旧版本请先升级再复现。

## 部署安全基线

- **不要**把 80 端口直接暴露到不受信网络。默认 compose 不提供 TLS；生产部署应在前置反向代理终止 TLS，并只允许代理访问本服务。
- 默认 `AUTH_MODE=local`：首次启动生成管理员随机口令（容器内 `/data/rkb/initial-admin-password`，0600），首次登录强制改密。未显式设置 `AUTH_MODE` 时按 `local` 处理；需要关闭应用层鉴权的场景必须显式写 `AUTH_MODE=none`。
- `AUTH_MODE=gateway` 只检查网关令牌头是否存在，**必须**配合会剥离并校验该头的前置网关使用。
- 模型管理、算子导入与连接测试仅管理员可用。
- 自定义算子按**可信代码**对待：执行时有内存/结果/时间限制、环境变量白名单与 AST 危险调用扫描，但这些是资源与运行时约束，**不是安全边界**。只导入你信任的算子包；需要强隔离时，请把算子执行放到独立容器/namespace、非 root、无业务卷、默认无网络的环境中。
- 数据库与 OpenSearch 默认只绑定 `127.0.0.1`；`deploy/.env` 含凭据，已被 `.gitignore` 忽略，发布物请使用 `git archive` 生成，不要直接压缩工作目录。
- 若部署在 HTTP 代理之后，必须把模型端点域名加入 `NO_PROXY`，否则请求可能被代理接走。

## 依赖与漏洞跟踪

- 后端依赖全量锁定在 `backend/requirements.lock`，前端锁定在 `frontend/package-lock.json`。
- CI 运行单测、架构检查与入口暴露审计。建议在升级依赖时额外运行：

```bash
pip-audit -r backend/requirements.lock
cd frontend && npm audit --omit=dev
```

## 已知边界

- 本产品面向单租户私有化部署，不内置多租户数据隔离与细粒度角色体系；管理员之外的账号不应共享。
- 登录会话 Cookie 的 `Secure` 属性跟随请求协议；未启用 HTTPS 时不会强制 `Secure`。
