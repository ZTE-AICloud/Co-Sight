# 贡献指南

感谢参与 Co-Sight Harness。提交代码前请阅读本文件与 [`README.md`](README.md)。

## 开发环境

- Node.js `^22.19.0` 或 `>=24.0.0`
- pnpm `11.28.5`（用 `corepack enable` 对齐）
- 运行真实 Agent 时需要本机安装 Claude Code CLI；不安装不影响框架与各模块的创建、管理、浏览功能

本仓库位于 [Co-Sight](https://github.com/ZTE-AICloud/Co-Sight) 仓库的 `Co-Sight Harness/`
子目录，所有命令都在该子目录下执行：

```bash
git clone https://github.com/ZTE-AICloud/Co-Sight.git
cd "Co-Sight/Co-Sight Harness"
corepack enable
pnpm install
pnpm dev
```

## 提交前门禁

提交前至少运行：

```bash
pnpm verify           # typecheck + lint + test，覆盖率阈值 80%
```

涉及打包或启动脚本时，追加：

```bash
pnpm package
pnpm smoke:package
```

## 提交规范

- 使用 Conventional Commits：`feat:` / `fix:` / `refactor:` / `docs:` / `test:` / `chore:` /
  `perf:` / `ci:`
- 一个提交只做一件事；修复缺陷时补回归用例。
- 不要提交 `.env`、`cosight.env`、`.credentials.yaml`、`.module-token`、日志、数据库文件、
  `node_modules/`、`dist/`、`.package/`、`.smart-factory/` 等本地运行产物。

## 代码风格

- 框架与前端：TypeScript，保持类型显式；文件聚焦、函数短小，避免深层嵌套。
- 插件：沿用 Drive 的内部布局（`.claude-plugin/` + `agents/` + `skills/` + `hooks/` + `tests/`）。
- 注释与文档可使用中文或英文，但同一文件保持一种语言。
- 不硬编码密钥、内网地址或本机绝对路径；示例地址使用 `localhost` 或 RFC 5737 文档地址
  （`203.0.113.0/24`）。

## 新增组件

1. 顶层目录使用 kebab-case，与组件英文名一一对应。
2. 插件类组件在 `.claude-plugin/plugin.json` 登记 `name` / `version` / `license` /
   `agents` / `skills` / `commands` / `hooks`。
3. 服务类组件一般包含 `server/`、`web/`、`docs/`；模块根不放 `package.json`，所有 pnpm
   命令在 `Co-Sight Harness/` 根执行。
4. 新增模块接入前，先在 `framework/docs/modules/` 登记清单，再按
   [`module-artifact-integration.md`](framework/docs/module-artifact-integration.md)
   决定是否进产物。

## 文档

行为变更时同步更新对应文档：

- 用户可见行为：`README.md` / `README.en.md` / `QUICKSTART.md`
- 接口契约：`framework/docs/` 与 `framework/shared/src/contracts/`
- 架构决策：`framework/server/docs/architecture.md`、`framework/docs/framework-decisions.md`

## Pull Request

- 说明动机、改动范围与验证方式。
- 关联相关 Issue。
- 确保 CI 与 `pnpm verify` 通过，且分支已与目标分支同步。

## 许可

提交即表示你同意以 [Apache License 2.0](LICENSE) 授权你的贡献。
