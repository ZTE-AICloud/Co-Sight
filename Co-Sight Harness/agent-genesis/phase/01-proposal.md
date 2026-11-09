---
project_id: agent-genesis
created: 2026-07-10
version: 0.17.5
automation_level: L2
human_time_budget_daily: 1h
---

# AgentGenesis 需求定义 (v0.17.5)

## Why — 为什么做

- **用户角色**: 开发者 / 架构师 / 技术管理者
- **业务场景**: 从 "I need a code review agent" 开始, 几分钟内得到可独立运行的 Claude Code Agent
- **核心痛点**:
  - 手工编写 Agent 需理解设计模式 / 加载策略 / Anthropic 规范, 学习曲线陡
  - 质量不可控, 靠运气
  - 跨项目重复造轮子
- **预期价值**:
  - Agent 创建时间 2-4h → 5-10min
  - 质量从靠运气 → 就绪度评分 ≥ L2
  - 产物即 Claude Code 原生格式, `cd && claude` 立即可跑
- **成功指标**:
  - 创建成功率 > 95%
  - 平均创建时间 < 10min
  - 首次通过率 > 80%
  - 用户回访率 > 60%

## What — 做什么

- **核心流程** (2 个 pipeline):
  - **agent-creation** (8 步, harness-create): 用户描述需求 → 需求澄清 → 模式匹配 → 方案生成 → 独立审查 → 用户审批 → 文件生成 → 静态验证 → (可选) 运行时评测
  - **skill-foundry** (8 步, 3 mode): 用户描述需求或目标 Skill → 阶段1（create→设计 / optimize|diagnose→7 维诊断）→ 健全性检查 → DC-002 审批 → 构建 / 增量修改 → 静态验证 → 测试生成 / 执行 / 盲评。diagnose 模式 Step 2 后早终止

- **关键特性**:
  - 3 pipeline 共享同一套 main-agent-helpers 状态机（gate 为显式调用, 无常驻 gate-engine）
  - 所有产物直接写 `output/`, 无中间 cp 步骤
  - 9 个 SubAgent 全部独立 context, 6 个 verifier 显式 forbidden_inputs 防完成偏置
  - 5 个 gate 静态检查 + circuit breaker (整 pipeline 5 次 retry 上限)

- **边界**:
  - **做**: 创建 Agent / Skill, 优化 Skill
  - **不做**: 原地改 Agent (需要用户重新跑), 跨非 Claude Code 平台 (Cursor / Windsurf 等)

- **优先级**: Must

## How — 怎么做

### agent-creation 8 步 (详细见 `skills/harness-create/references/workflow.md`；机检清单见 `phase/gates/gates.yaml` triggers[].outputs)

```
Step 0: env-probe (Bash)
Step 1: requirement-clarification (Skill, AskUserQuestion)
Step 2a: pattern-matching (SubAgent, 23 模式级联匹配)
Step 2b: matching-review (SubAgent, 独立审查)
Step 3: build-planning (SubAgent, 含 6 文件产出)
Step 3c: DC-001 人审 (4 步结构化)
Step 4: implementation (SubAgent, for 循环 + 断点恢复)
Step 5: readiness-verification (SubAgent)
Step 5.5: user-choice (AskUserQuestion: Skip 或 Run Step 6)
Step 6a/6b/6c: 测试生成 / 执行 / 盲评 (可选, 默认 Skip)
```

### 异常流程

- **Gate FAIL**: 1-3 次 retry → 退到上一步 → 超限 escalate
- **Circuit breaker**: 整 pipeline 5 次 retry 累计 → global ESCALATE → AskUserQuestion
- **User 取消** (DC-001/DC-002/DC-010 timeout 24h): 标记 BLOCKED, 询问继续 / 跳过 / 终止

### 业务规则

- **设计模式**: 23 模式, 6 类 (工作流 / 知识 / 数据 / 交互 / 约束 / 自进化)
- **级联匹配**: Tier 0 MN 判定 → Tier 1 子集过滤 → Tier 2 精细匹配
- **独立性**: 6 个 verifier SubAgent 都有 forbidden_inputs, 防止自我验证
- **gates-engine**: 3 层 (builtin + schema + custom), 17 个 gate 定义 (G001 v0.18 标记 orphan_removed, G027 新注册)

## Quality — 质量要求

- **性能**: 单次 Agent 创建 < 10min (含 human approval)
- **安全**:
  - 禁止 SubAgent 读 forbidden_inputs (人审报告 / build-plan / 上游产物)
  - 禁止 Bash 工具 (除 step 0/3 的 env-probe / file_exists)
  - 禁止 rm -rf / git push --force 等破坏性操作
- **可用性**:
  - confidence ≥ 80: 直接路由到 pipeline
  - confidence < 60: 进入需求澄清追问 (agent 线 Step 1 / skill-foundry Step 0, requirement-clarifier + AskUserQuestion)
  - 任何 step FAIL: 自动重试或退到上一步

## 验收

- [ ] Given 用户说 "帮我做一个代码审查 Agent", When 走完 Step 1-5 全流程, Then 产出 Agent readiness 报告分数 ≥ 58 (L2)，由 main agent 人判
- [ ] Given Step 2a pattern-matcher 选错模式, When Step 2b review 发现, Then 退到 Step 1 重新澄清
- [ ] Given Step 5 verification FAIL, When main agent 按 retry 预算重试 1 次, Then 退到 Step 4 重新生成
- [ ] Given Step 5.5 用户选 Skip, When 跳到 Step 7, Then 产物可 `cd && claude` 立即运行
- [ ] Given 用户选 Run (Step 6), When runtime-evaluator score < 3.5, Then 报告 diagnostic + 改进建议
- [ ] Given pipeline_retry_budget = 5 exhausted, When total retry = 5, Then 写 gate-block.md + AskUserQuestion

## 关联文档

- `skills/harness-create/references/workflow.md` — 8 步 agent 创建 pipeline
- `skills/skill-foundry/references/workflow.md` — 8 步 skill-foundry 统一 pipeline (create / optimize / diagnose 三 mode)
- `phase/00-conventions.md` — 路径与目录约定
- `phase/gates/gates.yaml` — 17 个 gate 定义 + 22 个 step trigger（含 G024 落盘检查, P10; G027 v0.18 注册, 脚本随批次 2 落地）
- `phase/human-approval/` — 3 个 DC 文档
- `scripts/main-agent-helpers.sh` — main agent 状态机 (11 个函数)
- `docs/migrations/v0.17-v0.18.md` — v0.17 → v0.18 升级路径
