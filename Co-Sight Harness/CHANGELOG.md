# 变更记录

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.0] - 2026-11-09

首个开源版本。

### 组件

- `framework/`：统一入口，左侧栏 + 工作区 + 模块 iframe 宿主 + 模块面 API。
- `cosight-viewer/`：任务中心，Claude Code 会话观测与任务管理（单机版）。
- `smart-factory/`：智慧工厂，对话式构建、预览与评估 Agent。
- `drive/`：声明式多 Agent 编排引擎，支持 `phase` / `dag` 两种编排模式。
- `agent-genesis/`：自然语言需求 → 可运行的 Agent / Skill（Claude Code 与 DSH 双平台）。
- `agent-evaluator/`：黄金集评测、E2E 用例生成 / 执行 / 评分、trace 轨迹审计。
- `skill-optimizer/`：Skill 评测-优化循环（评测 → 缺口分析 → 优化 → 再评测）。
- `cosight-bot/`：个人知识管理（PKM）与标书应答（SOC）。
- `dsh-compat/`：把五个插件挂到 DeepSeek Harness 的兼容层。

### 许可

- 以 Apache License 2.0 发布，Copyright 2026 ZTE Corporation。
- 第三方声明见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。
