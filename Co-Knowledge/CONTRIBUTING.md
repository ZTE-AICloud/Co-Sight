# 贡献指南

感谢参与 Knowledge Studio。提交代码前请阅读本文件与 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 开发环境

- Node.js ≥ 22.22
- Python 3.11
- Docker + Docker Compose v2（后端单测与整栈运行）
- 前端依赖：`cd frontend && npm ci`
- 后端依赖：`pip install -r backend/requirements.lock`

## 本地验证

提交前至少运行：

```bash
bash tools/run-tests.sh                 # 前端 vitest + 后端 pytest
python3 tools/check-architecture.py --strict
python3 tools/verify/generate-rkb-openapi.py --check
python3 tools/verify/exposure-audit.py --check
```

前端单测也可以单独跑：`cd frontend && npm run test:unit`。

## 提交规范

- 使用 Conventional Commits：`feat:` / `fix:` / `refactor:` / `docs:` / `test:` / `chore:` / `perf:` / `ci:`
- 一个提交只做一件事；修复缺陷时补回归用例。
- 不要提交 `deploy/.env`、`backups/`、`.metrics-data/`、日志或本地 IDE 配置。
- `backend/LICENSE`、`frontend/LICENSE`、`frontend/THIRD-PARTY-NOTICES.md` 是镜像构建上下文的副本；修改根 `LICENSE` / `THIRD-PARTY-NOTICES.md` 后必须同步复制（CI 会校验 `cmp`）。
- 接口契约以 `contracts/` 为唯一来源；改接口先改契约，再改实现与快照。

## 代码风格

- 后端：PEP 8、ruff、类型注解；注释只描述**当前行为**，不要写迁移史、日期或内部服务名。
- 前端：Vue 3 + Composition API；样式使用设计 token，不硬编码调色板与间距。
- 注释与文档使用中文或英文均可，但同一文件保持一种语言。

## 文档

- 面向用户的文档放在 `docs/`，只描述当前支持的能力与使用方式。
- 新增或修改外部 API 时，同步更新 `docs/external-api/` 并重新生成 HTML：

```bash
node tools/docs/build-external-api-html.mjs docs/external-api/knowledge-studio-api.md
node tools/docs/build-external-api-html.mjs docs/external-api/agent-rest-access.md
```

## 许可证

提交即表示你同意以 [Apache License 2.0](LICENSE) 授权你的贡献。请确保你有权提交相关代码，并保留第三方组件的版权与许可声明。
