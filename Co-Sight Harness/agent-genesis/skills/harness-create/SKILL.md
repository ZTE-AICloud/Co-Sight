---
name: harness-create
description: Agent 工厂入口（创建/优化双模式）。创建：接收自然语言需求，经 8 步 Pipeline（需求澄清→模式匹配→方案审批→构建→验证→可选评测）产出 output/agents/{name}/v1/ 完整 Agent 工程。优化：对已有 Agent 就地增量修改，支持三种输入形态——直接给方向并点名文件 / 提供 session trace 由诊断器分析 / 仅提优化意向由系统评估推荐方向；改动限定点名 ≤2 个文件且不含结构变更，构建前自动快照、越界自动回滚。当用户请求创建/搭建/生成 Agent/Harness，或优化/改进/调整既有 Agent（提到目标 Agent 目录、给出 trace 路径、或要求修改某个 Agent 的行为）时触发。输入为需求文本或"目标 Agent 路径 + 优化意图"，输出为完整工程或就地修订后的 Agent。
---

# Agent 创建 — Pipeline 入口

## 渐进式加载约定
- L2（本文件）：orchestration 逻辑，保持精简
- L3（references/，按需 Read）：
  - `references/workflow.md` — 各 Step 详细编排说明（输入/产出字段 = 人读编排视图）
  - `references/workflow-fast.md` — fast 车道编排视图（Lane 判定 = fast 时才 Read, experimental）
- 机检数据源：`phase/gates/gates.yaml` triggers[].outputs（step 产物落盘清单，G024 消费）
  — **注意路径**: gates.yaml 在插件根（`~/.claude/plugins/cache/...`），只读，禁止写入

## 路径约定（原 contract.yaml paths 模板，P10 后唯一权威在此 + phase/00-conventions.md）
- `work_root` = `.agent-genesis/work/{name}/agent-creation/`
- `output_root` = `output/agents/{name}/v1/`
- 基准目录 = 用户 cwd（`$PWD`）；插件根只用于读 knowledge/，**禁止写入**

## 平台适配（Claude Code / DSH）

本流水线同时支持两个宿主。**先判定平台，再决定产物形态与工具调用方式。**

**判定顺序**：
1. 用户显式传 `--platform <claude-code|dsh|both>` → 以它为准。
2. 否则看当前可用工具：出现 `todo_write` / `ask_user_question` / `subagent`
   且没有 `Task` / `TodoWrite` → **DSH**；否则 → **Claude Code**（默认）。
3. 判定结果写入 `.agent-genesis/work/{name}/agent-creation/platform.yaml`，后续步骤只读该文件。

**参数获取差异**：Claude Code 从 `$ARGUMENTS` 解析；DSH 的 `skill` 工具
**只接受 `name`，不支持 args**，兼容层也不做 `$ARGUMENTS` 替换——此时参数只能来自
用户消息原文（`/agent-genesis:harness-create` 之后的同一行）或已落盘的
`.agent-genesis/` 文件。两处都取不到就向用户确认，禁止猜默认目录。

**工具名映射（DSH）**：

| 本文档写法 | DSH 原生 |
|---|---|
| `AskUserQuestion` | `ask_user_question`（参数 `multi_select` 为下划线） |
| `TodoWrite` | `todo_write` |
| `Task` / `Agent` | `subagent`；生成的具名角色用 `subagent_<role>` |
| `Read/Write/Edit/Bash/Grep/Glob` | `read/write/edit/bash/grep/glob` |
| `WebFetch/WebSearch` | `web_fetch/web_search` |

**产物差异（DSH 平台）**：额外产出 `output/agents/{name}/v1/dsh/`（bundle 包：
`package.json` + `cordis.patch.yml` + `skills/`），详见
`knowledge/agent-creation/platforms/dsh.yaml`。`.claude/settings.json` 与
`.claude/hooks/hooks.json` **在 DSH 无原生等价物**，DSH 平台下不生成，改在
`dsh/README.md` 中声明能力边界。`--platform both` = 两套都产。

## 入口参数（可选）

- `--input-dir <目录>`: 输入资产目录；当前仅识别 `<目录>/knowledge.json`（`{"workflow_id": "RAG_Workflow_xxx"}`）
- `--knowledge-workflow-id <id>`: 直接指定 RAG 工作流 id，优先于 `knowledge.json`
- `--platform <claude-code|dsh|both>`: 产物平台，缺省 `claude-code`

前两者均未提供 → **不启用注入**，后续流程与既有版本完全一致。
任一经提供 → 在 Step 1 拿到 `{name}` 后立即执行 Step 1b。

> 参数来源：Claude Code 读 `$ARGUMENTS`；DSH 读用户消息原文（见「平台适配」）。

## 第一步：入口探针
从用户需求解析 {name}（kebab-case，向用户确认），代入上述路径模板。

**入口即探针**（P1 归并，原 step-0-env-probe 抽成独立脚本）:
```bash
bash scripts/env-probe.sh {name}
```
- 输出 `.agent-genesis/work/{name}/env-readiness.yaml`（追溯用）
- 失败 escalate always：缺工具/权限直接报用户
- **不**走节点（避免独立 node + schema + 状态流转的开销）

## Step 1b：知识库资产注入（仅在入口参数含 `--input-dir` 或 `--knowledge-workflow-id` 时执行）

在 Step 1 产出 `{name}` 后、Lane 判定前执行一次（不进入 Step 序列，不写 step verdict）：

```bash
python {PLUGIN_ROOT}/scripts/inject-input-assets.py \
  --input-dir <解析后的输入目录> \
  --output-dir output/agents/{name}/v1 \
  --work-dir .agent-genesis/work/{name}/agent-creation \
  [--knowledge-workflow-id <id>] [--verify] \
  [--target-platform <claude-code|dsh|both>]
```

- 产物落点随平台：`claude-code` → `.claude/skills/rag-knowledge-search/`；
  `dsh` → `dsh/skills/rag-knowledge-search/`；`both` → 两处都落。
  manifest 的 `knowledge.relative_dirs` 记录全部落点，`relative_dir` 保留首项兼容
- 同时产出 `.agent-genesis/work/{name}/agent-creation/injected-assets.yaml`
- **注入不覆盖用户资产**：目标已存在且内容不一致 → 先备份再重写。
  `claude-code` 备份为同级 `rag-knowledge-search.bak-<时间戳>`；
  `dsh`/`both` 备份到 `.agent-genesis/work/{name}/agent-creation/backups/`
  （技能根下不能留备份：`customSkillDirs` 会扫描每个子目录，残留 `SKILL.md` 会造成同名技能冲突）
- 退出码 0 = injected/noop，2 = 输入非法或注入失败 → 直接报用户并终止（不降级为"无知识库"继续构建）
- 输入目录中的 `mcp.json` **不在迁移范围**，注入器忽略并记 warning，不向用户提示可选 MCP 能力
- **注入生效的事实源就是 `injected-assets.yaml` 本身**（`status` ∈ {injected, noop}）：
  Lane 判定、build-planner、executor、G029 均读该文件判定，不另写 state 标记
- 之后 build-planner 必须把该 skill 标为 `generation: pre_staged`（见 `agents/build-planner.md`），executor 不重新生成

## 第 1.5 步：Lane 判定（experimental——详见 `references/workflow-fast.md` §Lane 判定节）

Step 1 澄清完成并收敛后单点执行, 只增不改 full 车道任何行为（红线 R7）。
**前置层（v1.2 裁定, 两线一致）**: 澄清不清楚不作为路由依据——字段缺失/未收敛 →
回 Step 1 继续澄清, 不进入判定（不写 lane-decision）; 续跑不重进本节。
**create/optimize 双维度**（各 ≤20 行, 正交共置——create 用 agent 段判据走 step-f1; optimize 用 optimize 语义
走 step-f2, 见判定节 optimize 维度）:

0. **知识库注入生效优先**: 本次运行执行过 Step 1b 且 `injected-assets.yaml` 的
   `status` ∈ {injected, noop} → **静默走 full, 不询问**（pre_staged 资产依赖 full 车道的
   build-plan 对账与注入审计门禁, fast 车道不支持）
1. **非交互保障优先**: 当前为不可交互上下文（selftest / e2e 管道 / headless / CI）→
   **静默走 full, 不询问**; criteria.yaml 缺失/解析失败 → 同样静默 full（配置完整性兜底）
2. **T1 判定（create）**: 对照 `knowledge/fast-lane/criteria.yaml` agent 段评估
   `fast_path_hit`（v1.3 单判据 OR 语义, 输入 = clarified YAML 显式字段;
   三分支: anchor 锚定核心模式之一(拓扑/外部集成不限) / low_complexity 单 Agent
   或简单协同可交付 / sampled golden 池有实例包）+ 模式锚定
   （task-mode-pattern-mapping.md 认定唯一主模式）;
   命中任一分支即直接 fast（留痕注明分支）, 全不命中 → 静默走 full 不打扰
3. **直道执行（D-04）**: 判定即执行, 不调 AskUserQuestion——命中 → 直接进 fast 驱动节,
   输出一行 `车道判定 → 标准模式构建（fast）`;
   用户明示"样例"/"走 full" 等则照办
4. **optimize 维度（FC）**: 用户意图为优化既有 Agent 时, 澄清段按三输入形态分流
   （方向直取 / trace→派 trace-analyzer / 仅"要优化"→现状描摹, 详见 workflow-fast.md
   optimize 段）收敛为"方向+点名"; T1 对照 skill_optimize 同款语义（点名 ≤2 /
   无结构变更 / 目标静态可定位）——全过 → 直接 fast（D-04 不问询; 裁定 6: agent 线
   optimize **只走 fast**, 用户显式拒绝 → 终止不改道）; 不过 → 告知超范围与去处（create 重建/手动）,
   **无 full optimize 可去**（agent-optimize-diagnose-mode.md 已缩水取代）
5. **留痕**: 判定写 `.agent-genesis/work/{name}/fast-lane/lane-decision.yaml`（走 full 也落）
6. **分道**: full → 原第二步（一切照旧）; fast → fast 驱动节（下方对应 mode）

## fast 驱动节（lane = fast 时替代第二步, 步骤详述 = workflow-fast.md §fast 驱动步骤）

Read `references/workflow-fast.md`, 按 fast 驱动步骤 1-6 驱动 step-f1-fast-build 到尾:
init+落盘 → Agent(fast-lane-builder) 单轮 → g025 物化 → G024 → G028 直调（agent-exit 档,
stdin JSON, 不经 g026）→ 合并 verdict + step_complete 单入口 → 按 action 分叉:
PASS → 交付汇报（模式明示 + 质量门禁提示 + 评测未运行提示）; FAIL → 修复轮一轮
（revision-request.json → builder 新会话 → 重跑 3-6）→ 再 FAIL → **终止 + 失败报告**
（三要素, 不升级 full）; ESCALATE_* → 按落盘选项问用户。
fast 车道不走 DC-010 通道建议消费 / DC-001 人审（G028 为唯一交付闸门）。

## fast 驱动节 · optimize（lane = fast 且 mode = optimize 时, 步骤详述 = workflow-fast.md optimize 段）

三输入形态在澄清段分流（trace 形态先派 trace-analyzer 出诊断再请用户确认）, 收敛为
"方向 + 点名清单"后走安全三件（同 skill 线规格, §4.0 禁各自变体）: 快照（目标 → fast-lane/snapshot/）
→ Agent(fast-lane-builder --mode optimize, 就地修订 + build-plan 对账——目标无 build-plan
则生成反映现状的极简 build-plan) → check-delta-scope（越界即终止+快照恢复）→ G024（按实际
形态传 outputs 子集——形态②含 trace-diagnosis.md）+ G028 agent-exit 档后测 → 合并 verdict
+ step_complete step-f2-fast-optimize → 分叉（修复轮仅修 FAIL 项; 终止出失败报告三要素）。

## 第二步：按 workflow.md Step 序列驱动
Read `references/workflow.md`，对其 Step 0-6c 逐个驱动（Step 6a/6b/6c 需 Step 5.5 用户选 Run 才执行）：
1. Read workflow.md 中本 Step 章节 → 按「输入」字段确认上游产物存在 → 缺失则按 Step 失败回路回退
2. 按 mode 调度（平台判定见「平台适配」）：
   - `main_agent` / `main_agent_direct` → 直接执行（Bash / `ask_user_question`）
   - `skill:<name>` → **Claude Code**: `Skill({name}, args="--output-dir <解析后路径>")`；
     **DSH**: 先调 `skill({name})` 加载正文，再把 `--output-dir <解析后路径>` 等参数
     写进紧邻的任务指令（`skill` 工具不接受 args，写进参数会被丢弃）
   - `subagent:<name>` → **Claude Code**: `Agent({subagent_type}, prompt)`；
     **DSH**: 优先用生成的具名工具 `subagent_<role>`；无具名行时用 `subagent`，
     并把角色名与完整任务写进 prompt
3. 每 Step 后跑 gate 并落盘 verdict → **step_complete 单入口决策**（执行+决策+落盘一体,
   完整契约见 workflow.md §Main Agent 必做）:
   - pipeline 启动先 init（step_complete fail-closed 要求 state 已存在）:
     `bash scripts/main-agent-helpers.sh init ".agent-genesis/work/{name}" agent-creation`
   - G024 落盘检查（机检权威 = gates.yaml triggers[step_id].outputs）:
     ```bash
     echo "{\"step_id\": \"<step_id>\", \"name\": \"{name}\", \"root\": \"$PWD\"}" | bash {PLUGIN_ROOT}/scripts/gates/g024-output-exists.sh
     ```
     `{PLUGIN_ROOT}` = env-probe/Step 0 已解析的插件根绝对路径，字面替换，禁止依赖 shell 环境变量
     `--root $PWD` 必须显式传（防 cd 后 cwd 漂移）
     FAIL-CLOSED: outputs 清单缺失/为空即 FAIL，绝不空转恒 PASS
     **step-4 例外**: G024 只做兜底校验（`.agent-genesis/work/{name}/gate-results/step-4-implementation.json`
     存在且 verdict 字段非空——executor 已写 step verdict），结果落同目录 `step-4-implementation.g024.json`，
     **不得写入/覆写 step verdict 文件**；verdict 消费照旧读后者
   - 合并该 step 全部 gate 结果写 `.agent-genesis/work/{name}/gate-results/<step_id>.json`
     （verdict 取最坏值; state 与 gate-results 均在 `{name}` 层, 00-conventions 产物分类表）
   - 单入口:
     ```bash
     bash scripts/main-agent-helpers.sh step_complete <step_id> ".agent-genesis/work/{name}" "$OUTPUT_DIR" "$outputs_json"
     ```
     按输出单行 JSON action 导航（PROCEED/PROCEED_WITH_CONCERNS/RETRY/BACK_OFF/ESCALATE_*;
     GATE_PENDING 绝不视为通过）; 重试上限/回退目标/升级阈值唯一权威 = gates.yaml
     triggers[].on_failure; pipeline 收尾 `status ".agent-genesis/work/{name}" COMPLETED`

**[P10.5 拉起规则] 分发 SubAgent 时只传 prompt 参数（--build-plan / --output-dir 等），
不传输入文件列表** —— SubAgent 的输入清单以 `agents/<name>.md`「输入」段为执行权威，
workflow.md 的「输入」字段仅是人读编排视图（ agents 输入段 ⊇ workflow 输入字段）。

## 第三步：里程碑
全部 Step 完成 → 运行时主交付 CLAUDE.md 齐备已在 executor 收尾由 G028（agent-exit 档）
校验（G028 agent-exit 档含运行时主交付 CLAUDE.md 齐备检查）→ 汇报产物位置 + **按平台给启动方式**：

- `claude-code`：`cd output/agents/{name}/v1 && claude`
- `dsh`：`cd output/agents/{name}/v1/dsh && dsh plugin --profile <profile> add .`，
  重启 DSH 后在界面选择 preset；开发期可 `dsh --patch ./cordis.patch.yml`（需在已装 DSH 依赖的目录）
- `both`：两段都给，并说明 `.claude/` 与 `dsh/` 各自独立、互不依赖

汇报必须包含「质量门禁提示」固定段（数据源 = `.agent-genesis/work/{name}/gate-results/g028-exit-sanity.json`
顶层 concerns[]）: 无则写「质量门禁全部通过」; 有则逐条以用户语义转述，不出现内部编号与术语。

full 车道交付时汇报末尾补沉淀建议句（C9-6 固定措辞, 契约见 `knowledge/golden/REFLUX.md` §4）:
「本次构建的形态可沉淀为样例, 下次同类需求可直接套用」——仅陈述不追问; 用户确认后按
REFLUX.md 档 1 流程启动沉淀。fast 车道产物形态已源自样例, 不补此句。

## 目标导向汇报（P5: IV1 强化，回归只需删本节）

每节点完成时由 main agent 渲染进度，坐标是「距可运行 Agent」而非 step_id：

```
[2/8 → 可运行 Agent] Agent 能力方案已确定: 共 4 项核心能力模块（方案无遗留疑点）
  下一步: 构建方案 → 你的审批（预计还需 2 次确认）
  剩余: 方案审批 → 构建（~N 文件）→ 就绪验证
```

> **用户面禁则（C9-6）**: 上述渲染文本不得出现内部 gate/pattern 编号（G0xx/W1/K4…）、
> 置信度、内部流程术语（决策物化/物化表/CONCERNS）与版本修饰词——用用户语义词汇
> 转述（如"质量门禁全部通过"）。内部精确语言只存在于 agent 定义/日志层。

| 模板变量 | 数据来源 | 渲染时机 |
|---------|---------|---------|
| `current/N` | orchestrator-state.yaml steps[].step_id | 每 step finish |
| `已完成节点` | 最近完成 step 的语义描述（pattern 已选 / 方案已批准 / 实施已完成） | 每 step verdict |
| `下一步` | 当前 steps 列表中下一步 step_id + 预计交互次数 | 估算 |
| `剩余` | steps 中未跑 step 的语义链 | 实时 |

**回退**：删除本节即可回退原 step_id 直白汇报（IV1 退化但不影响功能）。

**评测未运行提示行（OPT-3）**：Step 5.5 默认跳过评测（无询问），里程碑完成摘要必须
显著标注「评测未运行，可随时 `/e2e-test-ci` 补跑」；用户在任意汇报节点主动插话要求
评测 → 写 `step6-decision.yaml`（run）进入 Step 6/6c。

## 异常处理
- 整 pipeline retry 累计 ≤ 5（circuit_breaker，状态在 `.agent-genesis/work/{name}/orchestrator-state.yaml`）
- human_approval 节点（DC-010 / DC-001）暂停等待用户，超时 24h 标记 BLOCKED
- 续跑：Step 4 由 agent-executor 按 output_dir 文件系统对账跳过已存在声明文件，入口 skill 不重复调度已完成 Step
