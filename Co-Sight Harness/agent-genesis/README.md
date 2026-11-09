<div align="center">

# AgentGenesis

**从自然语言需求生成完整可运行的 Agent 与 Skill 的元工厂**（Claude Code / DSH 双平台）

[![Version](https://img.shields.io/badge/version-0.23.0-blue)](.claude-plugin/plugin.json)
[![Status](https://img.shields.io/badge/status-active-success.svg)](https://github.com/your-org/agent-genesis)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Plugin-7c3aed)](https://claude.com/claude-code)

[功能特性](#-功能特性) · [快速开始](#-快速开始) · [使用说明](#-使用说明) · [架构](#%EF%B8%8F-架构) · [质量保障](#-质量保障)

</div>

---

## 简介

AgentGenesis 是一个 Agent / Skill 元工厂插件，可运行在 Claude Code 上，也可安装到 DSH（DeepSeek Harness）。输入一段自然语言需求描述，经过「需求澄清 → 模式匹配 → 方案审批 → 构建 → 验证 → 可选评测」的流水线，交付完整可独立运行的 Agent 或符合 Anthropic 规范的 Skill——无需了解设计模式、加载策略或宿主目录规范。

产物平台由 `--platform` 决定：

- `claude-code`（默认）— Agent / Skill 落地为 Claude Code 原生目录，`cd` 进入产物目录并启动 `claude` 即可使用
- `dsh` — Agent 落地为 DSH 原生 bundle 包（`package.json` + `cordis.patch.yml`），`dsh plugin --profile <p> add` 安装后在 UI 中选择使用
- `both` — 两套产物同时生成（同一份 `CLAUDE.md` 复用），便于一份需求跨两个宿主交付

## ✨ 功能特性

- **Agent 创建**（`/harness-create`）— 从自然语言需求生成完整 Agent 工程，含 27 个设计模式的级联匹配、结构化方案审批与独立就绪度评分（L0–L3）
- **双平台产物**（`--platform claude-code|dsh|both`）— Claude Code 原生目录或 DSH 原生 bundle 包；DSH 产物由 `gate.dsh.output` 门禁校验结构，可直接安装与选择
- **知识库注入**（`/harness-create` 入口可选）— 传入 RAG 工作流 id 后，生成的 Agent 自动获得 `rag-knowledge-search` Skill，可通过 co-knowledge 的 `POST /api/co-knowledge/v1/agent/query` 检索知识库并携带引文作答
- **Agent 优化**（`/harness-create` optimize 模式）— 对已有 Agent 就地增量修改，支持三种输入形态：直接给方向 / 提供 session trace 由独立诊断器分析 / 仅提优化意向由系统评估后推荐方向；改动严格限制在点名文件内，越界自动回滚
- **Skill 创建**（`/skill-foundry` create）— 生成符合 Anthropic Skill 规范的完整工程（SKILL.md + references/ + scripts/ + templates/）
- **Skill 优化**（`/skill-foundry` optimize）— 6 维系统化诊断 + 点名式增量修改，附 delta 报告
- **Skill 诊断**（`/skill-foundry` diagnose）— 产出 7 维诊断报告，不修改任何文件
- **双构建车道** — 系统自动判定：简单需求走标准模式（单轮生成 + 机器检查），复杂需求走完整流程（模式匹配 + 人工审批 + 独立评分），判定即执行无需选择
- **真实 E2E 评测**（可选）— 生成测试用例并真实执行，禁止以静态检查冒充运行验证，评测由独立上下文的 evaluator 盲评
- **工厂自检**（`/selftest`）— 23 个 golden 用例端到端回归插件自身

## 🚀 快速开始

### 环境要求

- Claude Code CLI
- Python 3.8+（E2E 评测与部分 gate 脚本需要）

### 安装

**插件市场安装（推荐）**

```bash
claude plugin marketplace add <your-registry-url>
claude plugin install agent-genesis@agent-genesis
```

**本地目录安装**

```bash
git clone <repo-url> AgentGenesis
cd AgentGenesis
claude plugin install --from-directory .
```

**源码开发调试**

```bash
cd AgentGenesis
claude   # 以源码目录直接启动
```

### 创建第一个 Agent

在任意项目目录启动 `claude`，输入：

```
/harness-create 一个代码审查 Agent：读取 Git diff，按安全性/性能/可维护性
三个维度审查代码，生成 Markdown 审查报告。安全问题需阻断合并。
```

流水线将依次执行：

1. **需求澄清** — 诊断式追问，收敛后需确认（DC-010）
2. **车道判定** — 自动选择标准模式或完整流程
3. **构建方案审批**（完整流程）— 展示文件清单、风险列表与抽查计划，等待批准（DC-001）
4. **实施构建** — 批次生成 + 批内自修复，支持断点恢复
5. **就绪度评分** — 独立 verifier 输出 L0–L3 等级
6. **E2E 评测**（可选）— 真实执行测试用例 + 4 维盲评

完成后产物位于 `output/agents/code-reviewer/v1/`：

```bash
cd output/agents/code-reviewer/v1
claude    # 即装即用
```

## 📖 使用说明

### `/harness-create` — Agent 创建与优化

**创建**：直接描述需求即可。

**优化**：在需求中包含目标 Agent 路径与优化意图，按提供的信息分三种形态收敛：

| 输入形态 | 处理方式 |
|---------|---------|
| 明确的改动方向 | 直接按方向执行，追问需修改的文件（点名清单） |
| session trace（JSONL 路径） | 独立诊断器分析执行痕迹，给出候选优化方向，确认后执行 |
| 仅优化意向（无方向无 trace） | 先对目标 Agent 做现状评估，基于证据推荐方向，确认后执行 |

优化模式的安全约束：动手前自动快照目标目录；构建后机器校验改动是否越出点名清单，越界则终止并自动回滚快照；改动范围限定为点名 ≤2 个文件且不含结构变更，超出范围会明确告知（建议按新需求重新 create 或手动修改）。

**知识库注入**（可选）：入口参数 `--input-dir <目录>`（目录内 `knowledge.json` 形如 `{"workflow_id": "RAG_Workflow_xxx"}`）或 `--knowledge-workflow-id <id>` 任一提供时启用：

```bash
/harness-create --knowledge-workflow-id RAG_Workflow_780f 一个运维助手，回答设备告警处理问题
```

- 生成的 Agent 产物内含 `.claude/skills/rag-knowledge-search/`，调用方式：`echo '{"question": "..."}' | python .claude/skills/rag-knowledge-search/scripts/execute.py`
- 地址与 API Key 逐字段解析：框架「知识库路由设置」的生效路由（`routeUrl` + API Key，用 `{COSIGHT_HOME}/.module-token` 读取）优先，缺失时回落到 `CO_KNOWLEDGE_BASE_URL`（默认 `http://localhost:4910`）与 `CO_KNOWLEDGE_API_KEY`
- Agent API 只执行**已发布**工作流；`dialogue_id` 已废弃，统一使用 `conversation_id`（旧字段仍作为别名兼容）
- 注入资产为**预置产物**（`generation: pre_staged`），构建器不重写其内容；G029 审计清单一致性、固定端点、历史实现与 MCP 残留
- 未传上述参数时流程与旧版完全一致；MCP 能力不在迁移范围内

### `/skill-foundry` — Skill 创建 / 优化 / 诊断

单一入口，三种模式：

```
# 创建
/skill-foundry 创建一个 Python 代码风格检查 Skill：用 ruff 检查 PEP 8，
输出结构化的问题列表和修复建议

# 优化（点名问题与文件，增量修改）
/skill-foundry 优化 skills/my-code-review/ ——输出太啰嗦，收敛为结构化清单

# 诊断（只出报告，不改文件）
/skill-foundry 诊断 skills/my-code-review/
```

### `/selftest` — 工厂自检

用 23 个 golden 用例端到端回归 AgentGenesis 自身（意图路由 / 模式匹配 / 两条流水线）：

```bash
# 自检副作用会写入当前目录，请在专用空目录执行
mkdir -p /tmp/ag-selftest && cd /tmp/ag-selftest
/selftest                    # 全量；--ids <id> / --domain <字母> 可过滤
```

### `/dev` / `/dev-off` — 开发模式

修改 AgentGenesis 自身源码时，用 `/dev` 解锁插件写保护，改完立即 `/dev-off` 恢复。日常使用保持写保护状态。

### 产物结构

**Agent**（`output/agents/{name}/v1/`）— 仅含运行时所需文件：

```
code-reviewer/v1/
├── CLAUDE.md            # Agent 主定义（行为规范 + 工作流）
├── agents/              # 子 Agent 定义（如有拆分）
├── skills/              # 内嵌 Skill（如有）
└── …
```

平台为 `dsh` / `both` 时另含 DSH bundle（详见[平台适配](#-平台适配claude-code--dsh)）：

```
code-reviewer/v1/dsh/
├── package.json         # npm 包清单，dsh.bundle.patch -> ./cordis.patch.yml
├── cordis.patch.yml     # 插入 preset 行与子插件行
├── install.sh           # dsh plugin --profile <p> add .
├── README.md            # 安装 / 使用 / 能力差异
├── rules/               # 规则与资料
└── skills/              # 技能（由 customSkillDirs 挂载）
```

**Skill**（`output/skills/{name}/v1/`）— 符合 Anthropic Skill 规范：

```
py-lint/v1/
├── SKILL.md             # Skill 主定义
├── references/          # 深度参考文档（按需加载）
├── scripts/             # 可执行脚本
└── templates/           # 输出模板
```

构建过程的中间档案（匹配决策、方案、审批记录、验证报告）统一落在 `.agent-genesis/work/{name}/`，交付目录不含任何构建残留。

## 🔀 平台适配（Claude Code / DSH）

### 选择平台

```bash
/harness-create --platform dsh 一个代码审查 Agent：读取 Git diff ...
/harness-create --platform both 一个代码审查 Agent：...   # 两个宿主都要
```

`--platform` 缺省为 `claude-code`；`both` 共用同一份 `CLAUDE.md`，其余产物按宿主各写一套。平台判定结果记录在 build-plan 的 `platforms[]`，下游规划、生成与门禁均以此为准。

### 产物形态

| 能力 | Claude Code | DSH |
|------|-------------|-----|
| Agent 身份 | `CLAUDE.md` + `.claude/` 目录 | `dsh/package.json` + `dsh/cordis.patch.yml` 插入 preset 行（bundle 包） |
| 子 Agent | `.claude/agents/<role>.md` | preset 内每个角色一行 `@deepseek-ai/dsh-tool-subagent` |
| Skill | `.claude/skills/<name>/` | `dsh/skills/<name>/`，由 `@deepseek-ai/dsh-skill-filesystem` 的 `customSkillDirs` 挂载 |
| 规则 / 资料 | `.claude/rules/` | `dsh/rules/` |
| settings / hooks | `.claude/settings.json`、`hooks.json` | **无等价物**，不生成；差异写入 `dsh/README.md` 的「能力差异」节 |

DSH 的 preset registry 不扫描目录，因此新 Agent 只能以 bundle 包形式安装：

```bash
cd output/agents/code-reviewer/v1/dsh
./install.sh web          # 等价于 dsh plugin --profile web add .
# 重启 dsh，在 UI 中选择该 Agent
```

### 事实源与门禁

- **唯一事实源**：`knowledge/agent-creation/platforms/dsh.yaml`。DSH 侧字段（插件名、目录约定、bundle 契约）若变更只改这一处，planner / executor / 门禁全部跟随
- **结构门禁**：`gate.dsh.output`（`scripts/gates/g030-dsh-output.sh`）在构建期校验 `package.json`、patch 可解析性、preset 行 id / `toolName` 唯一性、subagent 必填字段、技能挂载是否指向本包、纯 dsh 产物是否残留 `.claude/` 与 Claude 专有工具名、`install.sh` 语法等
- **平台不适用时自动跳过**：未要求 dsh 平台且产物中无 `dsh/` 时门禁直接 PASS，不影响既有 Claude Code 流程

### 知识库注入的落点

`--target-platform` 与入口 `--platform` 保持一致，注入器按平台决定 `rag-knowledge-search` 的落点：

| 平台 | 技能落点 |
|------|---------|
| `claude-code` | `.claude/skills/rag-knowledge-search/` |
| `dsh` | `dsh/skills/rag-knowledge-search/` |
| `both` | 上述两处各一份 |

清单 `injected-assets.yaml` 用 `knowledge.relative_dirs` 记录全部落点（`relative_dir` 保留首项作兼容），G029 逐条校验。注入时会改写技能文档内自引用的路径，确保 DSH 产物不自指 `.claude/`。

覆盖已有技能时：`claude-code` 沿用同级 `<name>.bak-<时间戳>`；`dsh` / `both` 的备份移出技能根到 `work/backups/`——DSH 的 `customSkillDirs` 会扫描技能根下每一个子目录，残留的 `SKILL.md` 会造成同名技能冲突。

## 🏗️ 架构

```
自然语言需求
     │
     ▼
需求澄清（DC-010 确认）──► 车道判定（fast 直达 / full 继续）
     │                            │
     ▼                            ▼
┌─ full 车道 ─────────────────────────────────────┐
│ 模式匹配（27 模式库级联匹配）                    │
│   → 构建规划（per-file 方案）                    │
│   → DC-001 人审                                  │
│   → goal-loop 实施构建（批次 + 自修复 + 断点恢复）│
│   → 独立就绪度评分（L0-L3）                      │
└──────────────────┬──────────────────────────────┘
                   ▼
        可选：E2E 真实测试 → 4 维盲评
                   ▼
     output/agents|skills/{name}/v1/
```

- **编排层**：Main Agent 状态机驱动步骤推进、决策与落盘
- **执行层**：12 个 SubAgent 各自独立上下文（匹配 / 规划 / 构建 / 验证 / 测试 / 评测 / fast 车道三件）
- **门禁层**：语义键 gate 注册表（`phase/gates/gates.yaml`，6 gates + 3 runners + 25 step triggers）在每步之后执行确定性校验

## ✅ 质量保障

- **模式不编造** — Agent 结构从 27 个已验证设计模式库中匹配（工作流编排 / 知识源 / 数据流 / 人机交互 / 约束安全 / 自进化），不允许凭空发明
- **验证者独立** — 评分与测试的 verifier 禁止读取构建者的推理过程（独立上下文 + forbidden_inputs），防止自我验证
- **门禁落盘** — 每个 Pipeline 步骤后执行确定性机器检查（产物完整性 / 占位符 / 引用闭合 / 声明与实际产出一致），fail-closed
- **运行时真伪** — E2E 评测执行真实运行，结果带 verdict / exit_code 证据
- **诚实声明** — 每阶段报告强制包含 `outcome_status`（verified / blocked / declined / unrunnable）
- **路径封锁** — SubAgent 写入范围限定在 work/ 与 output/，由 hook 强制拦截越界写入

## ⚠️ 已知局限

AgentGenesis 解决的是**结构性可观察**问题。LLM 固有偏差（完成偏置 / SubAgent 互信级联 / 元认知上限）只能减弱、不能消除——这是上述机制的设计边界。对关键产物，建议始终执行 E2E 评测。

DSH 平台为实验性支持（事实源基线：deepseek-harness-master @ 2026-10）。DSH 无 `settings.json` / hooks 等价物，这类能力不会在 DSH 产物中出现；宿主字段若发生变更，需更新 `knowledge/agent-creation/platforms/dsh.yaml` 后重跑门禁。

## 📋 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.24.0 | 2026-10 | `rag-knowledge-search` 改用 co-knowledge Agent API（`/api/co-knowledge/v1/agent/query` + `Authorization: Bearer` API Key）；地址与 Key 优先读框架「知识库路由设置」生效路由，环境变量兜底；`dialogue_id` → `conversation_id`（旧字段兼容）；G029 增加旧查询链路与 Agent API 契约检查 |
| 0.23.0 | 2026-10 | DSH 双平台产物：`--platform claude-code\|dsh\|both`、`platforms/dsh.yaml` 事实源、DSH bundle 模板、`gate.dsh.output` 结构门禁；知识注入支持 `dsh/skills/` 双落点 |
| 0.22.0 | 2026-10 | 知识库注入（Step 1b + `rag-knowledge-search` + G029 审计门），对接 co-knowledge `/api/rkb/v1/query`；不迁移 MCP |
| 0.21.0 | 2026-10 | fast 车道 v1.3 单判据准入 + golden 样例池 + 语义键 gate 注册表 |
| 0.20.0 | 2026-09 | executor v2 goal-loop（批次 + 自修复 + 断点恢复）+ REFLUX 样例沉淀闭环 |
| 0.18.0 | 2026-08 | skill-foundry 三模式统一（create / optimize / diagnose） |
| 0.17.0 | 2026-07 | 9 步 Pipeline 重写 + SubAgent 独立 context + 交付目录只含运行时面 |
| 0.15.0 | 2026-06 | Honesty-First 6 机制 + Env Probe + DC-001 结构化审批 |

## 🤝 贡献

欢迎 Issue 与 PR。修改插件自身代码前请先执行 `/dev` 解锁写保护，完成后 `/dev-off` 恢复；提交前建议在专用空目录跑一次 `/selftest` 回归。

## 📄 许可证

许可证待定（TODO）。

---

<div align="center">

**AgentGenesis** — the Agent that builds Agents.

</div>
