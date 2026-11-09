# drive

> Claude Code 上的多 Agent 工作流编排插件 —— **声明式 workflow + 状态机自动机 + Hook 强制不变量**，把 Claude Code 自己当作运行时跑出 production-grade 的多阶段协作。

| 字段 | 值 |
|---|---|
| Plugin name | `drive` |
| Version | `2.3.4` |
| Display name | Drive |
| Author | drive contributors |
| 编排模式 | `phase`（顺序阶段）/ `dag`（DAG + Wave 拓扑） |
| Runtime | 适配 Claude Code 等 Agent harness；插件本身不绑定运行时，harness 既是执行器也是 UI |
| License | 待定（开源协议以仓库根 `LICENSE` 为准） |

## 它解决什么问题

直接用 Claude Code 干复杂活，4 处会卡：

- **上下文丢** —— 十几轮对话下来要复述前面决定了什么。
- **过程不可见** —— 中间哪步出岔只能事后发现，没结构化存档。
- **质量看心情** —— agent 跑完就算交付，缺硬性门禁。
- **状态不留盘** —— 明天回来从零开始。

Drive 是套在 Claude Code 上的 **harness**，把这 4 处都解掉：

- **结构** —— 5 阶段流水线（start → analyze → plan → execute → evaluate），每阶段专属 agent 干活。
- **存盘** —— `.drive/<plan_dir>/` 把每一步落磁盘，跨会话不丢。
- **门禁** —— `gate` 由 hook 强制执行，模型跳不过去，不是"希望它记得"。
- **可调** —— 流程不满意？改 `workflow.yaml`，校验过就用。

你说"用 drive 做 X"，它派调研员摸清意图、规划员拆任务、工头分派人手、质检员把关，关键决策点停下来等你拍板。每一步可监督、可打断、可重来。

### Drive 把 harness 哲学工程化

harness 不是"AI 工具"，是"AI 工作的舞台"——它决定 AI 在什么约束下、用什么工具、产出什么、走什么流程、卡在哪。**drive 把 harness 哲学工程化**：

- **不靠对话自觉，靠状态机强制** —— 模型不会自己记得"先原型再规划再实现"，drive 写进 `executeState.json` 它必须走；模型不会自觉停下来等人审，plan-review gate 写进状态机它必须停。
- **不靠人肉判断，靠 schema 校验** —— 完成度不是"看起来差不多"，是 `output_schema.artifacts[]` 声明的 `path_pattern` / `min_count` / `min_lines`，evaluator 跑完才算交付。
- **不靠产品方上新功能，靠改 yaml** —— 你不用等 harness 提供商出新能力。增删环节、换 agent、调 gate，写 `workflow.yaml`，校验过就用。
- **不靠单线对话，靠多 agent 编排** —— wave 调度、依赖图、跨阶段审计日志，都是 harness 该管但单线对话管不了的事。

---

## 第一次使用

在 Claude Code 里说"用 drive 做 X"或直接 `/drive`。5 阶段流水线依次跑：

0. **init（初始化）** —— 建 `.drive/<plan_dir>/` 骨架，写 `intent.md`。
1. **analyze** —— 调研员摸清你的真实意图，澄清需求，产出 `manifest.md`。
2. **plan** —— 规划员拆任务、分 wave、放行。
3. **execute** —— 工头按 wave 派工人（wave 内并发、wave 间同步）；代码类任务在 wave 收口前再过一遍 code review 与安全审查。
4. **evaluate** —— 质检员跑 L0/L1/L2 质检，通过才算交付，失败回 plan 重做。

**每个阶段结束都停下来等你点头**，不只是 plan。你没放行，状态机不往下走 —— `confirm_stage.py` 是唯一的放行通道，主对话没有它的免确认授权，替你放行会弹权限框。想一路跑完不打断，start 时开 `auto_mode`。

`.drive/<plan_dir>/` 产物：

```text
.drive/<plan_dir>/
├── executeState.json     # 运行时状态（带锁，并发写不互踩）
├── intent.md             # 你的意图
├── manifest.md           # analyze 输出
├── taskRecord.yaml       # plan 输出
├── waves.yaml            # 调度计划（会计算的波次与预算）
├── artifacts/            # 任务产物
│   └── <task_id>/
│       ├── SUMMARY.md    # 工人自述
│       └── REVIEW.md     # 审查报告（代码类任务才有）
├── evaluation/           # 质检报告
└── run-log.jsonl         # 审计日志
```

---

## 自定义编排

想改默认的 5 阶段编排（增删环节、换 agent、调 gate），在项目根放 `workflow.yaml`（或 `.yml`），drive 启动时读它；不放就走内置默认。

最小示例（等价于默认）：

```yaml
phases:
  - stage: analyze
    agent: drive:analyzer
  - stage: plan
    agent: drive:planner
  - stage: execute
    agent: drive:executor
  - stage: evaluate
    agent: drive:evaluator
    terminal_stage: true
```

## DAG 模式（drive-2.3+）

drive-2.3 新增 `mode: dag` —— 以 agent 为节点、`depends_on` 为边的 DAG 表达。DAG 是 phase 的**严格超集**：任何 phase 流程（链状 / 树状 / 网状 / 有回跳）都能用 DAG 表达，反之不行。

**适用场景**：

- 用户自定义 agent 比内置 6 个更合适（专业领域 agent）。
- 想表达复杂的偏序关系（"先 X 后 Y 同时 Z"）。
- 想做节点级 HITL gate（不是 phase 模式 plan-review 那种内置）。

最小示例：

```yaml
mode: dag

orchestration:
  max_concurrent_agents: 4
  wave_dispatch: barrier

agents:
  - id: planner
    agent: AuthPlanner       # 用户自定义 agent
    depends_on: []
  - id: impl-auth
    agent: AuthImplementer
    depends_on: [planner]
  - id: impl-api
    agent: ApiImplementer
    depends_on: [planner]
  - id: reviewer
    agent: drive:code-reviewer  # 混合内置 agent
    depends_on: [impl-auth, impl-api]
  - id: gate-human
    agent: drive:gate-human     # DAG 节点级 HITL gate
    depends_on: [reviewer]
    gate:
      type: human_review
      options: [approve, revise]
  - id: evaluator
    agent: drive:evaluator
    depends_on: [gate-human]
    terminal: true
    verdict_required: true

complexity_rules:
  trivial:
    skip_agents: [reviewer]
```

### 4 种 agent 地址形式

- `drive:xxx` —— drive 内置 agent（如 `drive:evaluator`）。
- 裸名 `xxx` —— 项目本地 agent（在 `.claude/agents/<name>.md` 定义）。
- `@xxx` —— Claude Code Agent tool 子 agent（如 `@Explore`、`@Plan`）。
- `plugin:xxx` —— plugin 提供的 agent。

### phase vs DAG 对照

| 维度 | phase 模式 | DAG 模式 |
|------|----------|---------|
| 调度源 | 内置 5-stage | 用户自定义 `workflow.yaml` |
| agents | 固定 6 个内置 | 用户 + 内置可混用 |
| 并发 | stage 内 wave_barrier 隐式 | `depends_on` 显式 DAG 拓扑 |
| HITL gate | plan 阶段内部微步骤 | DAG 节点 `drive:gate-human` |
| 复杂度策略 | `skip_phases` | `skip_agents` |

### DAG 模式 4 个核心机制

1. **Wave 并发** —— `wave-scheduling topo-sort` + `schedule-waves` 把 DAG 拆成可并行的波次，每波内用同一消息多次 `Agent(...)` 调用并发 spawn（drive 全局策略 `run_in_background=False`）。
2. **Wave Barrier 强对账** —— `wave-barrier aggregate` 强制对账 worker summary 的 task_id 集合 vs `waves.yaml[wave_n].tasks`，缺 / 多 / 重复就拒写 state。
3. **双重 HITL 闸门** —— 先 `confirm_node.py`（**不在任何 allowed-tools 内**，靠权限弹窗写 `confirmed_nodes[]`）→ 再 `mark-completed`（harness `check_dag_node_confirmation` + CLI `cmd_mark_status` 双重校验）。
4. **3-Retry 上限** —— `dag-runtime mark-retry-attempted` 累加 `retry_count`，`--max-retries` 默认 3，超过返回 `RETRY_BUDGET_EXCEEDED` 走 escalate 或 `mark-failed` + cascade。

---

## 目录结构

```text
drive/
├── .claude-plugin/
│   ├── plugin.json            # 插件 manifest：name/version/agents 列表
│   └── marketplace.json         # 内部 marketplace（zte-ai-lab）
│
├── agents/                    # 7 个 subagent 定义
│   ├── analyzer.md            # input-readiness researcher → manifest.md
│   ├── planner.md             # task 拆分 + 分派到已有 agent
│   ├── executor.md            # 单 task worker（code / analysis 双模式）
│   ├── evaluator.md           # L0/L1/L2 三层质检 + verdict
│   ├── gate-human.md          # HITL 闸门节点（不调 LLM，等用户决策）
│   ├── code-reviewer.md       # severity-based 代码审查（防 prompt injection）
│   └── security-reviewer.md   # OWASP Top 10 + 密钥 / 注入 / 访问控制
│
├── skills/                    # 17 个支撑 skill（4 个 user-invocable + 13 个 internal）
│   ├── drive/                 # 总入口 orchestrator（user-invocable）
│   ├── startup/               # plan_name 解析 + 初始化 .drive/ 骨架
│   ├── state-machine/         # .drive/<plan_dir>/executeState.json 读写
│   ├── dag-runtime/           # DAG 模式 active_agents[] + HITL 确认
│   ├── wave-scheduling/       # 拓扑排序 + budget 分配
│   ├── wave-barrier/          # wave 收尾强对账（task_id 集合 + fs diff）
│   ├── execution-patterns/    # 4 个执行模式：wave / whitelist / retry / checkpoint
│   ├── workflow-builder/      # 把自然语言翻译成 workflow.yaml（grill-me 风格）
│   ├── smart-decomposition/   # SMART 拆任务 5 原则
│   ├── critic-3-perspectives/ # plan 写完后的三视角 self-check
│   ├── context-packaging/     # per-task context snapshot（worker 冷启动优化）
│   ├── eval-fresh-evidence/   # L0/L1/L2 评测 + 5-axis rubric
│   ├── drive-trace/           # 实时 HTTP trace server（浏览器观测）
│   ├── drive-viz/              # 共享 CSS design tokens（light/dark）
│   ├── drive-record/          # 复盘 REPORT.md / HTML 回放
│   ├── drive-cleanup/         # 清理过期 plan-* 目录
│   └── bootstrap-data-completer/  # 部分输入的补全诊断
│
├── hooks/                     # 8 个防护层 Python 脚本
│   ├── hooks.json             # Claude Code 钩子配置（PreToolUse / SubagentStop）
│   ├── hooks_protocol.py      # 钩子调用约定 + 核心决策逻辑（single source of truth）
│   ├── planning_write_guard.py    # .drive/ 写入白名单 default-deny
│   ├── state_transition_guard.py  # 状态机合法迁移校验
│   ├── subagent_report_guard.py   # SubagentStop 报告校验
│   ├── audit_events.py            # audit 事件追加
│   ├── hook_io.py                 # 钩子 IO 协议（stdin JSON → exit 0/2）
│   └── state_rules.py             # VALID_TRANSITIONS / STAGES 权威定义
│
└── tests/                     # pytest 测试套件
    ├── agents/                # subagent 行为测试
    ├── skills/                # 各 skill 行为测试
    ├── hooks/                 # 钩子防护层测试（最重要）
    ├── scripts/               # 脚本测试
    ├── roles/                 # 单角色独立测试
    ├── e2e/                   # 端到端 workflow 跑测
    ├── test_plugin_contract.py          # 插件契约测试
    ├── test_phase_mode_builtin_regression.py
    └── test_role_independence.py
```

---

## 工作原理

### 核心心智模型：drive = 把 AI 当员工管的引擎

harness 视角下，AI 不是"工具"是"员工" —— 它有岗位、有上下级、有流程制度、有 OKR、有评审。drive 把这整套**组织管理学**搬进 AI 工作流：

| 组织概念 | drive 对应 |
|---|---|
| 组织架构图 | workflow（编排层）|
| 流程制度 | drive 核心（推进、HITL、状态留档）|
| 员工 | agents，各就各位只干自己岗位的活 |
| 个人技能 | skills，员工按需调用 |

判断"这个能力 / 决策放哪层"只需问：**这在公司里是谁的活？** 公司隐喻不是修辞 —— drive 的 5 阶段流水线、组织架构、岗位契约、雇佣关系都按"一家公司怎么干活"组织。

### 岗位的契约

四个阶段主力 + 两个只读审查者 + 一个 HITL 中介：

| 岗位 | 管什么 | 不管什么 |
|---|---|---|
| **analyzer 调研员** | 摸清你的真实意图，把模糊需求变成说得清的输入 | 不规划（不拆 task）|
| **planner 规划员** | 拆 task + 分派到岗 + 放行（校验合法性）| 不调研、不设岗（用已有 agent）|
| **executor 工头** | 按 task 声明孵化 subagent、管 wave 并行时序 | 不选人（agent 已分派）|
| **evaluator 质检员** | 检查产出质量，不合格打回 | 不执行（只质检）|
| **code-reviewer 审查者** | 代码质量，按 CRITICAL / HIGH / MEDIUM / LOW 分级报问题 | 不改代码、不写状态 |
| **security-reviewer 审查者** | OWASP Top 10、硬编码密钥、注入面、越权、弱加密 | 不改代码、不写状态 |

**质检员 vs 审查者的区别**：质检员查"验收标准有没有达成"，审查者查"达成的方式有没有埋雷" —— 验收标准全过的代码里照样可以有硬编码密钥或 SQL 注入。CRITICAL 会让任务重做，两次仍修不掉就停下问你。

### 雇佣关系

岗位之间可以**雇佣**：agent 履职时若能力不足（干不了 / 干不全 / 缺工具），可以临时雇其他 agent 补足缺口（如 planner 调 `topo_sort.py` CLI 算波次）。被雇者向雇主交代，雇主对 workflow 负责。**雇佣是运行时行为，不改组织架构图**。

### 四层职责

```text
① 用户入口          4 个公开入口（/drive 等）
                          ↓
② 编排层            workflow.yaml（声明）+ main agent（解释执行）
                    phase 顺序 / 每 phase 派谁、雇谁、卡在哪
                          ↓ 编排
③ Agent 层          7 个岗位（4 个阶段主力 + 2 个只读审查者 + gate-human HITL 中介）
                          ↓ 使用
④ Skill 层          员工技能（knowledge + capability）

   制度底座          hooks/ —— 不变量强制器（LLM 跳不过的检查点）
```

两条硬约束：

- **编排定结构，履职可雇人。** workflow.yaml 决定有哪些岗位、大流程怎么走；agent 不能改组织结构，但履职时能雇人补能力缺口。
- **策略是数据，不是代码。** gate、复杂度分支、执行模式全在 `workflow.yaml` 里，可校验、可 diff、可被用户覆盖。

---

## Hook 防护层（8 个脚本 + 1 个协议）

钩子是 drive 与 Claude Code runtime 之间的"宪法实施"层。

| Hook 脚本 | 触发时机 | 决策 |
|---|---|---|
| `planning_write_guard.py` | PreToolUse on Write/Edit/MultiEdit | `.drive/<plan_dir>/` 写入白名单 default-deny，状态文件 (executeState.json / run-log.jsonl) 强制走 CLI |
| `state_transition_guard.py` | PreToolUse on Write/Edit/Bash | 状态机合法迁移表 + 跨阶段产物污染拦截 |
| `audit_events.py` | PreToolUse on Bash/Task/Agent/Skill | 事件追加到 `run-log.jsonl` |
| `subagent_report_guard.py` | SubagentStop | 校验 subagent 报告格式 |
| `hook_io.py` | （基础设施） | stdin JSON → exit 0/2 协议 |
| `state_rules.py` | （基础设施） | VALID_TRANSITIONS / STAGES / VERDICT_REQUIRED_TARGETS 权威定义 |
| `hooks_protocol.py` | （基础设施） | `invoke_hook(hook_name, tool_name, tool_input)` 编程接口 |
| `hooks.json` | （配置） | 钩子注册表 |

设计要点：**决策规则单一真相源**。所有 hook 脚本共享 `hooks_protocol.py` 的 `HookResult`，避免规则在 hook 脚本与测试之间漂移。

---

## 质量门（Evaluator）

drive 把"是否合格"分成 **3 层** 评测 + **5 维**评分：

### 3 层评测

| 层 | 评估对象 | 方法 | 置信度 |
|---|---------|--------|---|
| L0 | 文件存在 + 格式 valid | 确定性 shell（ls/find/wc/stat）| 100% |
| L1 | Lint / 格式 / 类型 | markdownlint / eslint / tsc / ruff | 100% |
| L2 | AC 语义 | LLM Judge + 5-axis rubric | 0-100% |

最终 verdict = L0 AND L1 AND L2 综合判断（**PASS / FAIL / INCOMPLETE**）。

### Fresh Evidence 原则

> "It should work" is not verification.

- 5 分必须 cite 具体证据（`file:line` / grep 输出 / 测试结果）。
- 1–4 分必须同时给 "❌ 哪里缺" 和 "✅ 怎么补"。
- 禁止措辞：should work / probably / seems to / 应该 / 可能 / 看起来。
- 禁止只看 task description 推断产物是否达成。

---

## HITL 的"default-deny"哲学

drive 的所有"人审"都在 harness 层强制，不在代码里写 if/else：

1. **阶段间 HITL**（phase 模式）—— 每个 stage 的 `gate.type == human_review`，触发 `gate-human` agent → 主对话用 `AskUserQuestion` 真问用户 → 用户决策后由 `state-machine` skill 写 `executeState.json` 的 stage 流转。
2. **DAG 节点 HITL**（dag 模式）—— 每个 `agent: drive:gate-human` 节点对应一次 confirm → `confirm_node.py` 不在任何 allowed-tools 内，执行时由 Claude Code 弹授权请求 → 权限弹窗即人工确认 → 写 `confirmed_nodes[]` → 再 `mark-completed`（双重闸门）。
3. **plan-review gate** —— `pending_plan_review=true` 时必须停下 → 走 HITL → 用户回 `proceed` / `revise` 后再 `transition`。

**为什么这样设计**：把"信任"和"决策"分离 —— 代码不信任自己对人审的判断，由 harness 强制不可绕过。

`auto_mode=true` 时所有闸门跳过（用户明确说"auto"才开）。`complexity == trivial` 时 `plan` 闸门也跳过。

---

## 状态与可观测

### 持久化状态

```text
.drive/
└── plan-<UTC-YYYYMMDD-HHMM>-<name>/    # 每个 PR 一个 plan 目录
    ├── manifest.md                       # analyzer 输出
    ├── taskRecord.yaml                  # planner 输出（tasks 列表）
    ├── waves.yaml                       # wave-scheduling 输出（拓扑 + 并行度）
    ├── topo-state.json                  # 拓扑排序中间状态
    ├── executeState.json               # 运行时状态（fcntl 锁 + monotonic revision）
    ├── run-log.jsonl                   # 所有 hook 事件追加
    ├── verification-report.md          # evaluator 写
    ├── REPORT.md                       # drive-record 拼装的复盘文档
    ├── context_pack/<task_id>.json    # per-task 上下文快照（性能优化）
    └── inputs/                        # 用户输入（白名单放行）
        ├── proposal.md
        ├── workflow.yaml
        └── ...
```

### 三层可观测

1. **drive-trace** —— 启动时 spawn HTTP server（默认 127.0.0.1:8080），每次 GET 重新渲染 HTML，浏览器 meta refresh 2 秒一拉，实时看 stage / wave / status bar / elapsed。
2. **drive-viz** —— 共享 CSS design tokens（light + dark），其他 skill 引用这个出 stage / status 配色。
3. **drive-record** —— `/drive-record <plan_dir>` 拼多源回放：`executeState.json` + `run-log.jsonl` + workflow.yaml + chat session JSON，生成 REPORT.md 和可浏览器播放的 HTML。

---

## 命令

| 命令 | 干什么 |
|---|---|
| `/drive` | 入口，触发 5 阶段流水线 |
| `/bootstrap-data-completer` | 手上只有半套输入时，诊断缺什么、补齐字段 |
| `/workflow-builder` | 用自然语言生成 / 改 `workflow.yaml` 编排 |
| `/drive-record` | 复盘一次 `/drive` 执行 —— 生成 `REPORT.md` + `record_gaps.json` |

内部 user-invocable=false 的 13 个 skill（`startup` / `state-machine` / `dag-runtime` / `wave-scheduling` / `wave-barrier` / `execution-patterns` / `smart-decomposition` / `critic-3-perspectives` / `context-packaging` / `eval-fresh-evidence` / `drive-trace` / `drive-viz` / `drive-cleanup`）由 orchestrator 内部调用，**不直接 user-invocable**。

---

## 4 个执行模式（execution-patterns）

| 模式 | 含义 |
|---|---|
| **Wave 并发** | 拓扑排序后的并行 wave；`waves: []` 必须显式存在 |
| **Whitelist 保护** | 写 `.drive/<plan_dir>/` 默认拒绝，命中白名单才放行 |
| **3-Retry 上限** | fail fast，retry budget 默认 3 |
| **Continue-Here 触发** | 每 Wave 完成后写恢复点（resumption 用） |

---

## 任务拆分规范（SMART）

`smart-decomposition` skill 强制每个 task 同时满足 SMART 5 属性：

| 属性 | 检查方法 |
|---|---|
| **S**pecific | 读完 task name + steps 能动手 |
| **M**easurable | AC 至少 1 个 PASS/FAIL 判定 |
| **A**chievable | 估算时间 < 单 session 长度 |
| **R**elevant | 至少 1 个 user story 引用 |
| **T**ime-bound | estimated_duration 字段 |

违反 SMART 的任务必须重新拆分。

## Plan 质量三视角（critic-3-perspectives）

在 plan 写完但进入 execute 前强制由 planner 自我审视：

- **executor 视角** —— 字段齐全 / 步骤清晰 / AC 可验证 / 依赖明确 / 工具可达 / 类别匹配。
- **stakeholder 视角** —— 范围覆盖 user story / AC 覆盖 / 风险缓解 / out-of-scope 不涉及 / NFR 有对应 / Milestone 有 gate。
- **skeptic 视角** —— 失败点 ≥ 3 + mitigation / 资源风险 / 集成风险 / 外部依赖 / 边界 case。

3 视角任一 CRITICAL → 触发 HITL gate，由人决定 proceed / revise。

---

## 测试覆盖

```text
tests/
├── agents/              4 个文件 — subagent 行为
├── skills/              14 个子目录 — 各 skill 行为
├── hooks/               8 个文件 — 钩子防护层（最重要）
├── scripts/             2 个文件 — 启动脚本
├── roles/               8 个文件 — 单角色独立性
├── e2e/                 2 个文件 — 端到端 workflow
├── test_plugin_contract.py            # 插件契约
├── test_phase_mode_builtin_regression.py
└── test_role_independence.py
```

---

## 故障排查

**卡在等确认**

- 每个阶段结束都要你点头，这是设计而非故障。
- plan 阶段回 `proceed` / `revise`（`revise` 让规划员重拆），其余阶段说一句放行即可。
- 不想每阶段都停：start 时开 `auto_mode`。

**状态转换失败**

- 错误消息带 `reason` code，drive 拒绝非法流转（如 start → execute 会被拦下）。
- 进 `completed` 前要求质检 verdict 是 `pass`，没有就被挡下。

**审查报了 CRITICAL 一直修不掉**

- 看 `.drive/<plan_dir>/artifacts/<task_id>/REVIEW.md` 的问题清单与重做记录。
- 重做两次仍在就会停下问你：接受现状 / 判定未完成回去重规划 / 你自己动手修。

**Agent 执行失败**

- 看 `.drive/<plan_dir>/run-log.jsonl` 的 spawn 记录。
- 确认 `agents/*.md` 定义存在。

**workflow.yaml 不被采用**

- 确认文件在项目根，名字是 `workflow.yaml` 或 `.yml`。

---

## 关键词

`claude-code` · `plugin` · `workflow` · `harness` · `hitl` · `spec-driven` · `multi-agent` · `state-machine` · `wave-fanout` · `declarative-orchestration` · `baseline-versioning` · `skill-first` · `dag`

---

## 与 Cosight-Harness 的关系

drive 是 Cosight-Harness 的 **workflow orchestration engine** —— 把"分析需求 → 拆任务 → 多 Agent 协同 → 评审 → 产出"这条流水线变成可声明、可审计、可回放的制品。它的核心价值是：**把"多 Agent 协作"从"灵机一动"变成"工程化流水线"**。

业务价值点：

- **可审计**：所有 stage 流转有 hook 留痕 + `run-log.jsonl` 事件流 + `REPORT.md` 回放。
- **可回滚**：每个 PR 一个 `plan-*` 目录，跑挂 resumption 即可。
- **可扩展**：新场景写 `workflow.yaml` + 引用已有 agent，不必改插件代码。
- **可观测**：drive-trace 实时浏览器观测 + drive-record 事后复盘。
- **HITL 不可绕过**：人审决策走 harness 权限弹窗，不在代码里偷懒。
- **质量有底**：3 层评测 + 5 维 rubric + fresh evidence。