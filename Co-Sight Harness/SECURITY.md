# 安全策略

## 报告漏洞

请**不要**在公开 Issue 中披露安全问题。本项目位于
[Co-Sight](https://github.com/ZTE-AICloud/Co-Sight) 仓库的 `Co-Sight Harness/` 子目录，
请使用 **Co-Sight 仓库**的私密报告通道：

1. 打开 <https://github.com/ZTE-AICloud/Co-Sight> 的 **Security** 选项卡；
2. 选择 **Report a vulnerability**；
3. 描述影响版本、复现步骤、影响与建议修复。

我们会在 5 个工作日内确认收到，并在修复可用后与你协调披露时间。

## 支持范围

安全修复只针对最新发布版本。旧版本请先升级再复现。

## 部署安全基线

Co-Sight Harness 是**本地优先**的 Agent 宿主，默认按单机使用设计：

- 默认只监听 `127.0.0.1:4300`。不要把框架端口直接暴露到不受信网络；确需远程访问时，
  请在前置反向代理终止 TLS 并配置访问控制。
- 模型密钥、知识库账号等凭据保存在数据目录（默认 `~/.cosight-harness/`）下的
  `.credentials.yaml`，权限应为 `0600`；不要提交到版本控制。
- 模块面令牌位于数据目录下的 `.module-token`，供本机模块进程读取模型配置；不要复制、
  外传或写入前端。
- 通过环境变量注入的密钥只在服务端使用，不下发浏览器。
- 模块以 iframe 方式接入时，宿主按清单校验来源（`allowedOrigins`）；新增模块请在
  `framework/docs/modules/` 登记后再接入。
- 本发行物不包含、不分发 Claude Code CLI 或 Claude Agent SDK；真实执行能力由用户在本机
  安装并自行承担相应条款与安全责任。

## 依赖与漏洞跟踪

- 框架依赖锁定在根 `pnpm-lock.yaml`；各服务组件另有 `package-lock.json`。
- 升级依赖时建议运行：

```bash
pnpm install
pnpm verify
pnpm audit
```

- 插件会在安装/卸载时校验包完整性；不要绕过校验直接覆盖 `~/.claude/plugins/` 下的文件。

## 已知边界

- 本产品面向单机/单租户场景，不内置多租户数据隔离与细粒度角色体系。
- 工作区绑定目录、模块入口等配置由本机用户维护；多用户共用一台机器时应使用独立系统账号
  与独立数据目录。
- 自定义 Agent / Skill 视为可信代码：它们可以调用本机工具与模型。只安装你信任的资产包。
