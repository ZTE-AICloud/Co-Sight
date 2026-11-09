# Repository Guidelines（技术层样例——按项目改写）

## Project Structure

- `src/` — 源码主目录（子目录按职责划分: agent 核心 / 工具 / 外部适配）
- `scripts/` — 构建与发布脚本
- `.agent/` — Agent 运行时配置（模型选择持久化等, gitignored）

## Build, Test, and Development Commands

- 安装依赖: 按包管理器标准命令（npm/pnpm/bun）
- 类型检查: 按 tsconfig 严格模式跑
- 测试: 标准 test runner, 推前必跑

## Coding Style & Conventions

- 严格类型; 避免 `any`
- 文件保持精简; 重复逻辑抽公共函数
- 非显然逻辑加简短注释
- 不主动加日志, 不主动建 README（除非明确要求）

## Environment Variables

- API key 类一律走环境变量, **永不入库**; 缺失时启动即报错, 不静默降级。

## Version & Release

- SemVer; tag 前缀 `v`
- 发布前必须用户确认, 不自动 push/publish

## Security

- `.env` 与运行时配置 gitignored
- 密钥不写入源码/日志/测试 fixture
