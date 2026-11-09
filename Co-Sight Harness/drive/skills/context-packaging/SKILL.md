---
name: context-packaging
description: Use when executor cold-start IO needs reduction via per-task context snapshots. Activated by planner after schedule-waves succeeds.
user-invocable: false
---

# Context Packaging

## 调用的命令

| 命令 | 作用 | 入参 | 输出 | 失败模式 |
|---|---|---|---|---|
| `pack_context` | 为每个 task 生成 context snapshot，写 `<planning-dir>/context_pack/<task_id>.json` | `--planning-dir` (required) | Envelope `data.{tasks_packed, context_pack_dir}` | `file_missing` / `schema_invalid` |

## 命令契约

### pack_context

调用前：`<planning-dir>/taskRecord.yaml` 与 `<planning-dir>/manifest.md` 都已存在；本 skill 的 `wave-scheduling schedule-waves` 已成功落盘 `waves.yaml`（顺序非强制，但通常在 schedule-waves 之后跑）。

入参：

- `--planning-dir <dir>`（必填）：`.drive/<plan_dir>/` 路径

调用后：每个 task 一份 `.drive/<plan_dir>/context_pack/<task_id>.json`，含 task 字段、依赖列表、上游产物路径。stdout 打印 Envelope JSON。Exit 0 表示成功。

失败模式：

- `file_missing` → `details.path` 列出缺的文件（taskRecord.yaml 或 manifest.md）。补齐再跑。
- `schema_invalid` → `details.error` 含 YAML 解析错误或字段缺失。

## Gotchas

- 这是**性能优化**，不是必需。失败**不阻断**后续执行——worker 启动时若 context_pack 文件不存在或 digest 不匹配（taskRecord 在打包后被改过），自动降级为全量读取。
- 单文件 < 1 KB 量级；N 个 task 总量 ≤ N KB。IO 节省在 worker 冷启动（从 3-5m 降到 <1m）。
- **不在 taskRecord.yaml 修改后再调一次**：必须重跑本脚本，否则 context_pack 的 digest 跟 taskRecord 对不上、worker 自动降级。
- `task_id` 缺失或非 dict 的 task 会被**静默跳过**（不进统计、不报错）。若 `tasks_packed` 远少于 taskRecord 计数，检查 task 格式。

## 调用前 Checklist

- [ ] `<planning-dir>/taskRecord.yaml` 与 `<planning-dir>/manifest.md` 都在
- [ ] 决定失败时的策略：失败阻断后续（保守） / 失败仅记 `fail_notes` 继续（推荐——性能优化不应卡流程）