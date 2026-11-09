# Skill 模式访谈问题清单 — Requirement Clarifier L3

> 加载者: skill mode 命中后由 workflow-skill.md 引用
> 内容: Q1-Q4 / G1-G2 / 去重 / SF-6 公式的**访谈问题**（人话版）
> **不复制判定数值**——所有判定/阈值/操作模式定义/粒度阈值均指回 `knowledge/skill/skill-creation-guide.yaml` 唯一权威
> **防三重拷贝反模式 (R3 缓解)**: 本文件只问"怎么问用户", 不答"答案是什么"

---

## Q1: 操作模式（不复制 4 个 mode 名称的判定, 只问意图）

D<N> — 这个 Skill 主要做什么类型的活?
场景: 不同的操作模式对应不同的 SKILL.md 结构（有无 references/、有无 scripts/、模板形态）。
选错的代价: 选错会导致生成的 SKILL.md 没有对应章节, 下游 verifier (SK-S10 SF-1) FAIL。
推荐: 按用户的真实使用场景选择; 不确定时由 skill-planner 在阶段 1 决策（**仅引用 `guide.yaml §1 Q1` 决策表**, 不在本文件判定）。

A) 一个一个地分析、判断（推荐, 如果是审查/决策类）
B) 从一堆东西里筛出需要的、按某种规则排序
C) 把输入转成另一种形态输出（解析/格式转换/编译）
D) 边操作边记, 最后产出一份报告

完整度: 四个选项覆盖了 4 类基本操作模式, 但用户业务可能横跨多类, 选最接近的; 选错由 skill-planner 在阶段 1 兜底（guide.yaml 决策表）。

## Q2: 知识资产（不复制 guide.yaml Q2 的 references/scripts/templates 必要性论证）

D<N+1> — 这个 Skill 需要哪些支撑材料?
场景: 不同的支撑材料决定 SKILL.md 的目录结构。
选错的代价: 选少 → 生成的 Skill 知识不完整; 选多 → 冗余目录, 触发 SF-1 FAIL。
推荐: 按实际需要选; 不确定时由 skill-planner 在阶段 1 决策（仅引用 `guide.yaml §1 Q2`）。

A) 还需要查一些文档/规则（推荐, 如果存在外部规范/手册/检查清单）
B) 还要跑一些脚本（推荐, 如果有 LLM 不擅长的精确操作/校验/格式转换）
C) 还要给用户输入/输出模板（推荐, 如果用户每次都要从零构造参数）

完整度: 三类资产可多选; 选错由 skill-planner 在阶段 1 兜底（guide.yaml Q2）。

## Q3: 触发场景（不复制 SF-6 描述公式, 只问触发意图）

D<N+2> — 用户什么情况下会调起这个 Skill?
场景: 触发场景决定 description 字段的"何时触发"段, SF-6 公式四要素之一。
选错的代价: 触发场景模糊 → description 不够具体 → 路由时与其他 Skill 撞车。
推荐: 给出 1-2 个最常见入口, 用"当...时"句式。

答案需落到 `frontmatter_draft.description` 的"何时触发"段。具体:
- 用户的哪句话 / 哪个动作 / 哪个文件路径变化会触发?
- 是否需要先有特定上下文（如已有 plan.md / 已有 review 报告）?

## Q4: 验收标准（given/when/then, 通用三段式）

D<N+3> — 怎么算这个 Skill 干成了?
场景: 验收标准是 Step 6 product-tester 黑盒测试的种子, 也是 verifier 静态校验的基线。
选错的代价: 验收标准模糊 → 测试用例无法设计 → 端到端盲评无依据。
推荐: 至少 3 条 given/when/then; 数字/字段名/输出文件名要具体。

答案需落到 `acceptance_criteria[]` 数组; 字段名/输出路径必须能在产物中找到。

## G1: 粒度裁决（不复制 400 行阈值, 只问领域数）

D<N+4> — 这个 Skill 是干一件大事, 还是分几个独立小 Skill?
场景: 多 Skill vs 单 Skill 决策影响目录结构, 错误决策会导致 1 Skill 装太多职责, 触发 SF-1 FAIL。
选错的代价: 单 Skill 装多个独立功能域 → description 模糊, 路由歧义。
推荐: 按职责是否独立判断; 阈值由 skill-planner 在阶段 1 用 `guide.yaml §2 G1-G2` 决策（**不在本文件判定**）。

A) 一件事, 一个 Skill 干完（推荐, 多数场景）
B) 两件及以上独立的事, 拆成多个 Skill（推荐, 如果功能域边界清晰）

完整度: 由 skill-planner 在阶段 1 用 guide.yaml 阈值兜底。

## 去重（create 模式必问）

D<N+5> — 这个 Skill 跟项目里已有的 Skill 撞名/撞触发场景吗?
场景: 已有 skills/*/SKILL.md 里的 description 可能与新 Skill 高度相似。
选错的代价: 撞名导致路由歧义; 用户调用时无法精确触发。
推荐: 已扫过 `skills/*/SKILL.md`, 给出最相似的 1-2 个候选 + 区分点（由 skill-planner 阶段 1 自动跑, 此处仅做用户复核确认）。

答案回写到 phase1-skill-design.md 的 `dedup_check` 字段。
