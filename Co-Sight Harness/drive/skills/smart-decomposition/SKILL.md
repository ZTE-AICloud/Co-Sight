---
name: smart-decomposition
description: "Use when planning stage needs to split an analyzed manifest into SMART-compliant executable taskRecords. Activated by planner after analyzer writes manifest.md."
user-invocable: false
---

# Smart Decomposition

拆 plan 阶段任务为 SMART 合规的 `taskRecord.yaml`。3 套规则：

- **SMART 原则**（任务质量）
- **5 类任务分类**（任务粒度）
- **5 条拆分规则**（拆分方法）

任何 `taskRecord.yaml` 必须同时满足。

## 适用场景

| 场景 | 用什么 |
|------|------|
| 拆分 plan 阶段的任务 | 全部 3 套规则 |
| 评估已有任务是否合格 | SMART + 类别判定 |
| 决定任务粒度 | 5 类任务 |
| 决定是否需要再拆 | 5 条规则 |

## 使用规则

### 1. SMART 原则

每个 task **必须**满足 SMART 5 个属性：

| 属性 | 含义 | 检查方法 |
|------|------|----------|
| **S**pecific | 任务做什么，清晰无歧义 | 读完 task name + steps 能动手 |
| **M**easurable | 完成有明确标准 | AC 至少 1 个 PASS/FAIL 判定 |
| **A**chievable | 在合理时间内能完成 | 估算时间 < 单 session 长度 |
| **R**elevant | 对应 user story 或 AC | 至少 1 个 user story 引用 |
| **T**ime-bound | 估算 token / 时间 | estimated_duration 字段 |

违反 SMART 的任务必须重新拆分。

### 2. 5 类任务

| 类别 | 上下文上限 | 工具调用 ≤ | 典型用例 |
|------|----------|-----------|----------|
| **simple** | 4-8k | 3 | 改一行配置、查询 API、执行单条 shell |
| **single_file** | 12-16k | 5 | 改函数、加注释、修已知 bug |
| **multi_file** | 20-32k | 8 | 调用链理解、跨文件重构、读 8 文件汇总 |
| **planning** | 16-20k | 4 | 设计文档、多步测试计划 |
| **search** | 不应直接读上下文 | — | 由 Skill 处理（grep + 语义检索） |

### 3. 5 条拆分规则（按优先级）

| # | 规则 | 优先级 | 检查 |
|---|------|--------|------|
| **1** | **单一输出断言** | ⭐⭐⭐ 必做 | 每个 task 结束时必须产生 1 个可断言的产物 |
| **2** | **工具切换边界** | ⭐⭐ 应做 | 频繁切不同域的工具 → 拆 |
| **3** | **依赖反转** | ⭐⭐⭐ 必做 | 大数据量输出 → 写文件而非参数传递 |
| **4** | **上下文纯净度** | 折扣最大 | 工具返回 > 4k 但有用 < 1k → 结束当前 task。当前人工 review，不做自动判定 |
| **5** | **可并行性** | ⭐ 应做 | 无写冲突 → 拆出独立 task，标可并行 |

### 4. 拆分后检查清单

- [ ] SMART 全部满足
- [ ] 类别已定（5 类之一）
- [ ] 5 条规则按优先级检查
- [ ] 工具调用 ≤ 10（硬上限）
- [ ] 依赖链长度 ≤ 4 步
- [ ] 分支条件 ≤ 5 条
- [ ] 关键变量 ≤ 5 个

**完成标准：全部 7 项打勾才算 taskRecord 有效**。

例子与错误分类样例见 `references/anti-patterns.md`。