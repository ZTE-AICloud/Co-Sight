# AgentGenesis 路径与目录约定 (v0.17.5)

> 简化方案: 所有产物**直接写** `output/agents/{name}/v1/` 或 `output/skills/{name}/v1/`，无中间 cp 步骤。
> 适用: 8 步 agent-creation, 8 步 skill-foundry（create/optimize/diagnose）pipeline。
> **基准目录 = 用户 cwd**（`$PWD`）：用户调用 pipeline 时所在的项目目录。
> 插件安装目录（`~/.claude/plugins/cache/...`，仓库内即 `${PLUGIN_ROOT}`）是只读缓存，产物/过程文件一律不写那里。

## 目录结构

```
{用户项目目录 ($PWD)}/          # ← 基准目录，用户调用 pipeline 时所在位置
├── output/                    # 最终产物 (★ 直接写, 不 cp)
│   ├── agents/{name}/v1/      # agent-creation 最终产物（纯运行时面）
│   │   ├── CLAUDE.md
│   │   └── .claude/skills/, .claude/rules/
│   │
│   └── skills/{name}/v1/       # skill-creation / skill-optimization 最终产物
│       ├── SKILL.md
│       ├── references/, scripts/, templates/
│
└── .agent-genesis/work/{name}/   # 过程产物 (过程产物, 不发布)
    ├── agent-creation/        # agent pipeline 的过程产物
    │   ├── clarified-agent-requirements.yaml
    │   ├── phase1-matching-decision.md
    │   ├── phase2-review.md
    │   ├── matched-assets.yaml / adapted-assets.yaml
    │   ├── human-review.md
    │   ├── build-plan.md       # Step 4 消费
    │   ├── phase4-execution-report.md
    │   ├── phase4-verification-report.md
    │   ├── phase5-runtime-eval.md
    │   ├── e2e/                # Step 6a 测试用例
    │   └── e2e-results/        # Step 6b 测试结果
    │
    ├── create-skill/           # skill-creation pipeline 过程产物
    │   ├── phase1-skill-design.md / phase2-review.md
    │   ├── plan-approval-decision.md
    │   ├── phase4-verification-report.md
    │   ├── phase5-runtime-eval.md
    │   ├── e2e/ + e2e-results/
    │
    └── optimize-skill/         # skill-optimization pipeline 过程产物
        ├── phase1-diagnosis-report.md / phase2-review.md
        ├── plan-approval-decision.md
        ├── delta-diff.md
        ├── phase4-verification-report.md
        ├── phase5-runtime-eval.md
        ├── e2e/ + e2e-results/

${PLUGIN_ROOT}/                # 插件安装目录（只读，禁止写入）
├── phase/                     # workflow 步骤定义 (agent 创建指南)
├── .claude/                   # Claude Code 原生: skills / rules / agents
├── schemas/                   # 15 个 schema (产出结构验证)
├── knowledge/                 # 设计模式知识库 (级联匹配 + 23 模式)
├── scripts/                   # 工具脚本 + 10 个 gate 脚本 (scripts/gates/)
└── templates/                 # 1 个模板 (orchestrator-state)
```

## 路径变量

| 变量 | 值 | 说明 |
|------|-----|------|
| `{name}` | 用户输入或时间戳 | Pipeline 运行的唯一标识 |
| `${ROOT}` | `$PWD` | **基准目录** = 用户调用 pipeline 时所在项目目录；output/ 与 .agent-genesis/work/ 均相对它解析 |
| `${WORK_DIR}` | `${ROOT}/.agent-genesis/work/{name}/` | 过程产物根目录 |
| `${OUTPUT_DIR}` | `${ROOT}/output/agents/{name}/v1/` (agent) 或 `${ROOT}/output/skills/{name}/v1/` (skill) | 最终产物根目录 |
| `${PLUGIN_ROOT}` | AgentGenesis 安装路径 | **只读**：读 knowledge/契约/模板；禁止写入任何产物 |

## 产物分类

| 类别 | 路径前缀 | 持久性 | 谁写 |
|------|---------|:---:|------|
| **最终产物** | `${ROOT}/output/{agents,skills}/{name}/v1/` | 永久 | Step 1 / 3 / 4 SubAgent |
| **过程产物** | `${ROOT}/.agent-genesis/work/{name}/` | 临时 (30 天) | 多个 step |
| **fast 车道过程产物** | `${ROOT}/.agent-genesis/work/{name}/fast-lane/`（{name} 层, 与 agent-creation//skill-foundry/ 平级） | 临时 (30 天) | fast 驱动节 / fast builder。契约件: `lane-decision.yaml`（判定节留痕: 判据评估结果 + 模式锚定 + 用户裁定）、`build-plan.md`（FA 极简 build-plan, schema 全字段）、`revision-request.json`（G028 failures[] 机读修复指令）、`self-report.md`（fast-lane-report.schema）、`snapshot/`（optimize 就地修订前快照）。来源: fast-lane-implementation.md §4.0 |
| **gate 证据** | `${ROOT}/.agent-genesis/work/{name}/gate-results/{step_id}.json` | 临时 | main agent（跑完 gate 即落盘, 无自动引擎） |
| **状态文件** | `${ROOT}/.agent-genesis/work/{name}/orchestrator-state.yaml` | 临时 | main agent (每 step 后) |

## output/ vs work/ 决策

- **output/**: 是最终交付物, 用户拿走用。`cd $PWD/output/agents/my-agent/v1 && claude` 就能跑
- **work/**: 是审计 + 重试用, 不发布
- **决定路径**: SubAgent 的 `prompt 参数` `--output-dir` 决定, main agent 显式传（传 `$PWD` 解析后的绝对路径，防 cd 漂移；双根约定同 `scripts/gates/g024-output-exists.sh`：脚本相对定位解析 gates.yaml=插件根，root 参数解析产物=用户 cwd）

## 插件根写保护

- SubAgent 收到 `${PLUGIN_ROOT}` 内的输出路径时**必须立即报错**，不得自行改路径（`agents/build-planner.md` 硬规则）
- 插件根写保护由 `hooks/guard-self-modify.py` 承担；产物 manifest 的 `..` 穿越与声明未生产由 G023 cross 拒绝
- Main Agent 调 G024（`scripts/gates/g024-output-exists.sh`）时，stdin JSON 的 `root` 必须显式传 `$PWD`（P10 后承接原 validate-contract --node 落盘校验）

## orchestrator-state.yaml 状态机

每 step 后 main agent 写:
- `steps[]`: 已完成 step 列表
- `current_step`: 当前 step_id
- `pipeline_status`: IN_PROGRESS | COMPLETED | BLOCKED | FAILED
- `total_retry_count`: 整 pipeline retry 累计
- `pipeline_retry_budget`: 5 (超限 escalate)

**verdict 落盘责任**: gate-results/{step_id}.json 由 SKILL.md 主循环在跑完 gate 后立即写入
（不存在 gate-engine 组件）；main-agent-helpers `finish_step` 的等待仅为防呆，上限读
gates.yaml `defaults.verdict_wait_seconds`（默认 30，与 gate 执行超时 `per_gate_timeout_seconds`
是两个语义）。`step_done`/`step_complete`/`step_gate_summary` 在 verdict 未落盘（PENDING/UNKNOWN）时输出
GATE_PENDING，绝不视为通过。`decide_action` 未显式传参时从 gates.yaml
`triggers[step_id].on_failure` 读取 retry.max / back_off_to / escalate.after_exhausted。

完整 schema: `templates/orchestrator-state.template.yaml`
详细状态机契约: `scripts/main-agent-helpers.sh`
g026 批跑输入契约: `schemas/g026-input.schema.yaml`
