# Phase 执行指南 — AgentGenesis SOP

> 加载策略: L2 — Phase 执行时按需 Read
> 适用: 所有 pipeline（agent-creation / create-skill / optimize-skill）
> 来源: 收敛自 planner-agent.md、reviewer-agent.md、skill-creation-guide.yaml、multiagent-decision-guide.yaml

---

## Phase 0: 需求澄清

> 适用 pipeline: agent-creation | create-skill | optimize-skill
> 执行者: Main Agent（直接执行，不 spawn SubAgent）
> 核心 Skill: requirement-clarifier（v0.18, `skills/requirement-clarifier/SKILL.md`; 旧名 agent-requirement-clarifier, 双 mode 派发）
> 编排文件: `phase/phase0-clarify.md`

### 第一步：判定是否进入

```
INTENT DETECTION 完成
  ├── confidence ≥ 80 且需求完整清晰（无模糊词汇） → SKIP Phase 0，直接 Phase 1
  ├── confidence < 80 或检测到模糊词汇 → 进入 Phase 0
  └── 用户显式触发 /clarify → 强制进入 Phase 0
```

### 第二步：分析需求缺口

1. Read `skills/requirement-clarifier/SKILL.md` 加载需求澄清行为指引（v0.18 起; 旧名 agent-requirement-clarifier）
2. 根据 pipeline_mode 选择决策树：
   - agent-creation → 6 节点（Role → I/O → Knowledge → Interaction → Safety → Constraints）
   - create-skill → 5 节点（Operation Mode → Knowledge Base → Deterministic Ops → I/O Format → Trigger）
   - optimize-skill → 6 节点（CODE-FIRST: Read 源码 + git log → Symptoms → Recent Changes → Expected vs Actual → Context → Boundary）
3. 逐节点判定 PASS/GAP，对每个 GAP 生成问题 + 推荐答案 + 重要性说明
4. 写入 `work/{name}/phase0-question-queue.yaml`

### 第三步：逐题交互（需求澄清核心循环）

- 一次只问一个问题
- 每题必须带推荐答案
- 使用 AskUserQuestion 工具，三选项：推荐方案 / 我改一下 / 先跳过
- 不催促用户，不替用户做决定

### 第四步：汇总澄清结果

生成 `work/{name}/phase0-clarified-requirements.yaml`：
- `original`: 用户原始需求
- `decision_tree`: 所有节点的 PASS/GAP_RESOLVED/UNCERTAIN 状态
- `clarified_requirement`: 拼接后的完整需求描述

### 第五步：判定闭环

- [ ] 所有 PASS 节点有明确的原文引用依据
- [ ] 所有 GAP 节点已转为 GAP_RESOLVED 或标注 UNCERTAIN
- [ ] UNCERTAIN 节点 ≤ 2 个
- [ ] 无循环依赖残留
- [ ] clarified-requirements.yaml 已写入 work/ 目录

### 输出什么

| pipeline | 输出文件 |
|----------|---------|
| 所有 pipeline | `work/{name}/phase0-question-queue.yaml` |
| 所有 pipeline | `work/{name}/phase0-clarified-requirements.yaml` |

### 失败怎么办

| 情况 | 处理 |
|------|------|
| UNCERTAIN 节点 > 2 | 继续追问，最多追加 2 轮 |
| 用户要求跳过 | 标注剩余节点为 UNCERTAIN，PASS → PHASE_1 |
| 用户要求终止 | FAIL → IDLE，等待用户补充信息 |

### 与 Phase 1 的衔接

Main Agent 向 Phase 1 planner-agent prompt 中传递：
- `clarified_requirement` 替代原始 `$ARGUMENTS`
- `decision_tree` 状态：UNCERTAIN 节点保持灵活性，GAP_RESOLVED 节点视为硬约束

---

## Phase 1: 需求分析/设计

> 适用 pipeline: agent-creation | create-skill | optimize-skill
> 执行者: planner-agent (mode=create/optimize) 或 对应 domain planner

### 第一步：读什么

| 文件 | 用途 |
|------|------|
| `knowledge/shared/cascading-matcher.yaml` | 三级级联匹配流程（MN 判定 → 子集过滤 → 精细匹配） |
| `knowledge/shared/pattern-catalog.yaml` | 设计模式目录（27 模式定义、级联倾向、硬约束） |
| `knowledge/agent-creation/pattern-matcher.yaml` | 各子维度 indicator 匹配规则 |
| `knowledge/shared/problem-diagnoser.yaml` | 问题模式库（仅 optimize-skill 模式） |
| pipeline 专属 guide: skill-creation-guide.yaml / multiagent-decision-guide.yaml | 领域设计指南 |

### 第二步：做什么

**所有 pipeline 共通的三级匹配流程：**

1. **Tier 0 — 任务性质判定**: 读取 cascading-matcher.yaml，按 judgment_questions 依次判定 MN-Exploratory / MN-Deterministic / MN-Hybrid
2. **Tier 1 — 子集过滤**: 根据 Tier 0 结果，从 cascade_action 中选择候选模式子集（8-12 个）
3. **Tier 2 — 子域内精细匹配**: 仅在 Tier 1 子集内执行 pattern-matcher.yaml 的 indicator 匹配
4. **硬约束校验**: 检查 cascading-matcher.yaml 中 hard_constraints 的 6 项约束（HC-01 至 HC-06）
5. **生成 decision log**: 按 decision_log_integration 规范输出 matching-decision-log.yaml

**pipeline 专属步骤：**

| pipeline | 额外步骤 |
|----------|---------|
| agent-creation | 交叉维度校验（pattern_relationships 中的 tends_to_imply / incompatible_with）、构建类型决策（单Agent vs Multi-Agent）、架构意图分析（L2/L3 分层、SubAgent 拓扑） |
| create-skill | 操作模式分析（Q1-Q4: iterates_and_judges / fetch_filter_rank / transform / record_report）、粒度决策（G1 多 Skill / G2 单 Skill）、去重检查（与已有 Skill 名称+描述比对）、Description 公式生成（SF-6） |
| optimize-skill | 6 维诊断（Design Form 优先: DF-M1~M4 → 维度 1-4 → 维度 6 Global Context）、优先级排序、边界判定（Skill 内 vs 超出 Skill 范围）、升级报告生成（如根因超出 Skill 范围） |

### 输出什么

| pipeline | 输出文件 |
|----------|---------|
| agent-creation | `work/{name}/agent-creation/phase1-matching-decision.md` |
| create-skill | `work/{name}/create-skill/phase1-skill-design.md` |
| optimize-skill | `work/{name}/optimize-skill/phase1-diagnosis-report.md` |
| 所有 pipeline | `work/{name}/matching-decision-log.yaml`（含 tier_0/1/2 结果） |

### 失败怎么办

| 情况 | 处理 |
|------|------|
| MN 判定 confidence < 60 | IH2 追问（2-5 个聚焦问题），不猜测 |
| 子维度互斥冲突 | 记录冲突点，进入 PLAN_MODE 让用户裁决 |
| pattern-matcher.yaml 不可读 | 终止，REPORT_TO_USER |
| optimize-skill: 目标 SKILL.md 不存在 | 终止，报告用户路径错误 |
| optimize-skill: ≥3 维无法判定 | 要求用户提供更多执行日志 |
| optimize-skill: 边界判定"完全超出 Skill 范围" | 输出 Agent 优化建议报告，终止当前 pipeline |

---

## Phase 2: 审查

> 适用 pipeline: agent-creation | create-skill | optimize-skill
> 执行者: reviewer-agent (mode=create/optimize) 或 对应 domain reviewer

### 第一步：读什么

| 文件 | 用途 |
|------|------|
| Phase 1 输出文件 | 待审查的设计文档 |
| `knowledge/shared/cascading-matcher.yaml` | 硬约束校验（HC-01 至 HC-06） |
| `knowledge/shared/pattern-catalog.yaml` | 模式定义、互斥关系、范式预置组合 |
| blocker-check-result 文件 | Phase 1 阻断检查结果（PASS/FAIL） |
| pipeline 专属 guide | 领域审查标准 |

### 第二步：做什么

1. **确认阻断检查通过**: 检查 blocker-check-result 文件。如 FAIL → 拒绝审查，直接 REWORK Phase 1
2. **完整性审查**: Phase 1 输出是否包含所有必需章节和决策点
3. **一致性审查**: 模式选择是否自洽、无互斥冲突、符合硬约束（HC-01 至 HC-06）
4. **去重审查**（仅 create-skill）: 是否已有相似 Skill，去重建议是否合理
5. **约束审查**: hard_constraints 是否全部满足
6. **生成审查报告**: 标注 CRITICAL/HIGH/MEDIUM/LOW 发现

### 输出什么

| pipeline | 输出文件 |
|----------|---------|
| agent-creation | `work/{name}/agent-creation/phase2-review.md` |
| create-skill | `work/{name}/create-skill/phase2-review.md` |
| optimize-skill | `work/{name}/optimize-skill/phase2-review.md` |

### 失败怎么办

| 情况 | 处理 |
|------|------|
| 阻断检查 FAIL | 拒绝审查，直接 REWORK Phase 1 |
| 发现 ≥3 个 CRITICAL | verdict=REJECTED，REPORT_TO_USER |
| 缺失关键章节 | 标注缺失项，反馈 Phase 1 补充 |
| REWORK 次数已达上限 | REPORT_TO_USER |

---

## Phase 3: 构建/装配

> 适用 pipeline: agent-creation | create-skill | optimize-skill
> 执行者: creator-agent / builder-agent

### 第一步：读什么

| 文件 | 用途 |
|------|------|
| APPROVED 的 Phase 1 设计文档 | 已通过审查和 Plan Mode 审批的方案 |
| `skills/agent-design-patterns/patterns/*.template.md` | 模式模板文件 |
| spec-assembler.yaml（agent-creation） | Spec 章节装配顺序 |
| 相关 L2 规则模板 | L2-execution-rules / L2-data-flow / L2-validation 等模板 |

### 第二步：做什么

1. **验证审批状态**: 确认 design doc 状态 = APPROVED，非 APPROVED 则阻断
2. **填充模式模板**: 按 matching_decision 中的 pattern_id 选择对应 template.md 并填充
3. **拼装完整 Spec**: 按 spec-assembler.yaml 的章节顺序组装 CLAUDE.md
4. **生成配套文件**: agents/、rules/、evaluation/、schemas/、knowledge/
5. **L2/L3 分层**: 按 architectural_intent 分析结果生成 rules/*.md 和 skills/*/SKILL.md
6. **输出文件清单**: 生成 file-manifest.md 记录所有产物

### 输出什么

| pipeline | 输出 |
|----------|------|
| agent-creation | `$AGENT_OUTPUT_ROOT/{name}/$VERSION/` 下的完整 Agent 项目 |
| create-skill | `$AGENT_OUTPUT_ROOT/skills/{name}/$VERSION/` 下的完整 Skill 项目 |
| optimize-skill | 更新后的 Skill 目录 + file-manifest.md |

### 失败怎么办

| 情况 | 处理 |
|------|------|
| 设计文档未 APPROVED | 阻断，不执行构建 |
| 模板文件缺失 | 终止，REPORT_TO_USER |
| Spec 拼装后章节缺失 | 返回补充模板 |

---

## Phase 4: 静态验证

> 适用 pipeline: agent-creation | create-skill | optimize-skill
> 执行者: verifier-agent

### 第一步：读什么

| 文件 | 用途 |
|------|------|
| `rules/shared/verification-checks.md` | 7 项静态验证检查方法 |
| 构建产物目录 | 待验证的输出文件 |
| Phase 1 设计文档 | 交叉验证（声明 vs 实际） |
| file-manifest.md | 产物清单 |

### 第二步：做什么

**agent-creation pipeline — 7 项检查：**

| # | 检查名称 | 核心方法 | 阻断级别 |
|---|---------|---------|:------:|
| 1 | 完整性检查 | find 枚举文件，CLAUDE.md 声明交叉校验 | CRITICAL |
| 2 | 格式检查 | YAML 解析、章节标题 grep、占位符检测 | CRITICAL |
| 3 | 引用检查 | 工具/Skill 白名单匹配、路径提取 | HIGH |
| 4 | Schema 合法性 | JSON/YAML Schema 解析、实体-Schema 属性比对 | CRITICAL |
| 5 | 流转闭合 | 实体表解析、Producer/Consumer 图、悬空检测 | CRITICAL |
| 6 | 约束自洽 | CD3-K 交叉、Safety-Role 关键词重叠 | HIGH |
| 7 | 加载策略一致性 | L2 决策→rules/ 文件、L3 决策→Skill 声明、内容质量 | HIGH |

**create-skill / optimize-skill pipeline — Skill 适配验证：**

> SK-S1/S2/S3 执行面已脚本化（G028 module.skill.static + g005, 确定性收敛重构 2.1/2.2）
> ——verifier LLM 采信机检 verdicts, 不重跑; 定义唯一权威见 verification-checks.md
> Skill 验证节。SK-S4 与语义四项（S8/S9/S10）留 LLM。

| 检查 | 内容 | 阻断级别 |
|------|------|:------:|
| SK-S1 | SKILL.md 结构完整性（文件存在 + YAML frontmatter + ≥50 行）——机检 | CRITICAL |
| SK-S2 | 引用闭合性（references/*.md 存在 + scripts/*.sh bash -n + 无绝对路径）——机检 | CRITICAL |
| SK-S3 | 无占位符残留（无 TODO/TBD/FIXME/{{}}）——机检（g005） | CRITICAL |
| SK-S4 | 逻辑一致性（步骤间 I/O 闭合/无矛盾指令）——语义, LLM（原"语法合法性"已并入 SK-S1 机检的 frontmatter 解析检查） | CRITICAL |

### 输出什么

| pipeline | 输出文件 |
|----------|---------|
| agent-creation | `work/{name}/agent-creation/phase4-verification-report.md` |
| create-skill | `work/{name}/create-skill/phase4-verification-report.md` |
| optimize-skill | `work/{name}/optimize-skill/phase4-verification-report.md` |

### 失败怎么办

| 情况 | 处理 |
|------|------|
| CRITICAL 项失败 | AUTO_FIX（≤3 轮），修复后重验证 |
| AUTO_FIX 超限 | REPORT_TO_USER |
| HIGH 项失败 | 记录，尝试 AUTO_FIX |

---

## Phase 5: 运行时评估

> 适用 pipeline: agent-creation | create-skill | optimize-skill
> 执行者: evaluator-agent（盲评原则）

### 第一步：读什么

| 文件 | 用途 |
|------|------|
| 构建产物目录 | 待评估的 Agent/Skill |
| `evaluation/pass-criteria.md` | 通过标准 |
| test task YAML | 运行时测试任务定义 |

### 第二步：做什么

1. **构造测试任务**: 根据目标 Agent/Skill 的职责设计实际执行场景
2. **执行评估**: 4 维度评分（correctness / completeness / format / actionability）
3. **计算加权总分**: 各维度按权重计算
4. **生成评估报告**: 含 verdict、分项评分、改进建议

### 输出什么

| pipeline | 输出文件 |
|----------|---------|
| agent-creation | `work/{name}/agent-creation/phase5-runtime-eval.md` |
| create-skill | `work/{name}/create-skill/phase5-runtime-eval.md` |
| optimize-skill | `work/{name}/optimize-skill/phase5-runtime-eval.md` |

### 失败怎么办

| 情况 | 处理 |
|------|------|
| verdict=FAIL + REVISE 轮次 < 2 | REVISE → 反馈传回 Phase 1 重设计 |
| verdict=FAIL + REVISE 轮次 ≥ 2 | REPORT_TO_USER |
| 加权总分 ≥ 3.5 但 correctness < 3.0 | verdict=FAIL，进入 REVISE |
