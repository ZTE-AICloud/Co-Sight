# Whitelist Patterns

写 `.drive/<plan_dir>/` 受 hook 白名单约束。默认拒绝，命中白名单才放行。

白名单由 `hooks/hooks_protocol.py` 的 `WRITE_WHITELIST_PATTERNS` 定义并强制。
**本文档是白名单的语义说明，不是 source of truth**——如有不一致，以代码为准。

## 允许写入的路径

按"约定"放行，不按"已知路径名"枚举：

### 流程产物（按名字 + `.md` 或 `.yaml` 后缀）

| 路径 | 阶段 |
|------|------|
| `continue-here.{md,yaml}` | pause 时的恢复点 |
| `summary.{md,yaml}` | execute |
| `plan-summary.{md,yaml}` | plan |
| `manifest.{md,yaml}` | analyze |
| `verification(-report)?.{md,yaml}` | evaluate |

### 流程子目录（任意子目录都放行，不逐个枚举）

| 路径 | 说明 |
|------|------|
| `artifacts/...` | worker 产物：`SUMMARY.md`、`resumption.log`、analysis 模式的分析文件 |
| `tasks/*.yaml` | planner 写 taskRecord |
| `bootstrap/...` | drive 流程自身加的子目录（子目录名不固定） |
| `inputs/...` | 用户输入 |

### 状态标记位

- `.pause` — 标记工作流暂停

## 写入被拒（必须走 SDK 通道）

以下路径**不在白名单**，即使有人误加也不放行：

- `executeState.json` —— 状态文件，由 `state_cli.py` 写（fcntl 锁 + 加锁 + revision 自增）
- `run-log.jsonl` —— 审计日志，由 `audit_append.py` 追加
- `state.md` —— 旧版叙事状态文件，**实现里已不存在**，无需白名单

## 写入失败时

如果 hook 拒绝写（exit 2），说明路径不在白名单。两种处理：

1. 改用白名单内路径（首选）
2. 通过 HITL 上报，由 drive LLM 评估是否扩展白名单

> **白名单的扩展原则**：按"约定"放行（如流程子目录），不按"具体子目录名"枚举。
> 任意新增子目录都不需改白名单 —— 流程子目录整体可信（agent 不会自己骗自己）。
> 需要扩展白名单的少数情形：不在约定范围内的、敏感的、用户不应直接写的路径。
