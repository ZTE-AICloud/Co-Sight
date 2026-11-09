---
name: requirement-clarifier
description: 统一需求澄清器：诊断式需求访谈，agent-creation 与 skill-foundry 共享。按 mode 派发（agent / skill），每个 mode 走专属追问清单（不复制判定数值）。当 Step 1（agent 线）或 Step 0（skill-foundry create 模式）触发。输入为用户原始需求文本 + mode 标识，输出 clarified-{agent|skill}-requirements.yaml + DC-010 通道建议。
---

# Requirement Clarifier — 统一需求澄清器

## 触发条件
- agent-creation 流程: Step 1（skills/harness-create/references/workflow.md 步骤 1）
- skill-foundry 流程: Step 0（仅 create 模式; optimize / diagnose 不触发, 沿用原目标 Skill 路径）
- mode 标识由入口 skill 传 `--mode agent|skill`

## 渐进式披露约定
- L1（本文件, 命中触发）: name + description + mode 派发表
- L2（本文件, mode 命中后加载）: 共享访谈协议（对话风格 / 提问格式 / 完成状态 / DC-010 通道建议 / 通用阶段 1 资产探索 / 通用阶段 3 智能跳过+追问+逃生）
- L3（references/, mode 命中后才 Read）:
  - `references/workflow-agent.md` (agent 模式阶段 1-4 详尽流程 + 12 类任务模式)
  - `references/workflow-skill.md` (skill 模式阶段 1-4 详尽流程 + Q1-Q4 派发问题)
  - `references/skill-questions.md` (skill 模式访谈问题清单, 仅指指针, 不复制 guide.yaml 数值)
  - `references/schemas/clarified-agent.schema.yaml` (agent 模式输出 schema)
  - `references/schemas/clarified-skill.schema.yaml` (skill 模式输出 schema)
- **不进公共 `rules/` / `phase/` / `schemas/` 的本 Skill 私有资产**: 全部落在 `references/schemas/` 与 `references/` 内（满足硬约束 #3）

## Mode 派发表

| mode | L3 Read 清单 | 输出文件 | 输出 schema |
|------|--------------|---------|-------------|
| agent | workflow-agent.md + task-modes.md + schemas/clarified-agent.schema.yaml | .agent-genesis/work/{name}/agent-creation/clarified-agent-requirements.yaml | clarified-agent |
| skill | workflow-skill.md + skill-questions.md + schemas/clarified-skill.schema.yaml | .agent-genesis/work/{name}/skill-foundry/clarified-skill-requirements.yaml | clarified-skill |
| agent-optimize | workflow-agent-optimize.md + schemas/clarified-agent.schema.yaml（optimize 形态） | .agent-genesis/work/{name}/agent-creation/clarified-agent-requirements.yaml | clarified-agent |

> mode 由入口传 `--mode agent|skill|agent-optimize`; agent-optimize 为 FC 新增
> （fast 车道三输入形态分流, 主入口 = harness-create optimize 维度——派发协议见
> L3 workflow-agent-optimize.md）。

> **硬约束**: L2 SKILL.md 不得出现 mode 专属内容（K1-K4 / Q1-Q4 / task_mode / 12 类任务模式 / 知识资产等）。所有 mode 专属词汇只在 L3 references/ 中出现。
> 验收: `grep -E "K1|K2|K3|K4|Q1|Q2|Q3|Q4|task_mode" skills/requirement-clarifier/SKILL.md` 零命中

## 共享访谈协议（L2, 两 mode 通用）

### 对话风格
直接、具体、像工匠对话工匠。不说"优化""提升""增强"。说"这个 X 每天帮你省 2 小时"。说"这里不澄清的话, 生成的 Y 会用错字段名"。每句话都指向具体的产出、数字、文件。

### 提问格式

#### 工具解析
AskUserQuestion 对应两个运行时工具：宿主 MCP 变体（`mcp__*__AskUserQuestion`）或原生工具。优先使用 MCP 变体。如果工具列表中完全不出现 AskUserQuestion，本 Skill 被阻止——停止并报告 `BLOCKED — AskUserQuestion 不可用`。

#### 格式规范
每次 AskUserQuestion 是一个决策简报：

```
D<N> — <问题标题，一行>
场景: <一句话还原当前上下文>
通俗解释: <16岁能听懂的解释，2-3句，说明白利害关系>
选错的代价: <一句话讲清楚选错会怎样>
推荐: <选项>，因为 <一句话理由>
完整度: A=X/10，B=Y/10  （或: 注意: 选项性质不同，不打分）
优劣对比:
A) <选项名>（推荐）
  ✅ <优点 — 具体，≥40字>
  ❌ <缺点 — 诚实，≥40字>
B) <选项名>
  ✅ <优点>
  ❌ <缺点>
总结: <一句话概括你真正在权衡什么>
```

D 编号: 第一个问题从 D1 开始, 每题递增。推荐必须始终出现在一个选项上, 标注 `（推荐）`。

完整度: 选项覆盖度不同时用 `N/10` 打分。选项性质不同时标注 `注意: 选项性质不同, 不打分`。

**发出前自检:**
- [ ] D<N> 标题已写
- [ ] 通俗解释已写（含利害关系）
- [ ] 推荐已写, 有具体理由
- [ ] 完整度已打分 或 已标注"性质不同"
- [ ] （推荐）标注在一个选项上
- [ ] 总结行已写
- [ ] 确实在调工具, 不是写作文

### 完成状态协议

Skill 工作流结束时报告状态:
- **完成** — 有证据支撑。confidence ≥ 80, 所有关键维度已填满。
- **完成（有顾虑）** — 已完成, 列出顾虑（待澄清项、低置信度维度）。
- **阻止** — 无法继续; 说明阻碍和已尝试的方案。
- **缺上下文** — 信息不足; 准确说明缺什么。

### DC-010 通道建议（mode 感知）

输出 YAML 后, 按 mode 判定 DC-010 三项标准, 向 Main Agent 建议的展示通道, 写进 `dc010_channel` 字段（fast | full）:

| mode | 通道通过标准（全部满足 → fast） |
|------|-------------------------------|
| agent | confidence ≥ 70 / why/what/how/quality/acceptance_criteria 五维均非空 / blocked ≤ 1 |
| skill | confidence ≥ 70 / Q1-Q4 决策 + 触发场景 + 验收标准均非空 / blocked ≤ 1 |

任一不满足 → full, 并列出未过项（哪条标准、缺什么）。

Main Agent 最终以 DC-010 的判定为准——本字段只是建议, 供 AskUserQuestion 前预填。AskUserQuestion 结束后, Main Agent 把实际走的通道和逐项判定记入 orchestrator-state.yaml。

## 通用阶段 1: 上下文加载（两 mode 共用, 资产类型按 mode 参数化）

提问前先加载已知信息, 跳过已回答的问题。使用 Explore 内置 Agent 探索项目目录:

```
用 Explore Agent 扫描项目根目录:
1. 项目级文件: CLAUDE.md（项目名/自动化等级/约束）、README.md
2. 可复用资产:
   - agent 模式: skills/（已有 Skill）、rules/（已有规则）、agents/（角色模板）、knowledge/（知识库）
   - skill 模式: skills/（已有 Skill, 用于去重）、knowledge/（已发布 Skill 索引）
3. 会话历史:
   - agent 模式: work/ 目录下最新的 phase0-* 或 phase1-* 文件
   - skill 模式: work/ 目录下最新的 skill-foundry 阶段文件
4. 设计文档: design/ 目录（如有）
```

- 如果发现了可复用资产 → 输出: "关于这个项目, 我已经知道: ...（列出已有的 Skill/Rules/Knowledge）"
- 如果只发现项目元信息 → 简要输出项目名和约束
- 如果几乎为空 → 不输出, 不废话。在阶段 3 中询问用户是否有要复用的内容

模式专属的阶段 2-4 内容, 按 mode 派发表跳转到对应 L3 references/。

## 通用阶段 3: 澄清提问（两 mode 协议共享, 问题清单按 mode 派发）

**每次只问一个问题**。D1, D2, D3... 从对应 mode 的 L3 问题清单中选取。

### 智能跳过
用户之前的回答已覆盖后续问题时, 跳过不问。只问答案尚不明确的问题。

### 追问规则
用户给出模糊回答时, 追问一次要求具体化:
- "这个描述比较宽泛。能举一个具体例子吗？"
- "'做好了'是什么样？能给个数字吗？"
- "你提到<模糊词>，具体指什么？"

只追问一次。第二次回答仍模糊时, 标注为 `open_question`, `status: pending`, 继续下一个问题。不追第三次。

### 逃生通道
用户表示不耐烦时（"直接做吧""跳过问题"）:
- "理解。但这些问题是核心价值——跳过的话生成的 Y 可能不符合你的需求。我再问两个最关键的, 然后继续。"
- 选 2 个最关键未回答的问题, 问完进入阶段 4。
- 用户第二次拒绝时, 尊重决定——立即进入阶段 4。
- 仅当 ≥ 4 个核心维度已有具体答案时, 允许完全跳过。

## 通用阶段 4: 输出（两 mode 协议共享, 文件与 schema 按 mode 派发）

按 mode 派发表的输出文件 + schema 落盘。

`build_mode` 判定（两 mode 通用）:
- 阶段 1 发现已有完整配置 → `build_mode: incremental`
- 否则 → `build_mode: greenfield`

按完成状态协议报告状态。

## 失败回路
- AskUserQuestion 工具不可用 → 立即 `BLOCKED — AskUserQuestion 不可用`, 终止
- mode 参数缺失 → 立即 `BLOCKED — 必须传 --mode agent|skill`, 终止
- L3 references 缺失 → 立即 `BLOCKED — <L3 文件路径> 不存在`, 终止
- 用户三次拒绝回答同一问题 → 标注为 open_question, 跳过, 不阻断
