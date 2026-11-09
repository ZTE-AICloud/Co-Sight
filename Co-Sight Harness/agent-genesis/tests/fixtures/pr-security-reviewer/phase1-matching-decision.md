---
pipeline: agent-creation
decision_id: pr-security-reviewer-20261005T0343Z
timestamp: "2026-10-05T03:43:00Z"
mn_type: deterministic
selected_patterns: [W1, G1, K1, DT1, DF1, IH1, IT1, CD1, CD2]
rejected:
  - {pattern_id: W2, reason: "无入口分流需求——所有 PR diff 走同一安全扫描流程"}
  - {pattern_id: W3, reason: "扫描维度并行已由 multi_agent 拓扑(W1_stage_parallel)承载，顶层分解仍是 W1 阶段序；无归约式汇总结构"}
  - {pattern_id: W4, reason: "扫描步骤构建时已知（密钥/注入/配置三维度），非运行时动态派生"}
  - {pattern_id: W5, reason: "MN-Deterministic 一致性约束：不得选 W5 自适应拓扑"}
  - {pattern_id: SM1, reason: "执行路径固定，无状态回溯场景"}
  - {pattern_id: K2, reason: "clarified-requirements knowledge_sources[] 显式声明 K1（C4 证据），无特定权威文档"}
  - {pattern_id: K3, reason: "知识量小（通用安全常识），无需检索 Top-K"}
  - {pattern_id: K4, reason: "无结构化外部规则表；判定标准内嵌于各扫描器职责"}
  - {pattern_id: IH2, reason: "输入为完整 diff，IH1 语义成立；Step 1 澄清已闭环"}
  - {pattern_id: IH3, reason: "CLI 批处理场景，用户要求提交即出结果，无方案审批节点"}
  - {pattern_id: IV1, reason: "单 PR <3 分钟短流程，1-2 阶段，IV1 属过度设计"}
  - {pattern_id: CD3, reason: "无外部权威知识域边界需求；误报控制由 G1 独立复核承担"}
  - {pattern_id: DP1, reason: "发现含位置/证据属输入内引用，非跨步骤溯源审计需求"}
  - {pattern_id: DT2, reason: "无横向共享状态；数据单向链式传递"}
build_type: {type: multi_agent, topology: W1_stage_parallel}
---

# Matching Decision v2 — pr-security-reviewer

## Tier 0: 任务性质判定

**MN-Deterministic**（confidence: high）

判定依据：catalog 类别0 典型场景原文命中——"规范检查：'每次收到PR diff，按安全规范检查并输出报告'"。
相同 diff + 相同扫描规则 → 输出可验证（planted 漏洞检出率可度量）；步骤可在开始前完整列举；
知识来源为通用安全常识（knowledge_sources 显式声明 K1）。无"先发现后执行"分段结构，非 Hybrid。

## Tier 1: 子集过滤

cascade_action[MN-Deterministic] = [W1, W2, K2, K4, IH1, IT1-Optional, DT1, G1, DF1, CD1, CD2]
全部 Tier 2 选中模式均 ∈ 子集（cascade_aligned: true），无 override。

## Tier 2: 精细匹配决策表

| 子维度 | 选中 | confidence | rationale（引用需求信号） |
|--------|------|:---:|------|
| 工作流-分解 | **W1** | high | 需求声明 fixed steps："读取 diff → 按安全维度检查 → critical 问题输出"，顺序依赖明确（normal_flow） |
| 质量门禁 | **G1** | high | success_metrics 要求 planted 检出率 ≥90%，质量敏感；task_mode(verification_validation) 推荐组合含 G1；critical 判定需独立复核防误报 |
| 知识 | **K1** | high | C4 显式证据：clarified-requirements knowledge_sources[] 声明 `{type: K1, trust_level: 参考}`，无外部文档 |
| 数据-拓扑 | **DT1** | high | diff → 扫描发现 → 复核 → 报告，单向链式（DT1 typical_indicators 命中） |
| 数据-格式 | **DF1** | high | 每条发现必须含"维度/位置/证据片段/修复建议"四字段，结构化下游可消费，需 Schema 校验阻断不合规输出 |
| 交互-人机 | **IH1** | high | "接收 PR git diff → 输出快报"函数式批处理；exception_flow 要求失败即退出，无中间确认 |
| 交互-工具策略 | **IT1-Optional** | high | 核心能力为 LLM 静态文本分析，工具仅辅助（读文件）；非"没有工具会出错"场景 |
| 约束-域模板 | **CD1** | high | exception_flow："diff 过大或格式无法解析 → 明确报错并退出"——输入门禁语义 |
| 约束-域模板 | **CD2** | high | quality.security："审查 Agent 自身不执行被审代码，只做静态文本分析"——Safety-First 典型信号 |

**与 task-mode-pattern-mapping 交叉验证**：verification_validation 推荐 `G1 + WF6 + DF1 + CD1`。
命中 G1/DF1/CD1。偏离项 WF6（Circuit-Breaker）：WF6 属 WF 扩展参考、不在 27 模式 catalog 内（选中将触发 G017 L2 FAIL），熔断语义由编排层 retry budget（pipeline_retry_budget: 5）覆盖——标注偏离原因，不视为缺口。

## 未选中（rejected 汇总）

见 frontmatter `rejected[]`（14 项，均含理由）。补充说明：WF4/WF5/WF6/WF7 为 WF 扩展参考 ID，不在 27 模式 catalog 内，不参与 rejected 结构化枚举，仅在此注明未选原因（无辩论/契约锁定/熔断回流需求）。

## 硬约束校验（HC-01 ~ HC-06）

| 约束 | 状态 | 说明 |
|------|:----:|------|
| HC-01 | PASS | 未声明 CD3，无 K2/K3/K4 配对义务 |
| HC-02 | PASS | 未选 E1/E2/E3 |
| HC-03 | PASS | 未选 W5 |
| HC-04 | PASS | MN-Deterministic，无 phases 义务 |
| HC-05 | PASS | 未选 E2 |
| HC-06 | PASS | 顶层分解唯一（W1）；无互斥模式共存 |

一致性检查：MN-Deterministic 未选 W4/W5/SM1 ✓。

## Q1-Q6 判定

| 问题 | 答案 |
|------|------|
| Q1 可复用→Skill | none（skills[]=0，rationale 见结构决策） |
| Q2 质量门禁 | G1（独立 Reviewer SubAgent 复核 critical 判定） |
| Q3 独立评审 | G1 的 Reviewer SubAgent（security-reviewer） |
| Q4 多Agent触发 | S1（独立安全扫描维度 ≥2）+ S2（扫描×复核博弈对） |
| Q5 任务类别 | multi_file_analysis（diff 可多文件） |
| Q6 并行性 | parallel（三扫描器同阶段并行，复核阶段串行） |

## 结构决策（build_type_decision）

```yaml
type: multi_agent
topology: W1_stage_parallel
subagents:
  - role: secret-scanner
    split_trigger: S1
    knowledge_budget_lines: 150
    isolation_point: "forbidden_inputs: 其他扫描器输出、reviewer 结论——只读原始 diff"
  - role: injection-scanner
    split_trigger: S1
    knowledge_budget_lines: 150
    isolation_point: "forbidden_inputs: 其他扫描器输出、reviewer 结论——只读原始 diff"
  - role: security-reviewer
    split_trigger: S2
    knowledge_budget_lines: 200
    isolation_point: "forbidden_inputs: 原始需求/设计文档；独立复核扫描发现，不与扫描器共享中间推理"
skills: []
```

| role | split_trigger | knowledge_budget_lines | isolation_point |
|------|---------------|------------------------|-----------------|
| secret-scanner | S1 | 150 | forbidden_inputs: 其他扫描器输出、reviewer 结论——只读原始 diff |
| injection-scanner | S1 | 150 | forbidden_inputs: 其他扫描器输出、reviewer 结论——只读原始 diff |
| security-reviewer | S2 | 200 | forbidden_inputs: 原始需求/设计文档；独立复核扫描发现，不与扫描器共享中间推理 |

**拆分判定**: S1 命中（密钥硬编码/注入/危险配置三维度相互独立、并行无读写冲突——harness-design-principles 校准基线即本 agent 形态）；
S2 命中（生成-复核博弈：扫描器产出 × reviewer 独立复核 critical 判定）。anti_trigger 未命中（维度间非字段级依赖，扫描器只读同一份 diff）。
**拓扑选择**: 子任务角色构建时已知 → decision_table 命中 W1_stage_parallel。
**skill 规划**: n=0。rationale: 三维扫描已以 SubAgent 形态内聚于本 agent，能力非跨 agent 可复用单元（无其他消费者）；触发条件与 agent 私有流程耦合，不满足 K1_reusable/K2_triggerable 任一 scope_trigger（YAGNI）。
**一致性**: topology 基础 W1 ∈ selected_patterns ✓（G017 M6 闭合）。

## 决策物化（role 级）

| pattern_id | 机制 | target_roles | verify_hint |
|-----------|------|-------------|-------------|
| W1 | 步骤序列表（读取diff→并行扫描→独立复核→结构化报告）进 workflow，步骤间 I/O 契约逐行声明 | workflow_step | phase/02-workflows/ 含 4 步及每步输入/输出 |
| G1 | 独立 Reviewer SubAgent（security-reviewer）+ 回压协议（critical 误判→打回扫描器修正→重审≤2轮） | executor_subagent, workflow_step | subagents 定义含双向 forbidden_inputs |
| K1 | 无外部知识加载声明：推理依赖 LLM 内嵌通用安全知识（free_form——K1 不在 materialization_hints，依据 catalog constraints 推导） | claude_md_section | CLAUDE.md 知识节声明 K1、无 knowledge/ 目录依赖 |
| DT1 | 步骤间文件传递契约：diff→findings.json→reviewed-findings→report | workflow_step | 数据流转图无悬空实体 |
| DF1 | schemas/security-findings.schema.json（维度/位置/证据/修复建议四必填字段）+ 校验步骤进 workflow 阻断不合规输出 | schema, workflow_step | schemas/ 含 schema 文件且 required 四字段 |
| IH1 | workflow 无审批节点声明 + 输入完整性前置校验（CD1 配合，缺失即阻断退出） | workflow_step | phase/02-workflows/ 无 human_approval 节点 |
| IT1 | CLAUDE.md 工具策略条款：工具为辅助，核心判定由 LLM 静态分析完成 | claude_md_section | CLAUDE.md 工具节声明 IT1-Optional 语义 |
| CD1 | 输入存在性前置检查步骤：diff 文件缺失/为空/超大小上限 → 明确报错非零退出 | workflow_step, script | 第一步为 input-check，异常路径有定义 |
| CD2 | CLAUDE.md 安全约束节：禁止执行被审代码、禁止写被审仓库、只读分析 + 写范围限定（仅报告文件） | claude_md_section, rule_file | CLAUDE.md Safety 节含禁止操作清单 |

## 置信度总评

整体 confidence: high。MN 判定有 catalog 原文场景直接命中；全部选中模式 cascade_aligned 无 override；
K1 选择有 knowledge_sources[] 显式证据（C4）；唯一偏离（WF6）已注明不可选原因与替代覆盖。
