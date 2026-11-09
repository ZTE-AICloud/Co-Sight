# Drive 技术文档

| 字段 | 值 |
|---|---|
| 项目名 | `drive` |
| 版本 | 2.3.4 |
| 形态 | Claude Code 插件（`plugin.json` + `agents/` + `skills/` + `hooks/`） |
| 运行时 | Claude Code / 兼容 Agent Harness（插件自身不捆绑执行器） |
| License | 见仓库根 `LICENSE` |
| 源码 | https://github.com/ZTE-AICloud/Co-Sight/tree/master/Co-Sight%20Harness/drive |

---

## 1. 一句话定义

Drive 是一套跑在 Claude Code 之上的 **workflow orchestration harness**：用声明式 `workflow.yaml` 描述多阶段流水线，把多 Agent 协作从"灵机一动"工程化成"状态机 + Hook 强制不变量 + 可审计产物"。Claude Code 本身即是运行时，Drive 不引入第二个引擎。

---

## 2. 要解决的问题

直接用 Claude Code 干复杂活，会卡在 4 个具体位置：

- **上下文丢**：十几轮对话下来，前面定的方案、决定的理由早就被覆盖；下一个会话要从零回忆。
- **过程不可见**：哪一步出岔、谁改了什么、回滚到哪一行，没有结构化存档，事后只能"感觉哪一步可能错"。
- **质量看心情**：agent 跑完就算交付，没有硬性门禁；产出是否达标，由"看起来差不多"决定。
- **状态不留盘**：今天被叫停的任务流，明天再开新会话就从零开始；trace 与检查点都在对话上下文里，会话结束就丢。

这 4 个问题不是"AI 不够聪明"，而是 **harness 缺位**：缺一套机制强制 AI 走特定路径、在特定位置停下等人、产出落到固定形态。Drive 把这 4 件事做成 4 类机制：

| 问题 | Drive 的对应机制 |
|---|---|
| 上下文丢 | `.drive/<plan_dir>/` 把每一步落磁盘；跨会话不丢。 |
| 过程不可见 | `run-log.jsonl` 审计日志 + `drive-trace` / `drive-viz` 可观测。 |
| 质量看心情 | `output_schema.artifacts[]` 声明 `path_pattern` / `min_count` / `min_lines`，evaluator 跑完才算交付。 |
| 状态不留盘 | `executeState.json` 状态机 + 文件锁；非对话上下文，下个会话直接 `state_cli.py status` 续跑。 |

---

## 3. 设计方案

### 3.1 核心抽象：4 层职责

Drive 把"AI 工作的舞台"拆成 4 层，每层都有可实例化的对象：

| 层 | 职责 | 实例 |
|---|---|---|
| **Workflow** | 流水线结构 | `workflow.yaml`（阶段 / agents / gates / 条件回流） |
| **State** | 进度与门禁 | `executeState.json` + `state_rules.py` |
| **Agents** | 干活的工人 | `agents/*.md`（analyzer / planner / executor / evaluator / gate-human / code-reviewer / security-reviewer） |
| **Artifacts** | 交付物 | `.drive/<plan_dir>/artifacts/<task_id>/SUMMARY.md` 等 |

**关键原则**：模型不会自己记得"先原型再规划再实现"，Drive 写进状态机它必须执行；模型不会自觉停下来等人审，plan-review gate 写进状态机它必须停。

### 3.2 双编排模式

| 模式 | 形态 | 适用场景 |
|---|---|---|
| **phase**（默认） | 5 阶段顺序流水线：`start → analyze → plan → execute → evaluate`；每阶段一个专属 agent | 需求清晰、阶段边界明确 |
| **dag** | DAG + Wave 拓扑；节点声明 `depends_on`，wave 内并发、wave 间同步 | 任务并行可挖掘、阶段回流 |

模式由 `workflow.yaml` 顶部声明；运行时由 `/drive` 入口动态加载 `references/phase-mode.md` 或 `references/dag-mode.md` 派发协议。

### 3.3 Hook 强制不变量（核心不变量层）

8 个脚本 + 1 个协议，分布在 `PreToolUse` / `SubagentStop` 上：

| Hook | 触发器 | 职责 |
|---|---|---|
| `planning_write_guard.py` | Write/Edit | 计划期外的写盘拒绝 |
| `state_transition_guard.py` | Write/Edit/Bash | 状态机迁移合法性 |
| `subagent_report_guard.py` | SubagentStop | 子 agent 产物落盘前校验 |
| `audit_events.py` | Bash/Task/Agent/Skill | 审计事件落 `run-log.jsonl` |
| `hooks_protocol.py` | 协议层 | 7 个 hook 共享的不变量规则（不变量定义） |
| `hook_io.py` | I/O 层 | 与 Claude Code 通信的 stdin/stdout 协议 |
| `state_rules.py` | 规则层 | 状态机迁移规则定义 |

**关键设计**：所有写盘都先经过 guard，guard 拒绝则工具调用失败 —— **模型不能跳过门禁**。这是 Drive 与"提示词希望它记得"的本质区别。

### 3.4 HITL 的 default-deny

Human-in-the-Loop 不是"模型自觉停一下"，而是状态机层面强制：

- 阶段结束时，状态机写入 `pending_plan_review=true`。
- 唯一放行工具 `confirm_stage` 刻意不在任何 `allowed-tools` 内。
- 执行时 Claude Code 弹权限框，权限框即人工确认。
- 另有 `hooks_protocol.check_confirmation_tampering` 防篡改。

这意味着：**主对话没有免确认授权；想替用户放行会弹权限框；权限框就是 HITL 通道本身。**

### 3.5 声明式编排

想改默认的 5 阶段流水线（增删环节、换 agent、调 gate），在项目根放 `workflow.yaml`，Drive 启动时读它；不放就走内置默认。

最小示例（等价默认）见 `skills/drive/scripts/workflow.yaml`。

### 3.6 Fresh Evidence 原则

evaluator 验收不靠"对话里说完成了"，靠 Fresh Evidence：

- 产物在内存里 = 没出现
- 产物在对话里 = 没了
- **Fresh Evidence = 在磁盘上、按 `output_schema.artifacts[]` 校验**

`path_pattern` / `min_count` / `min_lines` 是 schema 的强约束；evaluator 跑完才算交付。

---

## 4. 价值

### 4.1 给开发者

- **可打断可重来**：每个阶段停下来，不满意 `revise` 回 plan，状态机驱动回滚。
- **可监督**：`.drive/<plan_dir>/` 全部落盘，每步可看可审计。
- **可定制**：改 `workflow.yaml` 即可调整流水线，不等 harness 提供商上新能力。

### 4.2 给团队

- **多 Agent 协作工程化**：wave 调度、依赖图、跨阶段审计日志，harness 该管的单线对话管不了。
- **HITL 落地**：门禁写进状态机，模型跳不过；权限框即人工。

### 4.3 给开源生态

- **适配多个 harness**：声明式 `workflow.yaml` + 标准 hook 协议，理论上可移植到 Claude Code / Codex / 其他兼容 harness。
- **不绑死 LLM**：agents 用 markdown 描述，靠 Claude Code 自身能力跑，可换底层模型。
- **可 fork 可定制**：License / 三阶段——业务价值点可叠加、可裁剪。

---

## 5. 技术架构

### 5.1 仓库结构

```
drive/
├── .claude-plugin/        # plugin.json + marketplace.json（发布元数据）
├── agents/                # 7 个 agent 描述（analyzer/planner/executor/evaluator/...）
├── skills/                # 16 个 skill（drive / state-machine / dag-runtime / ...）
│   └── drive/
│       ├── SKILL.md       # 主入口协议
│       ├── references/    # phase-mode.md / dag-mode.md / review-subflow.md
│       └── scripts/       # read_workflow.py / state_write.py / audit_append.py / ...
├── hooks/                 # 8 个 hook 脚本 + 1 个 hooks.json 配置
├── scripts/               # install.sh / pack.sh（打包 + 安装）
├── tests/                 # pytest 回归（角色独立性 / phase 回归 / 插件契约）
├── docs/                  # 架构图 / 技术文档
└── dist/                  # 已打 tar.gz（pack.sh 产物）
```

### 5.2 关键模块

| 路径 | 行数 | 作用 |
|---|---|---|
| `hooks/hooks_protocol.py` | 678 | 7 个 hook 共享的不变量协议 |
| `hooks/hook_io.py` | 185 | Claude Code ↔ hook 通信协议 |
| `hooks/state_transition_guard.py` | 112 | 状态机迁移合法性 |
| `hooks/subagent_report_guard.py` | 130 | 子 agent 产物落盘校验 |
| `hooks/state_rules.py` | 100 | 状态机迁移规则 |
| `hooks/audit_events.py` | 114 | 审计事件 |
| `skills/drive/scripts/read_workflow.py` | — | workflow.yaml 解析 + 校验 |
| `skills/drive/scripts/state_write.py` | — | 状态机写盘（带文件锁） |
| `skills/drive/scripts/dag_flow.py` | — | DAG 模式派发 |
| `skills/drive/scripts/workflow.yaml` | — | 内置默认 workflow |

### 5.3 状态机

`executeState.json` 字段（核心）：

- `plan_name` / `plan_dir`：plan 唯一身份（`envelope.data` 是唯一来源）。
- `active_stage`：当前阶段（phase 模式）或当前 wave（dag 模式）。
- `confirmed_stages` / `confirmed_nodes`：已确认阶段/节点 id 列表。
- `pending_plan_review`：是否停在 plan-review 等待用户。
- `verdict`：evaluator 评审判定（pass / fail / partial）。

**写入强制**：

- 两个字段（`confirmed_stages` / `confirmed_nodes`）均经 `update --set` 在 CLI 层禁写。
- `confirm_stage.py` 是唯一写入口，刻意不在 `allowed-tools` 内。

### 5.4 DAG 模式 4 个核心机制

1. **Wave 调度**：节点声明 `depends_on` → 计算拓扑 → 同消息多次 `Agent()` 并发 → wave barrier 收齐。
2. **节点状态**：dag-runtime skill 持有 `active_agents[]` 与 `current_wave`；每节点标 `completed` / `failed` / `skipped`。
3. **HITL 门控**：wave barrier 后停 → 用户放行才进下一 wave。
4. **重试与降级**：节点 `failed` 可 `record` 重试 attempt，verdict 保留更新。

### 5.5 测试覆盖

| 测试套 | 覆盖目标 |
|---|---|
| `tests/test_plugin_contract.py` | plugin.json / hooks.json 契约 |
| `tests/test_role_independence.py` | 7 个 agent 角色独立性 |
| `tests/test_phase_mode_builtin_regression.py` | phase 模式默认 workflow 回归 |
| `tests/e2e/` | 端到端流程 |
| `tests/agents/` / `tests/skills/` / `tests/hooks/` | 子模块单测 |

---

## 6. 技术标签

按 plugin.json `keywords` + 实际覆盖：

- `claude-code` —— Claude Code 插件形态
- `plugin` —— 插件发布包（plugin.json + marketplace.json）
- `workflow` —— 工作流编排
- `harness` —— AI 工作的舞台层工程化
- `hitl` —— Human-in-the-Loop（default-deny）
- `spec-driven` —— workflow.yaml 声明式规格驱动
- `multi-agent` —— 多 agent 协同
- `state-machine` —— 状态机自动机
- `wave-fanout` —— DAG Wave 并发派发
- `declarative-orchestration` —— 声明式编排
- `baseline-versioning` —— baseline 版本管理（plan / artifact）
- `skill-first` —— skill 优先（agents 通过 skill 调度）
- `dag` —— DAG 拓扑

辅助技术维度：
- **AI Engineering**：harness / spec-driven / multi-agent orchestration
- **Developer Tooling**：Claude Code plugin / IDE-adjacent runtime
- **YAML DSL**：`workflow.yaml` 即编排器

---

## 7. 适用与不适用

| 场景 | 是否适合用 Drive |
|---|---|
| 需求清晰、阶段边界明确的多步骤任务 | ✅ 适合（phase 模式） |
| 任务并行可挖掘、有依赖图 | ✅ 适合（dag 模式） |
| 单轮问答 / 闲聊 | ❌ 不适合（杀鸡用牛刀） |
| 不允许写盘的环境 | ❌ 不适合（依赖 `.drive/<plan_dir>/` 落盘） |
| 团队协作多 reviewer | ✅ 适合（review-subflow 天然支持） |

---

## 8. 安装与运行

```bash
# 用户态安装（默认 scope=user）
./scripts/install.sh

# 从制品安装（分发主路径）
./scripts/install.sh --from dist/drive-v2.3.4-*.tar.gz

# 开发态（marketplace 直指源码，改完即时生效）
./scripts/install.sh --dev

# 打包
./scripts/pack.sh    # 产物在 dist/
```

安装后需重启 Claude Code 会话，命令才会出现在面板里。

---

## 9. 与 Cosight-Harness 的关系

Drive 是 Cosight-Harness 的 **workflow orchestration engine**，把"分析需求 → 拆任务 → 多 Agent 协同 → 评审 → 产出"这条流水线变成可声明、可审计、可回放的制品。其核心定位是 **把"多 Agent 协作"从"灵机一动"变成"工程化流水线"**。

业务价值点：
- 多 Agent 协作的标准化与可复用
- 跨会话可监督、可中断、可重来的工作流
- 评审与门禁的硬性化（不只是"AI 自己觉得完成了"）

---

## 10. 风险与限制

- **依赖 Claude Code 兼容 harness**：hook 协议用 `${CLAUDE_PLUGIN_ROOT}` 环境变量，需 harness 提供。
- **状态机文件锁是同机锁**：跨机并发不覆盖（设计上为单会话独占）。
- **HITL 阻塞成本**：每阶段停下等人，在长链路上是慢动作；快路径可用 `auto_mode=true` 跳过 plan-review gate（其余 gate 仍生效）。

---

## 11. 许可与版权

开源协议以仓库根 `LICENSE` 文件为准。引用 Drive 的项目请保留版本与作者署名。

---

## 12. 贡献方向

- 新增 workflow 模板（`workflow-builder` skill 即可介入）
- 新增 skill（按 `SKILL.md` 协议编写）
- 新增 agent 角色（`agents/*.md` 描述 + 注册到 plugin.json）
- 新增 hook（写守卫脚本 + 注册到 `hooks/hooks.json`）

提交前请跑 `tests/` 全套，验证 plugin 契约与角色独立性不退化。