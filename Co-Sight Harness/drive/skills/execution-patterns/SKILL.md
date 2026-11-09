---
name: execution-patterns
description: Use when reasoning about drive's execute-stage runtime patterns: wave-based parallelism, whitelist file protection, retry ceilings, and checkpoint triggers.
user-invocable: false
---

# Execution Patterns

## 模式定义

drive Execute 阶段的 4 个关键模式：

1. **Wave 并发**（拓扑排序）
2. **Whitelist 保护**（默认拒绝，命中白名单才放行）
3. **3-Retry 上限**（fail fast）
4. **Continue-Here 触发**（每 Wave 完成后写恢复点）

## 使用规则

### 1. Wave 并发

- **Wave**: 一组无依赖、可并行的 task
- **Wave 1**: 无依赖 task
- **Wave 2+**: 依赖前 Wave 完成
- **排序**: planner 标注每个 task 的 `depends_on` 逻辑依赖；wave 拓扑由确定性 helper（`wave-scheduling` skill 的 `schedule-waves`）从 `depends_on` 计算，写入 `waves.yaml`
- **边界标注**: `waves: []` 必须显式存在，无论是否真并发
- **Wave barrier 强约束**: 每 wave 收尾时 `wave-barrier` skill 的 `aggregate` 强制对账 ——
  `summaries` 的 task_id 集合必须等于 `waves.yaml[wave_n].tasks` 的 task_id 集合。
  缺 / 多 / 重复 → 不写 state。详见 `references/wave-barrier.md`。
- **fs diff barrier**: 状态为 done 的 summary 必须声明 `files_changed` 非空，
  否则 `aggregate` 拒写。worker 报完成但 fs 无变化 → 不写 state，主对话
  补派或确认 task 不应改文件。

### 2. Whitelist 保护

写 `.drive/<plan_dir>/` 受 hook 白名单约束。命中白名单才放行，不在白名单的写入会被 hook 拒绝（exit 2）。

路径分类与允许列表见 `references/whitelist-patterns.md`。

### 3. 3-Retry 上限

每个 task 最多重试 3 次。3 次全部失败 → 标记 `permanent_failed`，写 `continue-here.md`，触发 HITL 升级。

### 4. Continue-Here 触发

**触发时机**：

- 每个 Wave 完成时
- Task 失败达 max_retries
- 用户主动 `/pause`

**不触发**：每个 Task 完成时（太细）。