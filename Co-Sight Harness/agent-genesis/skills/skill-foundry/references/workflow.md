# Skill Foundry — 统一 Skill Pipeline 编排视图

> 互指: fast 车道（experimental）人读视图 = `references/workflow-fast.md`（车道 4 create /
> 车道 6 optimize; 分道判定在 SKILL.md §第 1.5 步）——本文件仅 full 车道, 两视图互为唯一对照
> 适用 mode: create（创建）/ optimize（优化）/ diagnose（仅诊断）
> diagnose = optimize 前缀: Step 1-2 完成后提前交付诊断结论, 不修改目标 Skill
> 机检权威: `phase/gates/gates.yaml` triggers[].outputs（G024 消费）
> 执行权威: `agents/*.md` 各 SubAgent「输入/产出」段（P10.5; 本文件「输入」仅人读编排视图）
> Gate 触发器共 11 条 = 9 逻辑步 (Step 0 + Step 1-6c) + step-s1/step-s4 按 mode 分叉
> （G024 全量存在语义不支持产物二选一, v3.2 修订）

---

## 路径约定

- `work_root` = `.agent-genesis/work/{name}/skill-foundry/`
- `output_root` = `output/skills/{name}/v1/`
- 基准目录 = 用户 cwd（`$PWD`）; 插件根只用于读 knowledge/ 与 rules/, **禁止写入**

---

## Step 0: 需求澄清（requirement-clarifier, v0.18 新, 仅 create 模式）

- step_id: `step-s0-clarify`
- mode: skill
- Skill: requirement-clarifier（`skills/requirement-clarifier/SKILL.md`）— prompt 传 `--mode skill` + 用户需求文本
- 触发条件: 仅 create 模式; optimize / diagnose 已有目标 SKILL.md 路径, 无澄清环节
- 输入（人读视图）: 用户需求文本
- 产出: `work_root/clarified-skill-requirements.yaml`（schema: `skills/requirement-clarifier/references/schemas/clarified-skill.schema.yaml`）
- 后续: Main Agent 按 DC-010 通道建议 + 用户确认后, 进入 Step 1（prompt 附 `clarified-skill-requirements.yaml` 路径）
- gates: G024
- 失败回路: BLOCKED (AskUserQuestion 不可用 / 模式未传 / 阶段1未达 confidence ≥ 70) → ESCALATE
- optimize / diagnose 模式: **跳过** step-s0, 直接进 Step 1

---

## Step 1: Skill 方案 / 诊断（skill-planner）

- step_id: `step-s1-skill-plan`
- mode: subagent
- SubAgent: skill-planner（prompt 传 `--mode create|optimize|diagnose` 及对应参数）
- 输入（人读视图）:
  - create: 用户需求文本 + 已有 Skill 清单（planner 自行 Glob 去重比对）
  - optimize / diagnose: 目标 SKILL.md 路径 + 用户反馈
- 产出（mode 二选一）:
  - create → `work_root/phase1-skill-design.md`
  - optimize / diagnose → `work_root/phase1-diagnosis-report.md`
- gates: G024（optimize/diagnose 前置「目标 skill 存在」由 skill-planner 自身承担）
- G024 调用 step_id: create → `step-s1-skill-plan-create`; optimize/diagnose → `step-s1-skill-plan-optimize`
- 失败回路: retry ≤ 2（原地重跑 planner）→ 超限 ESCALATE

---

## Step 2: 方案健全性检查（G027, main_agent_direct）

- step_id: `step-s2-plan-sanity`
- mode: main_agent_direct（不调 SubAgent, 确定性检查替代原 LLM reviewer, 同 agent 线 G017 先例）
- 动作:
  - create: 校验 phase1-skill-design.md — frontmatter 决策字段齐全、每个 Q/G 决策引用 guide.yaml 条目、无占位符
  - optimize/diagnose: 校验 phase1-diagnosis-report.md — 7 维摘要表齐全、每个 FAIL 有目标 SKILL.md 行号证据、边界判定结论存在
- gates: G027（`scripts/gates/g027-plan-sanity.sh`,
  stdin `{"mode", "report_path", "source_path"}`；optimize/diagnose 时 `source_path` 必须传目标 Skill 的
  SKILL.md 路径——G027 据此校验 `SKILL.md:<N>` 行号证据真实存在（v0.18 修订补实现，伪造行号 FAIL），
  缺省则降级 CONCERNS 不阻断）
- 产出: `work_root/plan-sanity-result.yaml`（G027 verdict + 明细; v3 方案原文写 phase2-review.md,
  v0.18 实施定名为 plan-sanity-result.yaml——Deterministic gate 的原始 verdict 即终审格式记录,
  不再包装一层 LLM 审查报告壳; step-s2 trigger outputs 以本文件名为准）
- 失败回路: FAIL → 回退 Step 1（retry ≤ 1）→ 超限 ESCALATE
- diagnose mode 到此终止: 交付诊断报告（边界判定为"完全超出"时附 Agent 优化建议报告段）+ plan-sanity-result.yaml, 跳过 Step 3-6c

---

## Step 3: DC-002 方案审批（human_approval）

- step_id: `step-s3-dc002-approval`
- mode: human_approval (DC-002)
- 4 步结构化: 文件清单（≥10 行）+ 风险（≥2）+ spot-check（≥3）+ yes_no
- 产出: `work_root/plan-approval-decision.md`
- 失败回路: 用户 reject → 回退 Step 1; 超时 24h → BLOCKED, AskUserQuestion

---

## Step 4: 构建 / 增量修改（skill-builder）

- step_id: `step-s4-skill-build`
- mode: subagent
- SubAgent: skill-builder（prompt 传 `--mode` + `--output-dir output/skills/{name}/v1/` +
  `PLUGIN_ROOT` 插件根绝对路径——builder 内 g026 命令模板 `{PLUGIN_ROOT}` 占位由该值字面替换）
- 输入（人读视图）:
  - create: `work_root/phase1-skill-design.md`（已批准）
  - optimize: `work_root/phase1-diagnosis-report.md`（已批准）+ 目标 Skill 目录
- 产出:
  - create → `output_root/`（完整 Skill 工程）
  - optimize → `output_root/`（修改后）+ `work_root/delta-diff.md`（三段式 Diff 审计）
- gates: G024 + G028-exit-sanity（profile=skill-build）
- G024 调用 step_id: create → `step-s4-skill-build-create`; optimize → `step-s4-skill-build-optimize`
- 失败回路: 验证报告分数由 main agent 人判，前置修复回退见 Step 5; 构建本身 retry ≤ 2 → 超限 ESCALATE

---

## Step 5: 静态验证（skill-verifier）

- step_id: `step-s5-skill-verify`
- mode: subagent
- SubAgent: skill-verifier
- 输入（人读视图）: `output_root/`（optimize 追加 `work_root/delta-diff.md`）
- **机检结论注入**: `.agent-genesis/work/{name}/gate-results/`（清单/路径注入——
  step-s4 / step-s5 的 runner.exit verdict JSON 位置（profile=skill-build / skill-verify，
  含 module.skill.static 的 SK-S1/S2 与 g005 的 SK-S3 结论）；确定性规则由 skill-verifier
  采信，不重跑——2.2 采信改造，fail-closed 见其 prompt §Step 1）
- 产出: `work_root/phase4-verification-report.md`（含机读 failed_items[] 修复指令）
- gates: G024 + G028-exit-sanity（profile=skill-verify; 验证报告分数由 main agent 人判 ≥58）
- 失败回路: FAIL → 回退 Step 4（builder 消费 failed_items 逐项修复, 批内自修复 ≤3）→ 超限 ESCALATE

---

## Step 5.5: 评测选择（交互反转对齐, 提速方案 OPT-3; mode 相关语义保留）

- step_id: `step-s5-5-eval-choice`
- mode: main_agent_direct
- Run → 写 `work_root/step6-decision.yaml`; Skip → 写 `work_root/step6-skipped.flag`（两分支互斥, 不挂 G024）
- **对齐规则（OPT-3: 默认值即 Skip 的提问是纯 wall 洞, 不再询问; 默认值即 Run 的保留询问）**:

| mode | 行为 | 理由 |
|------|------|------|
| create | **保留 AskUserQuestion（默认 Run）** | 新 Skill 无原契约, E2E 是质量信号**唯一来源**（v0.18 O5 语义不变）——这是实质质量决策而非 wall 洞 |
| optimize | **不询问, 直接 Skip + 摘要标注「评测未运行, 可随时补跑」** | 已有原 Skill 契约作基线; e2e 是回归检测非质量信号; 用户已批准 delta-diff.md |
| diagnose | N/A | diagnose mode 早终止, 不进 Step 5.5 |

- create 模式写决策文件时附 mode 与推荐理由字段（人审可见）:
  ```yaml
  choice: run | skip
  mode: create | optimize
  default_recommended: true | false
  default_rationale: "<本 mode 的推荐理由>"
  decided_at: "<ISO8601>"
  ```

---

## Step 6: 产物黑盒测试（product-tester）

- step_id: `step-s6-product-validation`
- mode: subagent
- SubAgent: product-tester（prompt: `--acceptance-source <验收/原契约> --product-path output_root --output-dir work_root/`）
- 说明: 测试设计唯一来源 = 验收标准（create）/ 原 Skill 契约（optimize, 防"测不出回归"）; forbidden_inputs 追加设计文档
- 产出: `work_root/e2e/` + `work_root/e2e-results/`
- gates: G024（e2e 结果真实性由产出契约 + runtime-evaluator 盲评承担）
- 失败回路: retry ≤ 2 → 回退 Step 4

---

## Step 6c: 评分盲评（runtime-evaluator）

- step_id: `step-s6c-runtime-evaluation`
- mode: subagent
- SubAgent: runtime-evaluator
- 输入: `work_root/e2e-results/` + 验收标准（盲评, 不参与构建/测试过程）
- 产出: `work_root/phase5-runtime-eval.md`
- gates: G024
- 失败回路: retry ≤ 1 → 回退 Step 6

---

## Milestone: "Skill Foundry 完成"

**不在 skill 目标上调 g021**（其规则已内嵌 G028 agent-exit 档, 仅 agent 线使用）。
由入口 skill 按 mode 执行**内联条件**判定:

- create: `output_root/SKILL.md` 存在 + 验证报告分数人判 ≥58 + (e2e 结果存在或 step6-skipped.flag 存在)
- optimize: 同上 + `work_root/delta-diff.md` 存在 + phase4-verification-report.md 含"无回归"结论段
- diagnose: `work_root/phase1-diagnosis-report.md` 存在 + Step 2 健全性 PASS（提前终止, 无 DC/构建/验证）

全部满足 → 汇报产物位置与启动/使用方式。

- full 车道 create 交付汇报末尾补沉淀建议句（C9-6 固定措辞, `knowledge/golden/REFLUX.md` §4）:
  「本次构建的形态可沉淀为样例, 下次同类需求可直接套用」; 仅陈述不追问,
  用户确认 → REFLUX.md 档 1 流程。fast 车道不补（形态已源自样例）。

---

## Main Agent 必做

0. **pipeline 启动一次性 init**（step_complete fail-closed 要求 state 已存在, 拒绝静默新建）:
   ```bash
   bash scripts/main-agent-helpers.sh init ".agent-genesis/work/{name}" skill-foundry
   ```
   state（orchestrator-state.yaml）与 gate-results/ 均在 `{name}` 层（00-conventions 产物分类表,
   两线同构; skill 线过程产物在 `skill-foundry/` 子层, gates.yaml outputs 路径不变）
1. mode 判定与路径解析（见 `skills/skill-foundry/SKILL.md` §Mode 判定; 此处不重复）
2. 每 Step 执行后跑 gate 并**落盘 verdict**（落盘责任在主循环, 00-conventions 状态机节;
   单入口不执行 gate——verdict 先行, 30s 防呆等待超时即 GATE_PENDING）:
   - G024（全部 step, FAIL-CLOSED, `--root $PWD` 显式传）:
     ```bash
     echo "{\"step_id\": \"<step_id>\", \"name\": \"{name}\", \"root\": \"$PWD\"}" | bash {PLUGIN_ROOT}/scripts/gates/g024-output-exists.sh
     ```
     `{PLUGIN_ROOT}` = env-probe 已解析的插件根绝对路径，字面替换，禁止依赖 shell 环境变量
   - step-s2 另跑 G027（main_agent_direct, 见 §Step 2）; step-s4/s5 另有 runner.exit
     （G028 profile=skill-build/skill-verify, verdict 由 gate 执行方落盘同目录）
   - 合并该 step 全部 gate 结果写 `.agent-genesis/work/{name}/gate-results/<step_id>.json`
     （verdict 取最坏值: FAIL > CONCERNS > PASS）
3. **单入口决策**（执行+决策+落盘一体; 取代旧"手调 G024 后手读 verdict 人查失败回路"）:
   ```bash
   bash scripts/main-agent-helpers.sh step_complete <step_id> ".agent-genesis/work/{name}" "$OUTPUT_DIR" "$outputs_json"
   ```
   - 输出单行 JSON: `gate_verdict` + `action`（+ `block_file`, 仅 ESCALATE_* 时）
   - action 编排导航: `PROCEED` / `PROCEED_WITH_CONCERNS` → 下一 step；`RETRY` → 重跑同 step；
     `BACK_OFF:<step_id>` → 转向目标 step；`ESCALATE_STEP` / `ESCALATE_GLOBAL` → 按单入口
     已落盘的 `gate-block.md` 选项 AskUserQuestion（GATE_PENDING 绝不视为通过——verdict
     未落盘须排查 gate 执行, 不得跳步）
   - 重试上限 / 回退目标 / 升级阈值唯一权威 = `phase/gates/gates.yaml` `triggers[].on_failure`
     （单入口按注册表决策落盘）; step-s1 / step-s4 按 mode 选 `-create` / `-optimize` 触发器
   - pipeline 收尾: `bash scripts/main-agent-helpers.sh status ".agent-genesis/work/{name}" COMPLETED`
4. **P10.5 拉起规则**: 分发 SubAgent 只传 prompt 参数（--mode / --output-dir 等）,
   不传输入文件列表 —— SubAgent 输入清单以 `agents/<name>.md`「输入」段为执行权威
5. diagnose mode: Step 2 后立即终止并交付诊断结论, 不进入 DC-002
6. 整 pipeline retry 累计 ≤ 5（circuit_breaker, 状态在 `.agent-genesis/work/{name}/orchestrator-state.yaml`）
7. 断点恢复: 不重复调度 orchestrator-state 中已 verdict=PASS 的 Step
