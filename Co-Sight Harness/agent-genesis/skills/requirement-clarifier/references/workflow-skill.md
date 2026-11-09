# Skill 模式 Workflow — Requirement Clarifier L3

> 加载者: skill mode 命中后由 L2 SKILL.md 引用
> 内容: skill 模式阶段 2-4 详尽协议
> 唯一权威: Q1-Q4 / G1-G2 / 4 个 mode / 400 行阈值 = `knowledge/skill/skill-creation-guide.yaml`（项目级, 不内联）
> 唯一权威: 问题访谈话术 = `references/skill-questions.md`（同包）
> 唯一权威: 输出 schema = `references/schemas/clarified-skill.schema.yaml`
> 防三重拷贝反模式: 本文件**不复制**任何 guide.yaml 数值, 仅引用 + 派发

## 阶段 2: Skill 模式分类（不复制 4 个 mode 判定）

内部对照 `knowledge/skill/skill-creation-guide.yaml` §1 Q1 的 4 个操作模式, 不直接问用户（与 agent 模式 D-Knowledge 强制追问不同——skill 模式分类由 skill-planner 在阶段 1 决策更准）。

**只在以下两种情况**主动问用户澄清模式:
1. 用户明确说"我不确定"且 skill-planner 自检后无主键
2. 跨多 mode 杂交（如"分析+排序+报告"），需要用户确认主从

## 阶段 2.5: 知识资产探测（不复制 guide.yaml Q2 必要性论证）

向用户提 3 类资产的访谈问题（具体问题见 `references/skill-questions.md` §Q2）。本文件不复制必要性论证表, 由 skill-planner 阶段 1 用 `guide.yaml §1 Q2` 决策。

**不强制追问**（与 agent 模式 D-Knowledge 不同）——如果用户说"我也不知道需要什么", 直接标 `knowledge_assets: {references: [], scripts: [], templates: []}` + open_question, 不阻塞。

## 阶段 3: 澄清提问（按 references/skill-questions.md 顺序）

D1 → D2 → D3 → D4 → G1 → 去重, 共 5+1 = 6 主题（具体话术与 SKILL.md L2 协议见 `references/skill-questions.md`）。

**通用阶段 3 协议**（L2 共享）: 一次一问 / 智能跳过 / 追问一次 / 逃生通道——已在 L2 SKILL.md 详述, 本文件不重复。

## 阶段 4: 输出（skill 专属）

写入 `.agent-genesis/work/{name}/skill-foundry/clarified-skill-requirements.yaml`。
格式: `references/schemas/clarified-skill.schema.yaml`（同包, Skill 私有）。

**不**写任何 `output/` 交付文件（需求契约只落 `clarified-skill-requirements.yaml`，两条 pipeline 一致）。

如果阶段 1 发现已有 Skill 目录（`output/skills/{name}/v1/SKILL.md` 存在）, 设置 `build_mode: incremental`。
否则 `build_mode: greenfield`。

## 与下游 skill-planner 的契约

`clarified-skill-requirements.yaml` 是 skill-planner step-s1 的**直接输入**。skill-planner 必须:
1. Read `clarified-skill-requirements.yaml`（Q1-Q4 决策 + acceptance_criteria + knowledge_assets + dedup_check 候选）
2. 对每个决策点引用 `guide.yaml` 对应节作为 evidence
3. 输出 `phase1-skill-design.md`（frontmatter 含 Q1-Q4 + granularity_decision + frontmatter_draft 完整字段, 满足 skill-design-rules.md §阶段1 契约）

skill-planner **不读** clarification Skill 的任何 L2 协议段, 不读 D 编号/通俗解释/推荐理由——那些是给用户看的, 不是给 planner 看的。
