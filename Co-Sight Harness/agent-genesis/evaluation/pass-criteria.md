# AgentGenesis 评估通过标准

> 来源: AgentGenesis CLAUDE.md — 五、Evaluation Contract
> 用途: 外部评估 AgentGenesis 产出质量的判定标准
> 与 Phase 4 的 7+1 项静态检查 1:1 对应

## 硬校验项（自动判定 — 与 Phase 4 7 项检查对齐）

| 编号 | Phase 4 检查 | 校验项 | 判定方法 | 通过阈值 |
|:----:|:-----------:|--------|---------|:------:|
| H-01 | 1-完整性 | 输出文件存在 + 目录结构完整 | `find $AGENT_OUTPUT_ROOT/{name}/$VERSION -type f` | CLAUDE.md + matching-decision.md + review-report.md + verification-report.md 四者存在 |
| H-02 | 2-格式 | 章节完整 + 无占位符 | `grep -c '^## ' CLAUDE.md`；`grep -c '{{.*}}' CLAUDE.md` | 章节 == 8；占位符 == 0；无 TODO/TBD 残留 |
| H-03 | 3-引用 | 工具/Skill/路径引用合法 | 工具白名单匹配；Skill 可追溯到定义文件 | 未知工具 == 0；路径引用闭合 |
| H-04 | 4-Schema | Schema 语法合法 + 实体对应 | `json.load()` / `yaml.safe_load()` 可解析；实体属性在 Schema 中体现 | schemas/ 下所有文件可解析 |
| H-05 | 5-流转闭合 | 数据实体有生产者和消费者 | 实体表解析 + 生产者/消费者图 | 0 个悬空实体（非最终输出） |
| H-06 | 6-约束自洽 | CD3-K 一致 + Safety-Role 一致 | CD3 权威领域有 K 来源；禁止领域无 K 来源 | 0 个 CD3-K 冲突 |
| H-07 | 7-加载策略 | L2 决策有 rules/ 文件；L3 决策有 Skill 声明 | L2 引用文件均存在；L3 Skill 有 SKILL.md 且格式完整 | L2 文件全部存在 + L3 SKILL.md 皆 >= 500 字符 |
| H-08 | 8-Plan 一致性 | 构建方案文件存在且格式完整 | `work/{agent-name}/agent-creation/construction-plan.md` 存在且含 8 个必需章节 | 8 章节齐全 + Plan ID 有效 + 状态 ∈ {APPROVED} |
| H-09 | 8-Plan 一致性 | 生成输出与 Plan 声明的文件清单一致 | 对比 Plan 中"文件创建清单"与实际 `find` 输出 | 无遗漏文件 + 无多余文件 |
| H-10 | Phase 5 | 运行时评估报告存在且含 4 维评分 | `grep -c '## (correctness\|completeness\|format_compliance\|actionability)' work/{name}/agent-creation/phase5-runtime-eval.md` | 4 维度均有评分 (1-5) + verdict 字段存在 |
| H-11 | Phase 5 | 评估使用的测试任务 YAML 合法且匹配 Agent 类型 | `yaml.safe_load()` 可解析；`agent_type` 字段与 matching_decision 一致 | YAML 可解析 + agent_type 匹配 |
| H-12 | 级联-Tier0 | Tier 0 MN 判定存在且 confidence 合法 | `grep tier_0 + confidence` 于 matching_decision 文件 | confidence ∈ {high, medium, low} + mission_nature ∈ {MN-Exploratory, MN-Deterministic, MN-Hybrid} |
| H-13 | 级联-Tier1 | Tier 1 子集与 Tier 0 一致 | 比对 cascading-matcher.yaml 的 cascade_action.subset | 子集与 cascading-matcher.yaml 定义一致（含 override 标注） |
| H-14 | 级联-MN-Hybrid | MN-Hybrid 声明了 phases 分段 | `grep phases` 于 matching_decision 文件 | phases 字段存在且每段标注 mission_nature + 模式倾向 |
| H-15 | 阻断检查 | Phase 1 阻断检查通过 | 检查 blocker-check-result.md 存在且 exit code 0 | blocker-check-result.md 存在且 Result=PASS |

## 软校验项（人工判定）

| 编号 | 校验项 | 评分标准 (1-5) | 通过阈值 |
|:----:|--------|---------------|:------:|
| S-01 | 模式匹配准确性 | 5=所有选中模式精确对应需求语义意图 | >= 4 |
| S-02 | Spec 内容正确性 | 5=填充值完全匹配用户需求 | >= 4 |
| S-03 | 审查质量 | 5=审查发现真实问题，无假阳性 | >= 3 |
| S-04 | 修复方向可行性 | 5=诊断建议在上下文中可操作 | >= 3 |
| S-05 | 章节间一致性 | 5=跨章节引用闭合，无矛盾 | >= 4 |
| S-06 | Plan 质量 | 5=Plan 清晰完整、风险识别准确、决策说明充分 | >= 4 |
| S-07 | 运行时质量 | 5=4 维加权总分 >= 4.5，Agent 实际行为完全符合预期 | >= 3.5 (加权) + correctness >= 3.0 + completeness >= 3.0 |
| S-08 | 级联匹配质量 | 5=MN 判定合理 + 子集选择适当 + cascade_tendencies 使用正确 + override 理由充分 | >= 3 |

> 软校验详细评分细则见 [quality-rubric.md](quality-rubric.md)

## 综合评分

| 维度 | 权重 | 分数 |
|------|:----:|:----:|
| 模式匹配准确性 | 25% | /5 |
| 级联匹配准确性 | 10% | /5 |
| Spec 完整性 | 25% | /5 |
| Spec 一致性 | 15% | /5 |
| 审查有效性 | 15% | /5 |
| 可追溯性 | 10% | /5 |
| **加权总分** | | **/5** |

## 通过条件

- 硬校验项 H-01 至 H-15 全部通过（H-08/H-09 为 Plan 相关，仅当存在 construction-plan.md 时适用；H-10/H-11 为 Phase 5 相关，仅当 Agent 通过 Phase 4 时适用）
- 加权总分 >= 4.0
- S-01 (匹配准确性) >= 4
- S-08 (级联匹配质量) >= 3

## verdict 值定义

| verdict | 含义 |
|---------|------|
| PASS | 全部适用硬校验通过 |
| PASS-WITH-WARNINGS | 硬校验全部通过但软校验有 >= 1 项低于阈值 |
| FAIL | 硬校验有未通过项 |
