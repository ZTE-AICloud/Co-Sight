---
name: skill-foundry
description: 统一 Skill 工厂（创建/优化/诊断三模式）。接收自然语言需求或目标 Skill 路径，经 8 步 Pipeline（方案或诊断→健全性检查→DC-002 审批→构建或增量修改→静态验证→可选黑盒测试与盲评）产出完整 Skill 工程或诊断报告。当用户请求创建新 Skill、优化/改进已有 Skill、或诊断 Skill 问题时触发。输入为 Skill 需求文本或目标 SKILL.md 路径，输出为 output/skills/{name}/v1/ 工程或 .agent-genesis/work/{name}/skill-foundry/ 诊断报告。
---

# Skill Foundry — Skill Pipeline 入口

## 渐进式加载约定
- L2（本文件）: mode 判定 + orchestration 逻辑, 保持精简
- L3（references/, 命中才 Read）:
  - `references/workflow.md` — Step 1-6c 详细编排（输入/产出 = 人读编排视图）
  - `references/workflow-fast.md` — fast 车道视图（Lane 判定 = fast 时才 Read, experimental）
  - 机检数据源: `phase/gates/gates.yaml` triggers[].outputs（step 产物落盘清单, G024 消费）
  — **注意路径**: gates.yaml 在插件根（`~/.claude/plugins/cache/...`）, 只读, 禁止写入

## 路径约定
- `work_root` = `.agent-genesis/work/{name}/skill-foundry/`
- `output_root` = `output/skills/{name}/v1/`
- 基准目录 = 用户 cwd（`$PWD`）; 插件根只用于读 knowledge/ 与 rules/, **禁止写入**

## Mode 判定（本入口唯一职责之一）

从用户输入判定 mode（语义理解, 非关键词匹配）:

| 用户典型表达 | mode |
|-------------|------|
| "帮我做一个 X Skill""新建/生成/创建 Skill""一个能力" | create |
| "优化/改进/增强这个 Skill" + 目标路径 | optimize |
| "排查/诊断/看看哪里有问题" + 目标路径（不要求修改） | diagnose |

- Goal（Create/Improve/Diagnose）或目标不明确 → 一次一个问题追问, 带推荐答案, 最多 2 个:
  1. "你是想创建新的, 还是优化/诊断已有的？"
  2. "目标 Skill 的路径是？（优化/诊断需要）"
- mode 与 {name}（kebab-case, 向用户确认）确定后代入路径模板; diagnose 无 {name} 时用目标 Skill 目录名

## 第 1.5 步：Lane 判定（experimental——详见 `references/workflow-fast.md` §Lane 判定节）

s0 澄清（create）/目标确认（optimize）后单点执行, 只增不改 full 车道任何行为（红线 R7）。
**前置层（v1.2 裁定, 两线一致）**: 澄清不清楚不作为路由依据——字段缺失/未收敛 →
回 s0 继续澄清, 不进入判定（不写 lane-decision）; 续跑不重进本节。

1. **非交互保障优先**: 不可交互上下文（selftest / e2e 管道 / headless / CI）→ 静默走 full,
   不询问; criteria.yaml 缺失/解析失败 → 同样静默 full
2. **T1 判定**（对照 `knowledge/fast-lane/criteria.yaml`, 输入 = clarified YAML 显式字段）:
   - create: skill_create 段单判据 `fast_path_hit`（v1.3 D-03, OR 三分支任一命中:
     light 单职责+知识内联/单文件 / template_form 标准形态 / sampled 池有实例包）——
     命中 → 直接 fast（D-04 不问询, 一行陈述告知, 留痕注明分支）; 全不命中 → 静默走 full
   - optimize: skill_optimize 段三条（点名 ≤2 / 无结构变更 / 目标静态可定位）——
     全过 → 直接 fast（D-04 不问询, 裁定 6; 用户显式拒绝 → 终止改手动）; 任一不过 →
     **不进 full optimize**（维护态不作 fallback, R6）——告知超范围项与去处
     （create 重建 / 手动）, 由用户选
3. **留痕**: 判定写 `.agent-genesis/work/{name}/fast-lane/lane-decision.yaml`（含
   decided_by; 走 full / 范围拦截也落盘）
4. **分道**: full → 原驱动循环; fast → fast 驱动节（下方）

## fast 驱动节（lane = fast 时替代驱动循环, 步骤详述 = workflow-fast.md）

Read `references/workflow-fast.md` 按对应 mode 驱动到尾:
- **create（step-sf1）**: init → Agent(fast-skill-builder --mode create) 单轮 → G024 →
  G028 直调（skill-build 档, 无 build-plan 不走 g025）→ 合并 verdict + step_complete →
  按 action 分叉（PASS → 交付汇报; FAIL → 修复轮一轮 → 再 FAIL 终止+失败报告三要素）
- **optimize（step-sf2, 安全三件不可裁——R6）**: init → **快照**（cp -r 目标 → fast-lane/snapshot/,
  点名清单落 change-list.txt）→ Agent(fast-skill-builder --mode optimize, 就地修订) →
  **check-delta-scope**（diff ⊆ 点名集; 越界即终止+快照恢复, 不走修复轮）→ G024 +
  **G028 后测**（skill-verify 档）→ 合并 verdict + step_complete → 分叉（修复轮仅修
  G028/自报 FAIL 项）
- 交付汇报四要素: 模式明示 / 质量门禁提示（concerns 语义转述）/ 评测未运行 /
  产物位置（optimize 另含 delta 摘要与快照位置）。fast 车道不走 DC-002。

## 驱动循环

Read `references/workflow.md`, 对 Step 1-6c 逐个驱动（diagnose mode 仅 Step 1-2; Step 6a/6b/6c 需 Step 5.5 用户选 Run）:

1. Read workflow.md 中本 Step 章节 → 按「输入」字段确认上游产物存在 → 缺失则按该 Step「失败回路」回退
2. 按 mode 调度:
   - `main_agent` / `main_agent_direct` → 直接执行（Bash / AskUserQuestion）
   - `subagent:<name>` → Agent({subagent_type}, **只传 prompt 参数**: `--mode` / `--output-dir` 等)
3. 每 Step 后跑 gate 并落盘 verdict → **step_complete 单入口决策**（执行+决策+落盘一体,
   完整契约见 workflow.md §Main Agent 必做）:
   - pipeline 启动先 init（step_complete fail-closed 要求 state 已存在）:
     `bash scripts/main-agent-helpers.sh init ".agent-genesis/work/{name}" skill-foundry`
   - G024 落盘检查（机检权威 = gates.yaml triggers[step_id].outputs）:
     ```bash
     echo "{\"step_id\": \"<step_id>\", \"name\": \"{name}\", \"root\": \"$PWD\"}" | bash scripts/gates/g024-output-exists.sh
     ```
     `--root $PWD` 必须显式传（防 cd 后 cwd 漂移）; FAIL-CLOSED: outputs 清单缺失/为空即
     FAIL, 绝不空转恒 PASS
   - 合并该 step 全部 gate 结果写 `.agent-genesis/work/{name}/gate-results/<step_id>.json`
     （verdict 取最坏值: FAIL > CONCERNS > PASS; state 与 gate-results 均在 `{name}` 层）
   - 单入口:
     ```bash
     bash scripts/main-agent-helpers.sh step_complete <step_id> ".agent-genesis/work/{name}" "$OUTPUT_DIR" "$outputs_json"
     ```
     按输出 action 导航（PROCEED/RETRY/BACK_OFF/ESCALATE_*; GATE_PENDING 绝不视为通过）;
     重试上限/回退目标唯一权威 = gates.yaml triggers[].on_failure

**[P10.5 拉起规则] 分发 SubAgent 时只传 prompt 参数, 不传输入文件列表** ——
SubAgent 输入清单以 `agents/<name>.md`「输入」段为执行权威。

## 里程碑

全部 Step 完成 → 按 mode 执行 workflow.md §Milestone 的**内联条件**判定
（**不调 g021** —— 它是 agent 线里程碑脚本, v3.2 修复）。满足后汇报:
- create/optimize: 产物位置 + 目录结构 + 使用方式
- diagnose: 诊断结论摘要 + 报告路径（不修改目标 Skill）
- **create 汇报末尾追加沉淀建议句**（固定措辞, 权威 = knowledge/golden/REFLUX.md §4）:
  「本次构建的形态可沉淀为样例, 下次同类需求可直接套用」——仅陈述不追问;
  用户确认后按 REFLUX.md 档 1 流程启动沉淀。fast 车道产物形态已源自样例, 不补此句。

**评测未运行提示行（OPT-3）**: optimize 模式 Step 5.5 默认不询问直接 Skip，
完成摘要标注「评测未运行，可随时补跑」；create 模式保留询问（默认 Run，E2E 是
新 Skill 唯一质量信号）。用户在任意汇报节点主动插话要求评测 → 写
`step6-decision.yaml`（run）进入 Step s6。

## 目标导向汇报（IV1）

每节点完成时渲染进度, 坐标是「距可用 Skill / 诊断结论」而非 step_id:

```
[2/8 → 可用 Skill] 方案已通过健全性检查: Q1-Q4 + G1/G2 决策齐（证据行号 12 处）
  下一步: 你的审批（DC-002, 预计 1 次确认）
  剩余: 审批 → 构建 → 静态验证
```

diagnose mode: `[1/2 → 诊断结论] 7 维诊断完成: 3 维 FAIL（Decomposition/Design Form/Logic）`

## 异常处理
- 整 pipeline retry 累计 ≤ 5（circuit_breaker, 状态在 `.agent-genesis/work/{name}/orchestrator-state.yaml`）
- human_approval 节点（DC-002）暂停等待用户, 超时 24h 标记 BLOCKED
- 断点恢复: 不重复调度 orchestrator-state 中已 verdict=PASS 的 Step
