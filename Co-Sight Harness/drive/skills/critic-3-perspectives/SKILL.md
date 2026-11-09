---
name: critic-3-perspectives
description: Use after planner finishes taskRecord.yaml to review the plan with CRITICAL/MAJOR/MINOR severity, before transitioning to execute stage.
user-invocable: false
---

# Critic 3-Perspectives

## 模式定义

drive 的 plan 质量检查：写完 plan 后，由 planner agent 内部以 3 个独立视角（executor / stakeholder / skeptic）审视 plan，按 CRITICAL / MAJOR / MINOR 分级，CRITICAL 触发 HITL gate。

3 视角分工：

- **executor**：taskRecord 字段齐全 / 步骤清晰 / AC 可验证 / 依赖明确 / 工具可达 / 类别匹配
- **stakeholder**：范围覆盖 user story / AC 覆盖 / 风险缓解 / out-of-scope 不涉及 / NFR 有对应 / Milestone 有 gate
- **skeptic**：失败点 ≥ 3 + mitigation / 资源风险 / 集成风险 / 外部依赖 / 边界 case

实现方式：planner agent 内部 self-check（**非**多 agent 循环）。

## 适用场景

| 场景 | 用 3 视角 |
|------|------|
| Plan 写完，进 Execute 前 | 必跑 |
| Plan 写完，发现 task 数过多 | 跑 stakeholder 视角 |
| Plan 写完，复杂度 ≥ complex | 必跑 |
| Plan 写完，但 auto_mode=true | 仍跑 |
| Plan 写完，trivial 任务 | 简化为 1 视角（executor） |

## 使用规则

### 1. 三个视角

#### Perspective 1: executor

**问题**：每个 task 能用 taskRecord.yaml 跑吗？

| 检查项 | PASS 条件 |
|------|------|
| 字段齐全 | name/steps/read_first/verify/AC/done 都有 |
| 步骤清晰 | LLM 读完 steps 能动手，不需猜 |
| AC 可验证 | 至少 1 个 PASS/FAIL 判定标准 |
| 依赖明确 | depends_on 列表完整 |
| 工具可达 | 工具调用权限足够（不在 denylist） |
| 类别匹配 | task_category 与 context_limit_tokens 一致 |

#### Perspective 2: stakeholder

**问题**：plan 实现了 user intent 吗？

| 检查项 | PASS 条件 |
|------|------|
| 范围覆盖 | 每个 user story 至少 1 个 task 支持 |
| AC 覆盖 | manifest.md 的每个 AC 有 task 支持 |
| 风险缓解 | 文档列出的 risk 有对应 mitigation task |
| 不做的范围 | out-of-scope 没 task 涉及 |
| 非功能需求 | NFR（性能/可靠性/安全）有对应 task |
| Milestone 对应 | 每个 milestone 有完成判定标准 |

#### Perspective 3: skeptic

**问题**：哪里会失败？

| 检查项 | PASS 条件 |
|------|------|
| 失败点 | 至少识别 3 个可能失败点 |
| Mitigation | 每个失败点有应对方案 |
| 资源风险 | 时间/token 估算合理 |
| 集成风险 | Wave 间衔接明确 |
| 外部依赖 | 外部资源/权限考虑 |
| 边界 case | 错误输入、空数据、并发等考虑 |

### 2. 失败分级

| 严重度 | 含义 | LLM 动作 |
|------|------|------|
| **CRITICAL** | AC 全空 / task 数 = 0 / Plan 覆盖不到 user story / Wave 循环依赖 | stop + 让用户看（返回 `status: blocked`） |
| **MAJOR** | Wave 顺序错 / 依赖缺失 / 失败点无 mitigation | 自动修复后继续，记 `critic_check.notes` |
| **MINOR** | 命名 / 注释 / 估算不准 | 记 self-decisions，继续 |

### 3. 输出：critic_check 字段

写入 `plan-N.yaml` 的 `critic_check` 字段（含 3 视角各自的 status / notes / issues_count + overall / critical / major / minor）。完整格式见 `references/critic-format.md`。

**同时落 3 个独立 artifact** 到 `.drive/<plan_dir>/artifacts/critic/plan-N/`：

- `executor.md` —— executor 视角的完整 check 记录（每项 PASS/FAIL + 依据）
- `stakeholder.md` —— stakeholder 视角
- `skeptic.md` —— skeptic 视角

落文件时若任一视角含 CRITICAL，artifact 文件加前缀 `CRITICAL-` 以便扫描
`artifacts/critic/` 时一眼定位。

### 4. 返回值

| 情况 | 返回 status | 后续动作 |
|------|------|------|
| 3 视角都 PASS | `completed` | 调 `/state-machine transition` 进 execute |
| 有 CRITICAL 问题 | `blocked` | 触发 HITL |
| 全部 FAIL | `failed` | 写 continue-here，提示用户 |