# Phase 2: Agent 创建 Pipeline

> 8 步 (含 Step 5.5 评测 opt-in)
> 互指: fast 车道（experimental）人读视图 = `references/workflow-fast.md`（车道 2, step-f1; 分道判定在 SKILL.md §第 1.5 步）——本文件仅 full 车道（车道 1）, 两视图互为唯一对照
> gate trigger 绑定与 invoked_by 调用点见 `phase/gates/gates.yaml`（无自动引擎, gate 为显式调用）
> main agent 状态机契约见 `scripts/main-agent-helpers.sh`
>
> [P10.5 编排视图] 本文件各 Step 的「输入/产出」字段是人读编排视图，非机器可检权威：
>   执行权威 = `agents/<name>.md` 各 SubAgent 的「输入/产出」段；
>   机检权威 = `phase/gates/gates.yaml` triggers[].outputs（G024 消费，漂移时修 gates.yaml）

---

## Step 0: 入口探针（非节点）

- 入口即探针: `bash scripts/env-probe.sh {name}`（原 Step 0 抽成独立脚本）
- 产出: `.agent-genesis/work/{name}/env-readiness.yaml`（供 main agent 追溯，不进 gate）
- 失败: escalate always（缺工具/权限），由 main agent 直接报告用户
- P1 归并说明: 不再走 `step-0-env-probe` 节点（避免独立 node + schema + 状态流转的开销大于价值）

---

## Step 1: 需求澄清

- step_id: `step-1-requirement-clarification`
- mode: skill
- Skill: requirement-clarifier（v0.18, 旧名 agent-requirement-clarifier, 模式 = agent）
- prompt: `--output-dir output/agents/{name}/v1/`
- 产出:
  - `.agent-genesis/work/{name}/agent-creation/clarified-agent-requirements.yaml`
- schema: `skills/requirement-clarifier/references/schemas/clarified-agent.schema.yaml`
- human_approval: DC-010

---

## Step 1b: 知识库资产注入（非节点，可选）

- 触发条件: 入口参数含 `--input-dir` 或 `--knowledge-workflow-id`（见 SKILL.md「入口参数」）
- 时点: Step 1 产出 `{name}` 后、Step 1.5 Lane 判定前；**只执行一次**
- 命令:
  ```bash
  python {PLUGIN_ROOT}/scripts/inject-input-assets.py \
    --input-dir <输入目录> \
    --output-dir output/agents/{name}/v1 \
    --work-dir .agent-genesis/work/{name}/agent-creation \
    [--knowledge-workflow-id <id>] [--verify] \
    [--target-platform <claude-code|dsh|both>]
  ```
  `--target-platform` 必须与入口 `--platform` 一致（缺省 `claude-code`）；
  平台判定见 SKILL.md「平台适配」
- 输入契约: `<input-dir>/knowledge.json` = `{"workflow_id": "RAG_Workflow_xxx"}`
  （schema `schemas/knowledge-input.schema.yaml`；`mcp.json` 不在迁移范围，忽略并记 warning）
- 产出（随 `--target-platform`）:
  - `output/agents/{name}/v1/.claude/skills/rag-knowledge-search/`（claude-code / both）
  - `output/agents/{name}/v1/dsh/skills/rag-knowledge-search/`（dsh / both）
  - 每个落点均含 SKILL.md + scripts/{execute,rag_knowledge_search,check_env}.py
  - `.agent-genesis/work/{name}/agent-creation/injected-assets.yaml`
    （schema `schemas/injected-assets.schema.yaml`，字段
    target_platform/knowledge{workflow_id,base_url,relative_dirs,relative_dir,…}/files/warnings；
    新消费方以 `relative_dirs` 为准，`relative_dir` 为兼容首项）
- 失败: 退出码 2 → 直接报用户并终止；**不得**降级为"无知识库"继续构建
- Lane: 注入生效（status ∈ {injected, noop}）→ SKILL.md Lane 判定规则 0 静默走 full
- 下游约束: build-planner 必须把 `rag-knowledge-search` 相关文件标为 `generation: pre_staged`；
  agent-executor 不生成、不覆盖；G029 在 Step 4 验收其完整性
- 端点: 固定 `/api/co-knowledge/v1/agent/query`；地址与 API Key 逐字段解析
  （框架「知识库路由设置」生效路由优先，`CO_KNOWLEDGE_BASE_URL` / `CO_KNOWLEDGE_API_KEY`
  兜底，地址缺省 `http://localhost:4910`），鉴权用 `Authorization: Bearer`；
  不使用服务发现，不访问外部注册中心

---

## Step 2: 模式匹配（含产出后自检）

- step_id: `step-2-pattern-matching`
- mode: subagent
- SubAgent: pattern-matcher（含 G017 自检闭环，见 `agents/pattern-matcher.md`「步骤 8」）
- prompt:
  - 产出格式以 `agents/pattern-matcher.md`「步骤 7: 输出」为**唯一权威定义**，
    写盘前自校 frontmatter 三字段（selected_patterns / rejected[] / build_type）齐全；
    产出后按其「步骤 8」自跑 G017，FAIL 就地修订（≤2 轮），三种终态均落盘
    phase2-review.md + `.agent-genesis/work/{name}/gate-results/step-2-matching-review.json`
  - **PLUGIN_ROOT 注入**: 传入插件根绝对路径（env-probe/Step 0 解析）；步骤 8 G017
    命令模板中 `{PLUGIN_ROOT}` 占位由该值字面替换，禁止依赖 shell 环境变量
  - **知识注入清单**: knowledge/INDEX.yaml、
    knowledge/shared/cascading-matcher.yaml、knowledge/shared/pattern-catalog.yaml、
    knowledge/agent-creation/pattern-matcher.yaml、
    knowledge/agent-creation/harness-design-principles.yaml、
    knowledge/agent-creation/task-mode-pattern-mapping.md、
    knowledge/agent-creation/agent-classic-cases.yaml、
    schemas/matching-decision.schema.yaml
- 输入: clarified-agent-requirements.yaml（+ `injected-assets.yaml`，Step 1b 执行时存在）
- 产出: `.agent-genesis/work/{name}/agent-creation/phase1-matching-decision.md`
  + `.agent-genesis/work/{name}/agent-creation/phase2-review.md`（G017 自检结果）
  + `.agent-genesis/work/{name}/gate-results/step-2-matching-review.json`（DC-001 证据）
- 失败回路:
  - G017 FAIL 超限（subagent 携 failures 返回，verdict=FAIL）→ ESCALATE_STEP（gate-block.md）
  - G017 CONCERNS → 不阻断；concerns 由 runner.review.assemble 自 phase2-review.md 机械透传进
    human-review.md「已知风险」（step-3 组装接线, 见 Step 3），DC-001 人审裁决
  - G024 落盘失败 → on_failure（retry ≤2 → back_off step-1）
- 产出字段: frontmatter `selected_patterns[]` / `rejected[]{pattern_id,reason}` / `build_type{type,topology}`；
  正文新增「结构决策」（build_type_decision: subagents[] 含 split_trigger S1-S4 / skills[] 含 scope_trigger）与
  「决策物化」两节（模式→机制→target_roles→verify_hint，role 级）
- schema: `schemas/matching-decision.schema.yaml`

---

## Step 3: 方案生成

- step_id: `step-3-build-planning`
- mode: subagent
- SubAgent: build-planner
- prompt:
  - `--output-dir output/agents/{name}/v1/`
  - 产出格式以 `agents/build-planner.md`「Step 9: 输出」为**唯一权威定义**（build-plan
    四元组 brief/invariants/acceptance/anti_patterns；增量 = 物化表 target_files 绑定），
    不另造格式
- 输入: phase1-matching-decision.md（含结构决策/决策物化）+ phase2-review.md（step-2 自检产出；
  存在时追加 `injected-assets.yaml`——其 `knowledge.files[]` 必须逐条成为 build-plan 的
  `generation: pre_staged` 条目，`source` 指针指向已注入路径，不得重新生成内容；
  G017 CONCERNS 经 runner.review.assemble 机械透传进 human-review「已知风险」）
- 产出 (work/):
  - `.agent-genesis/work/{name}/agent-creation/asset-adaptations.yaml`（P4-4.1: 合并旧 matched + adapted）
  - `.agent-genesis/work/{name}/agent-creation/human-review-fragment.md`（build-planner 只写判断段,
    8 槽位; 机械段组装见下方「组装接线」）
  - `.agent-genesis/work/{name}/agent-creation/human-review.md`（main agent 组装接线产出——
    判断段透传 + 机械段: §4 文件清单/§5 风险透传/§7 验收转写/§11 拓扑图）
  - `.agent-genesis/work/{name}/agent-creation/build-plan.md`（物化表 target_files 绑定 +
    每文件四元组 brief/invariants/acceptance/anti_patterns；acceptance_criteria 已转化为 invariants[derived_from] 或显式 manual_verify）
- schema: `schemas/asset-adaptations.schema.yaml` + `schemas/build-plan.schema.yaml`
- 校验接线（step-3 边界, main agent 直调——与 G024 per-step 同构；非注册 gate, 不入
  gates.yaml, 不新增 gate 件）: build-planner 返回后、进 G024/step_complete 之前先跑物化对账:

  ```bash
  python3 {PLUGIN_ROOT}/scripts/validate-plan-v2.py \
    --decision .agent-genesis/work/{name}/agent-creation/phase1-matching-decision.md \
    --build-plan .agent-genesis/work/{name}/agent-creation/build-plan.md \
    --catalog {PLUGIN_ROOT}/knowledge/shared/pattern-catalog.yaml \
    > .agent-genesis/work/{name}/gate-results/step-3-build-planning.reconciliation.json
  ```

  - verdict PASS → 继续「组装接线」（下方）→ G024 落盘 + `step_complete` 单入口（「Main Agent
    必做」节, 形态不变）
  - verdict FAIL → **step-3 既有 retry 回路**: 按 gates.yaml
    `triggers.step-3-build-planning.on_failure`（retry ≤1 → back_off step-2-pattern-matching
    → escalate after_exhausted）重跑 build-planner 或回退；重试累计受 pipeline
    `pipeline_retry_budget=5` 约束。FAIL verdict JSON 已落 reconciliation 文件（修复信号, 可追溯）
  - 对账语义: build-plan「决策物化表」为增量表（仅 `pattern_id` + `target_files`）——机制/
    验证方式单源在 matching-decision；表格重新转写（mechanism/verify）、缺绑定行、发明
    matching 表外模式、重复绑定行均 FAIL（MAT_* findings, 机读可点名）
- 组装接线（step-3 边界, main agent 直调 runner.review.assemble——1.6③; 校验 PASS 后、
  G024/step_complete 前机械拼装 human-review.md）:

  ```bash
  python3 {PLUGIN_ROOT}/scripts/render-human-review.py \
    --fragment .agent-genesis/work/{name}/agent-creation/human-review-fragment.md \
    --build-plan .agent-genesis/work/{name}/agent-creation/build-plan.md \
    --decision .agent-genesis/work/{name}/agent-creation/phase1-matching-decision.md \
    --requirements .agent-genesis/work/{name}/agent-creation/clarified-agent-requirements.yaml \
    --review .agent-genesis/work/{name}/agent-creation/phase2-review.md \
    --out .agent-genesis/work/{name}/agent-creation/human-review.md
  ```

  - exit 0 → human-review.md 就绪（判断段自 fragment 逐字透传 + 机械段组装: §4 文件清单/
    §5 风险透传/§7 验收转写/§11 拓扑图），继续 G024 + step_complete
  - exit 2（input_error: fragment 槽位缺失/未知、风险缺等级前缀、风险 <2、输入缺文件或
    解析失败）→ 同 FAIL 回路（step-3 既有 retry 回路重跑 build-planner）
  - 物化对账不在此重复（归上方校验接线）；dc001-channel.sh 对 §5 的消费形态不变
    （风险等级前缀 `- [临界|重大|轻微]` 机械 grep 计数）

---

## Step 3c: DC-001

- step_id: `step-3c-plan-approval`
- mode: human_approval (DC-001)
- **先跑通道判定**: `bash scripts/dc001-channel.sh {work_dir}` 决定 fast / full
  - fast: 压缩面板（文件清单全列 + 物化摘要表 + 风险 top-2 + 一键 Approve/Adjust/Cancel）
  - full: 现有 Step 1-4 完整流程不变
- 4 步: 文件清单 (≥10 行) + 风险 (≥2) + spot-check (≥3) + yes_no
- 通道判定 + 4 项标准逐项结果写入 `.agent-genesis/work/{name}/agent-creation/dc001-decisions.yaml`

---

## Step 4: 独立执行

- step_id: `step-4-implementation`
- mode: subagent
- SubAgent: agent-executor
- prompt:
  - `--build-plan .agent-genesis/work/{name}/agent-creation/build-plan.md`
  - `--output-dir output/agents/{name}/v1/`
  - 执行协议以 `agents/agent-executor.md` 本体为**唯一权威定义**（gate 循环 / 断点恢复 / 收尾三件套），
    prompt 不重复格式细节
  - **PLUGIN_ROOT 注入**: 传入插件根绝对路径（env-probe/Step 0 解析）；executor 全部
    gate 命令模板中 `{PLUGIN_ROOT}` 占位由该值字面替换，禁止依赖 shell 环境变量
  - **环境事实注入（固定模板, 以 env-probe 输出为准）**:
    ① 全程用绝对路径——Bash cwd 会漂移, 状态文件写入用绝对路径;
    ② 无 gate-engine——gate 直接 bash 字面绝对路径执行, verdict JSON 手动持久化到
    `.agent-genesis/work/{name}/gate-results/`;
    ③ g023 invariant 正则注意: `c+` 量词命中不了字面加号, 产物写实现拼接形态（如 topicURL）;
    ④ G005 全树扫描命中 `{{...}}` 占位符与其黑名单内的字面待办词, 产物措辞避开
- 失败回路:
  - G028 verdict=CONCERNS → 透传不修复: concerns 写入 step verdict 顶层 `concerns[]`
    + execution-report deviance，main agent 继续，里程碑汇报披露（SKILL.md 第三步）
- 产出:
  - `output/agents/{name}/v1/` 全部文件
  - `.agent-genesis/work/{name}/agent-creation/phase4-execution-report.md`
- schema: `schemas/execution-report.schema.yaml`
- gates: G024 + G028（exit_gates 由 executor 收尾一次执行, main agent 采信 verdict）

---

## Step 5: 静态验证

- step_id: `step-5-readiness-verification`
- mode: subagent
- SubAgent: readiness-verifier（agent 线验证器权威；skill-verifier 属 skill-foundry 线）
- prompt:
  - **知识注入清单（OPT-4）**: knowledge/agent-creation/verification-matrix.yaml、
    knowledge/agent-creation/agent-output-standard.yaml、
    knowledge/agent-creation/agent-classic-cases.yaml
  - **机检结论注入**: `.agent-genesis/work/{name}/gate-results/`（清单/路径注入——
    收尾 gate 集合 + 各步 G024 的 verdict JSON 位置；确定性规则由 verifier 采信，不重跑）
- 输入: `output/agents/{name}/v1/`
- 产出: `.agent-genesis/work/{name}/agent-creation/phase4-verification-report.md`
- schema: `schemas/readiness-report.schema.yaml`
- gates: G024（readiness 分数由 main agent 按报告人判 ≥58）

---

## Step 5.5: 评测 opt-in

- step_id: `step-5-5-runtime-eval-choice`（保留）
- mode: main_agent_direct
- **默认路径（无交互）**: Step 5 verdict=PASS 后 main agent 直接写 `step6-skipped.flag`
  进入里程碑，完成摘要显著标注「评测未运行，可随时 `/e2e-test-ci` 补跑」
- **opt-in 路径**: 用户在 6/8 步汇报时主动插话要求评测 → 写 `step6-decision.yaml`（run）
  → 进入 Step 6
- 决策记录: `.agent-genesis/work/{name}/agent-creation/step6-decision.yaml`（仅 Run 分支写；
  C1: 原名 phase5-runtime-eval.md，让给 6c 评估报告专用）

---

## Step 6: 产物黑盒测试（生成 + 执行）

- step_id: `step-6-product-validation`
- mode: subagent
- SubAgent: product-tester
- prompt:
  - `--acceptance-source {work_root}/clarified-agent-requirements.yaml`
  - `--product-path {output_root}/`
  - `--output-dir {work_root}/`
- 说明: 测试设计唯一来源 = 验收标准；设计意图文档（human-review/build-plan/matching-decision 等）经 forbidden_inputs 隔离（三方隔离: builder / tester / judge）
- 产出:
  - `.agent-genesis/work/{name}/agent-creation/e2e/`（golden case + suite.yaml）
  - `.agent-genesis/work/{name}/agent-creation/e2e-results/`
- schema: `schemas/test-case.schema.yaml` + `schemas/e2e-results.schema.yaml`
- gates: —（e2e 结果真实性由 product-tester 产出契约 + runtime-evaluator 盲评承担）

---

## Step 6c: 评分盲评

- step_id: `step-6c-runtime-evaluation`
- mode: subagent
- SubAgent: runtime-evaluator
- 输入: e2e-results/, clarified-agent-requirements.yaml (验收标准唯一来源)
- 产出: `.agent-genesis/work/{name}/agent-creation/phase5-runtime-eval.md`
- schema: `schemas/runtime-eval.schema.yaml`
- 失败回路 (C1): verdict=fail → `BACK_OFF_TO:step-4`，评估报告作为 step-4 修订输入（`revise_max_rounds: 1`）；
  修订轮耗尽仍 fail → `ESCALATE_STEP`（gate-block.md + AskUserQuestion: 接受产物 / 人工指导 / 终止）

---

## Milestone: "Agent 创建完成"

判定: **运行时主交付齐备** = `.agent-genesis/work/{name}/gate-results/g028-exit-sanity.json`
存在且顶层 `verdict` ∈ {PASS, CONCERNS}。文件缺失/verdict 非法 → GATE_PENDING →
gates.yaml 既有 `back_off_to: step-4` 回路，不自跑 G028。

包含步骤: `[0, 1, 2, 3, 3c, 4, 5, 5.5, 6, 6c]`

- full 车道交付汇报末尾补沉淀建议句（C9-6 固定措辞, `knowledge/golden/REFLUX.md` §4）:
  「本次构建的形态可沉淀为样例, 下次同类需求可直接套用」; 仅陈述不追问,
  用户确认 → REFLUX.md 档 1 流程。fast 车道不补（形态已源自样例）。

---

## Main Agent 必做（每 Step 后）

0. **pipeline 启动一次性 init**（step_complete fail-closed 要求 state 已存在, 拒绝静默新建）:
   ```bash
   bash scripts/main-agent-helpers.sh init ".agent-genesis/work/{name}" agent-creation
   ```
   state（orchestrator-state.yaml）与 gate-results/ 均在 `{name}` 层（00-conventions 产物分类表,
   两线同构; agent 线过程产物在 `agent-creation/` 子层, gates.yaml outputs 路径不变）

单入口调用（执行+决策+落盘一体；状态机契约见 `scripts/main-agent-helpers.sh`）:

```bash
bash scripts/main-agent-helpers.sh step_complete <step_id> "$WORK_DIR" "$OUTPUT_DIR" "$outputs_json"
```

- 输出单行 JSON: `gate_verdict` + `action`（+ `block_file`, 仅 ESCALATE_* 时）
- action 编排导航: `PROCEED` / `PROCEED_WITH_CONCERNS` → 下一 step；`RETRY` → 重跑同 step；
  `BACK_OFF:<step_id>` → 转向目标 step；`ESCALATE_STEP` / `ESCALATE_GLOBAL` → 按单入口
  已落盘的 `gate-block.md` 选项 AskUserQuestion
- 重试上限 / 回退目标 / 升级阈值唯一权威 = `phase/gates/gates.yaml` `triggers[].on_failure`
  （单入口按注册表决策落盘；`GATE_PENDING` 绝不视为通过——verdict 未落盘须排查 gate 执行）
- pipeline 收尾: `bash scripts/main-agent-helpers.sh status "$WORK_DIR" COMPLETED`

Circuit breaker: `pipeline_retry_budget=5` (整 pipeline 总 retry 限制, 超限单入口输出 ESCALATE_GLOBAL)
