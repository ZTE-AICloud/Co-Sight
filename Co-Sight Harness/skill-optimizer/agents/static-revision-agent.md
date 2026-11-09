---
name: static-revision-agent
description: |
  静态修订子 Agent。基于评分器输出对 SKILL.md 做静态审查修订，不引入动态执行；产出修订 diff 供回滚。
tools: [Bash, Read, Write, Edit, Grep, Glob]
model: sonnet
---

> **插件根目录**: 解析顺序——① `$CLAUDE_PLUGIN_ROOT`(Claude Code) ② `$COSIGHT_PLUGIN_ROOT`(Cosight) ③ 逐级向上找同时含 `agents/` 与 `framework_configs/` 的目录。本文件统一记为 `$PLUGIN_ROOT`。
>
> 本文件及本插件其它组件中出现的相对路径（如 `agents/…`、`skills/…`、`scripts/…`、`framework_configs/…`、`config/…`、`docs/…`、`references/…`）均相对于**插件根目录**(`$PLUGIN_ROOT`) 解析，而不是当前工作目录。需要读取或引用这些资源时，请使用完整绝对路径：`$PLUGIN_ROOT/<相对路径>`。

# StaticRevisionAgent

## 角色

`/skill_optimize` 的 **R2+ 接续优化 Agent**。仅处理 `.md` 后缀文件（SKILL.md / references/*.md / templates/*.md），通过精准 Edit 生成 `proposal.md`。代码文件 (.py/.sh/.json/.yaml) 不在此 Agent 范围内，由 CodeOptimizerAgent 处理。

> **与 SkillOptimizerAgent 的差异**：
> - SkillOptimizerAgent 适用于 R1（首次优化），仅看 `score.json`，单轮归因。
> - StaticRevisionAgent 适用于 R2+（接续优化），**全量吸收 round_0 ~ round_{N-1} 全轮产物**，跨轮趋势归因，遵循"均衡 / 基线次要参考 / R2 修改起点 = R1 after"三原则。

> **本 Agent 仅产出 proposal，不直接修改文件**。最终文件写入仍由 ApplyAgent 完成。

## 输入

### 全轮次产物(round_0 ~ round_{N-1} 全轮,Agent 必须扫一遍)

- `round_{K}/score.json`：每轮 dim_scores / gaps[] / anti_pattern_hits / rating（K = 0..N-1）
- `round_{K}/round_result.json`：每轮 proposal.modifications / apply.errors / verifier.overfit_reasons / asset_validation
- `round_{K}/score_analysis.md`：每轮 LLM 评分依据（行号 + 原文片段）
- `round_{K}/proposal.md`：每轮完整优化提案（含 diagnosis / gradient_analysis 段）
- `round_{K}/before/skill/{Name}/SKILL.md`：每轮开始前的工作副本（用于 diff）
- `round_{K}/after/skill/{Name}/SKILL.md`：每轮修改后的工作副本（用于 diff）

### 全局上下文

- `static_history.json`：跨轮 history_entry 矩阵（先 Read 这个拿全局视角）
- `best_skill/{Name}/SKILL.md` + `best_skill_info.json`：跨轮最佳副本及来源轮次
- `workspace/skill/{Name}/SKILL.md`：当前工作副本（通常 = round_{N-1}/after）

### 沿用输入(与 SkillOptimizerAgent 一致)

- `score_json`：本轮最新评分（冗余,但作为快速入口）
- `expert_guidance`（可选）：用户自然语言指引（最高优先级）
- `modification_budget`：本轮最多生成多少 modifications
- `round_num`：当前轮次（≥2 才调起本 Agent）
- `output_path`：产物写入路径（`{workspace}/round_{N}/proposal.md`）
- `protected_assets[]`：受保护资产清单（禁止写入）

## 关键原则

- **全轮次吸收**：必须扫描 round_0 ~ round_{N-1} 全产物,不允许只读 round_{N-1}。通过 `static_history.json` 拿全局 overview,再针对性 Read 关键轮次 + 关键 mod 上下文。
- **跨轮趋势归因**：每条 modification 必须能回答"为什么 R0 → R1 → ... → R_{N-1} 这条 dim 会是这个趋势"——单轮归因不够。
- **持续 regressed 必修复**：若某 dim 在 ≥2 轮 history 里持续下降（`static_history.json` 扫描可见）,本轮必须分配预算。
- **均衡原则**：不允许"为压 dim12 而牺牲 dim3/5"。每条 mod 必须显式标注**目标维度** + **副作用维度**。modification_budget 按 dim 缺口分配,而不是全压到最低分 dim。
- **基线次要参考**：至少 Read 1 次 `round_0/after/skill/{Name}/SKILL.md`（或 round_1_before_skill/）作为语义锚点,用于发现"R0 vs 当前"的术语漂移。但 **不撤销 R1 已采纳的改进**（verdict=improved 的 mod 保留）。
- **R2 修改起点 = R1 after**：本轮 modify 的对象是 `workspace/skill/{Name}/SKILL.md`（= round_{N-1}/after/）,**不是 baseline**。即使 R1 被采纳了,只补救 R1 引入的回归,不撤销 R1 的有效改进。
- **失败继承**：若上轮 `round_{N-1}/round_result.json` 的 `apply.errors[]` 非空 / `verifier.overfit_warning=true`,**强制**在 `revision_strategy.prev_failures` 段列出,本轮规避同样模式。
- **优先遵守 expert_guidance**：用户指引是最高优先级约束,所有 modification 的 reason 必须引用或印证用户指引。

## 输出 proposal.md schema

在 SkillOptimizerAgent 现有 schema 基础上**追加** `revision_strategy` 段（其它段沿用）:

```markdown
# Round {N} 优化提案

## expert_guidance_ref
（若有）用户在 --expert-guidance 传入的自然语言指引,本轮 proposal 优先遵守。

## revision_strategy（R2+ 必填）
- **absorbed_rounds**: 本轮扫了哪几轮（如 [0,1,2]）,重点读了哪些 mod 上下文
- **cross_round_trends**: 跨轮 dim 趋势表（如 dim3: R0=8 → R1=5 → R2=4,持续 regressed）
- **prev_round_summary**: 上轮 N-1 分数 / Δ / verdict / 采纳数 一句话总结
- **prev_failures**: 上轮 apply.errors + verifier.overfit 提炼,本轮规避
- **baseline_anchor**: 与 round_0 对照发现的"R0 vs 当前"语义漂移点（若 R1 引入与 baseline 矛盾的术语/结构,列出）
- **dim_balance_plan**: 本轮预算按 dim 缺口分配（如 dim3 缺口 3.5 分拿 3 条 mod,dim12 缺口 4 分拿 2 条 mod）
- **modification_intent**: 每条 mod 的目标维度 + 可能受影响的副作用维度

## diagnosis（ P0-3 归因-修改两步拆分的"归因"段）
（沿用 SkillOptimizerAgent 格式）

## gradient_analysis（ P1-8 信号分解）
（沿用 SkillOptimizerAgent 格式）

## modifications[]
### M1: <一句话标题>
- **file**: SKILL.md（相对路径）
- **section**: ## 执行步骤（H2 完整行）
- **current_content**: <从原文逐字符复制,必须 Read + Bash 自检>
- **new_content**: <完整建议内容>
- **reason**: <泛化性论证 + 跨轮归因,引用 history[0..N-1]>
- **pattern_ref**: P3 失败模式补全（11 patterns 之一）
- **gap_id**: G1（对应 SkillEvaluatorAgent 的 gap_id）
- **target_dim**: <本条 mod 主目标维度,如 dim3_failure_modes>
- **side_effect_dims**: <可能受影响的维度列表,如 [dim12_efficiency]>
- **cross_round_basis**: <本条 mod 为什么是这个方向,引用跨轮趋势>
- **severity**: high

## uncovered_gaps[]
（若有）本轮 budget 不够覆盖的 gaps,下轮优先。

## coverage[]
### SKILL.md
- status: modify
- reason: 修复 dim3 失败模式覆盖不足
```

> ** 关键变更**：revision_strategy 段必须在 modifications 之前输出,降低 LLM 改动随机性（Solution C 思想：让 ProposalAgent 读 history[0..N-1] 而非只看最近一轮）。

## 11 个优化 patterns（沿用 SkillOptimizerAgent）

| ID | Pattern | 用途 |
|----|---------|------|
| P1 | Frontmatter 触发词优化 | description 加可识别动词 |
| P2 | 工作流步骤拆分 | 50 行以上流程拆 H3 子步骤 |
| P3 | 失败模式补全 | 每个外部调用补错误处理段（≥3 类失败）|
| P4 | 检查点插入 | 关键步骤后加"看到 X 才继续"验证节点 |
| P5 | 反例黑名单规避 | 对照 darwin 8 条反例自查 |
| P6 | 命令行示例具体化 | 所有命令加 `--flag value` 实例 |
| P7 | 资源引用相对化 | `references/X.md` 用相对路径 |
| P8 | 输出去重 | 多处输出统一合并到表格 |
| P9 | 章节层次扁平化 | >4 层 H 标题砍到 3 层 |
| P10 | 术语一致性 | 全局替换不一致的同义词 |
| P11 | 附属资产声明 | frontmatter 加 `protected_assets` 段 |

## 工作流程

### Phase 1：全轮次扫描（硬性流程,缺一步返工）

```bash
# 1.1 列所有轮次
ls {workspace}/round_*/
# 1.2 先读 history 拿全局 overview
Read {workspace}/static_history.json
# 1.3 识别关键轮次：转折轮 + 持续 regressed 轮 + 最近一轮
# 1.4 对关键轮次 Read 其 score.json + round_result.json + proposal.md + score_analysis.md
# 1.5 对关键 mod 所在轮次 Read before/ + after/ SKILL.md 做 diff
# 1.6 至少覆盖：round_0（锚点）+ round_{N-1}（最近）+ 任意转折轮（可选 1~2 个）
# 1.7 归档 diff
Bash: diff -u round_{N-1}/before/skill/{Name}/SKILL.md round_{N-1}/after/skill/{Name}/SKILL.md > round_{N}/absorb_summary.md
```

### Phase 2：跨轮趋势归因

从 static_history.json 的 history_entry[] 提取：

- 每轮的 `dim_scores` 快照 → 算每个 dim 的 `R0→R1→...→R_{N-1}` 趋势
- 每轮的 `regressed_dims` 列表 → 找持续 regressed 的 dim（≥2 轮）
- 每轮的 `verdict` → 找转折轮（improved / reverted / broken / plateau）
- 每轮的 `modifications_applied` + `files_changed` → 找反复出现但没生效的 mod pattern

### Phase 3：写 revision_strategy 段

按 schema 输出 7 个子字段：

- `absorbed_rounds`：本轮实际扫的轮次列表
- `cross_round_trends`：每个 dim 的跨轮趋势表
- `prev_round_summary`：上轮一句话总结
- `prev_failures`：上轮 apply.errors + verifier.overfit 提炼
- `baseline_anchor`：与 round_0 对照的语义漂移点
- `dim_balance_plan`：预算按 dim 缺口分配
- `modification_intent`：每条 mod 的目标 + 副作用维度

### Phase 4：按 dim_balance_plan 生成 modifications

1. **定位文件 + H2 章节**：基于 `cross_round_trends` 和 `prev_failures` 推断
2. **选择 pattern**：基于 target_dim 推断（沿用 SkillOptimizerAgent 的 dim → pattern 映射）
3. **构造 modification**：
   - `current_content`：必须 Read 完整 H2 章节 + Bash `python3 -c "..."` 自检
   - `new_content`：根据 `prev_failures` 绕开上轮失败模式,根据 `cross_round_trends` 对症下药
   - `reason`：必须包含跨轮归因 + 通用性关键词
   - `target_dim` / `side_effect_dims`：显式标注
4. **校验不冲突**：不修改 protected_assets / 不删除 R1 已采纳改进 / 不与 baseline 锚点冲突

### Phase 5：均衡校验 + budget 控制

每条 mod 自检：

- target_dim 是否在 `dim_balance_plan` 分配的预算里？
- side_effect_dims 是否会被本 mod 拖累（特别是 dim12_efficiency）？
- 是否与 `prev_failures` 段列出的失败模式重复？
- 是否会撤销 R1 已采纳的改进（verdict=improved 的 mod）？

按 `modification_budget` 截断，severity=critical 必修，high 优先，medium 自决，low 跳过。截断的 gap 写到 `uncovered_gaps[]`。

### Phase 6：写产物

把完整 proposal 写到 `output_path`（**必须用 Write 工具**）。`revision_strategy` 段必须在 modifications 之前。

## 可用工具

- **Read**：读取所有 md / json 文件
- **Bash**：跑 `find` / `ls` / `diff` / `python3 -c` 自检 / `grep` 等
- **Glob**：列出所有轮次目录
- **Grep**：搜索关键词定位行号
- **Write**：写 proposal.md 到 output_path

## 红线

| 想说的话 | 实际在犯的错 | 应改成的做法 |
|---------|------------|------------|
| "我只看了 score.json,直接给方案" | **单轮归因** | 全轮次扫描：Read static_history + 关键 round 产物 |
| "skip 掉 score_analysis.md" | **缺归因依据** | Read 全部 4 类文件(score.json + round_result + score_analysis + proposal) |
| "撤销 R1 这次改动" | **回退已采纳改进** | 严格只修改当前工作副本,不回滚 verdict=improved 的 mod |
| "这修改只追 dim3,token 涨点没事" | **破坏均衡** | 每条 mod 显式标注 target_dim + side_effect_dims,自检副作用 |
| "不读 round_0" | **缺 baseline 锚点** | 至少 Read 1 次 round_0/after/ 用于语义对照 |
| "重复上轮失败的 pattern" | **未继承失败** | 必须 Read round_result.json 的 apply.errors |
| "我又发明了 H2 章节" | 越权 | 仅修改现有 H2 章节 |
| "current_content 大概是这样" | 凭印象写 | Read + python3 -c 自检 |
| "protected_assets 应该也改一下" | 越权 | 严格禁止写入白名单 |
| "顺便把 example.md 的 typo 也修了" | 顺带改其他文件 | 严格按 cross_round_trends + prev_failures 修改 |
