---
name: plan-approval
description: >
  计划审批多 Agent——Leader 产出计划后必须暂停等用户显式批准才分发执行;
  执行者按 5-7 文件规模约束领任务并行开工; 审查发现的问题修复后不自动重审,
  必须再次用户确认（Review Loop Protocol, 防无限审查-修复循环）;
  实现者/审查者只回简洁结构化报告, Leader 上下文保持精简。
  当任务需要人审把关计划与重审、多实现者分工、上下文成本敏感时使用。
version: "1.0.0"
---

# Plan Approval — 计划审批与受控审查回环 Agent

本 Agent 是一个三角色协作系统：Leader（主会话）产出计划并管控全局节奏,
Implementer（实现者）按领到的任务块执行, Reviewer（审查者）对实现产出
做质量审查。核心原则：**计划与重审两处人审把关, 其余环节自动流转**——
人只出现在决策点, 不出现在传输带上。

## When to Use

- 计划质量影响大、错误分发代价高的任务（先批准后执行, 不做返工）
- 多实现者分工且需要独立审查者把关的构建任务
- Leader 上下文窗口敏感（实现/审查细节不回流, 只回结构化摘要）

## 角色与职责

### Leader（主会话）

- 探索代码库, 产出计划（任务块划分 + 依赖关系 + 并行/串行判定）
- 把任务块分发给 Implementer（同消息内多个 Task 调用 = 并行）
- 把实现产出送 Reviewer 审查
- 向用户汇报: 每阶段开始/完成各一次, 每 Agent 3-5 行摘要
- **不搬运** Implementer/Reviewer 的全量输出——只取结构化摘要

### Implementer（实现者, 每任务块一个）

- 领到任务块 + 必要的上下文（前置任务的结构化摘要, 非全量历史）
- 完成后回结构化报告: 变更文件清单 + 关键决策 + 已知遗留
- 单次任务规模约束: 处理 **5-7 个文件**——超过即应拆分, 不硬扛
  （经验值: 超过 7 文件上下文窗口吃紧, 质量下降）

### Reviewer（审查者, 独立上下文）

- 对实现产出做质量审查（正确性/错误处理/安全/性能/命名/测试覆盖）
- 按优先级回报告: critical / warning / suggestion 三档
- 修复后**不自动重审**——Review Loop Protocol 要求用户显式确认才重跑

## 核心机制（三件）

### 1. 双点人审（计划批准 + 重审确认）

```
Leader 产出计划
  │
  ▼
AskUserQuestion: 批准执行?（方案可见, 风险 ≥2 条, 抽查 ≥3 件）
  │
  ├── 否 → 收回改计划, 再次提交
  └── 是 → 分发 Implementer
              │
              ▼
         Reviewer 审查
              │
              ▼
         AskUserQuestion: 修复完成, 重审?（不默认重跑）
           ├── 是 → Reviewer 重审一轮
           └── 否 → 结束, 标记 needs_review 待后续
```

两处人审都是显式 AskUserQuestion, 不是静默默认通过。这是防自动化系统
失控的根本闸门: 人只在决策点出现, 但每次出现都真有决定权。

### 2. 任务看板与状态留痕

任务六态: `Idea → Planned → Pending → In Progress → Needs Review → Completed`。
状态变迁落盘任务文件（title/description/status/assigned_to/tags）, 支持跨
会话追溯"谁在什么时候做了什么、卡在哪"。

### 3. 上下文精简纪律

- Implementer 回报: 变更文件列表 + 关键决策——**不回放执行过程**。
- Reviewer 回报: critical / warning / suggestion 三档——**不逐行点评**。
- Leader 向用户汇报: 每 Agent 3-5 行摘要——**不搬运全量输出**。

规模约束的来源: 审查者/实现者的全量输出若全部回流 Leader, Leader 的
上下文会被中间结果塞爆, 丢失对全局的把握。结构化摘要是抗上下文爆炸
的纪律, 不是可选优化。

## Execution Steps

### Step 1 — 计划产出（Leader）

探索代码库 → 划分任务块 → 判定并行/串行 → 落盘计划文件。

### Step 2 — 计划人审（AskUserQuestion）

展示方案（文件清单 + 风险 + 抽查项）, 用户批准后继续; 不批准则收回
修订。

### Step 3 — 分发执行（Leader → Implementer）

独立无依赖的任务块同消息并行分发; 有依赖的串行, 前置结果以结构化
摘要传给后续。

### Step 4 — 审查（Leader → Reviewer）

实现产出全部到位后送 Reviewer; Reviewer 按三档优先级回报告。

### Step 5 — 重审人审（AskUserQuestion）

修复完成后 AskUserQuestion 确认是否重审; 不重审则标记 Needs Review
收尾, 不无限循环。

### Step 6 — 汇报与归档（Leader）

向用户出最终摘要; 任务看板状态置 Completed; 过程锚件归档。

## Not for

- 单文件/小改动（3 行级修改 Leader 直做, 不分发——分发开销大于收益）
- 无审查需求的一次性脚本（Reviewer 角色空置, 退化两角色）
- 强实时交互场景（双点 AskUserQuestion 引入等待, 不适合争分夺秒任务）
