# token 减少技巧(降本优先降级为次要目标)

> **由 proposal-agent.md 引用。**
> **⚠️ 重要:本节是次要目标的技巧清单,**不能为降本而降本** —— 任何降本必须保证分数不下降。**

## ⚠️ 核心警告

**优先级铁律**:**提分 > 降本**

本节列出的技巧都是**次要目标**。**Round 1/2 实战教训**:

- Round 1 优化后,3 个 case 暴涨(0→100)+ 4 个 case 暴跌(83→0、63→0、53→0、33→0),净 -2.44
- Round 2 进一步优化,反而把 5 个 case 已通过的产物覆盖破坏(从 83→0)
- **降本很容易,保分很难**

**修改前必读** `safety-rules.md` 的"决策铁律"段。

## 触发条件(全部满足才能用)

```
✅ 触发降本技巧的安全条件(必须全部满足):
- SKILL.md > 300 行(或内联 >100 行)
- 该段 LLM 多次重读且无动态变化
- 修改不依赖上下文(纯静态参考文档)
- 已有 5+ 个 case 已通过,稳定可抽
⚠️ 任一项不满足 → 优先用 condense / edit_exact,不动 L3
```

## 渐进式披露(PROGRESSIVE DISCLOSURE)

**核心思想**:LLM 不需要一次读所有内容,只读当前 step 需要的。

| 改法 | 适用场景 | 效果 |
|------|----------|------|
| `split_skill` | SKILL.md > 500 行 | 拆出 `_advanced.md`,主文件留核心段 |
| 抽 `references/<topic>.md` | >100 行参考文档 | SKILL.md 加 1 行引用 |
| 抽 `templates/<name>.md` | 可复用模板 | SKILL.md 引用 |

## 提取到 L3(extract_to_script)

**何时抽**(必须满足):

- 规则明确是**枚举 / 正则 / 校验**
- **反复执行**(LLM 多次重复同一段代码)
- **确定性结果**(没有 LLM 智能推断空间)

**何时不抽**:

- ❌ 规则需要 LLM 上下文判断(让 SKILL.md body 描述即可)
- ❌ 规则只执行 1-2 次(脚本维护成本 > 直接执行)
- ❌ 上次抽取副作用严重(参考 Round 2 的 M1 ensure_user_analysis_row.py)

**典型反例(Round 2)**:

```python
# ensure_user_analysis_row.py 抽取后,脚本"自动"覆盖了 5 个 case 已通过的 09 文件
# 原因:脚本没有 _has_valid_data_row 检测,见 RAN-3404224 从 63→20
```

**修复模式**(避免重复):

- 抽脚本前先在 SKILL.md 加"如已存在有效 X,跳过脚本"硬约束
- 或在脚本顶部加 `if already_valid(): return SKIP`
- 或优先用 `edit_exact` 强化 SKILL.md body,不抽脚本

## 合并冗余(`condense`)

- 同一规则在 SKILL.md 出现 ≥3 次 → 合并为 1 处 + 引用
- 多 SKILL 重复描述同一能力 → 抽 `references/_common.md`(多 Skill 模式)
- 章节定义模糊导致 LLM 困惑 → 重写,让边界清晰

## 删除冗余(`delete_redundant`)

- 旧规则被新规则完全覆盖 → 删旧规则
- `SKILL.md` 中"附录"/"已知问题"等历史段 → 移到 CHANGELOG,不留 body
- 失败的 mod 描述、调试日志 → 移 references/_history.md(如有)

## Token 影响预估

每条 mod 必填字段:

- `estimated_token_impact`: int(可为负,选 extract/condense/delete 通常为负)
- `score_impact`: float(预计提升 score 百分点)
- `cost_benefit`: float = `score_impact / max(1, abs(estimated_token_impact) / 100)`

**新字段(必填,防 trade-off 副作用)**:

- `non_target_cases_risk`: 0/1/2(对未失败 case 的伤害风险)
- `risk_evidence`: 具体 case_id + 失败模式
- `net_impact`: score_impact - (non_target_cases_risk × expected_harm_size)

如果 `non_target_cases_risk ≥ 2`,**即使 score_impact 巨大,也不写入 modification**(参考 trade-off 评估段)。

## 实战教训(避免重复)

| 技巧 | Round 1 后果 | Round 2 后果 | 教训 |
|------|------------|------------|------|
| 抽 ensure_user_analysis_row.py | - | **5 case 被覆盖破坏** | 抽脚本必须有"已存在则跳过"保护 |
| M4 split_skill(场景类型抽 references) | **未生效** | Round 2 重做 | LLM 对 split_skill 实施有困难 |
| M1 沙箱限制硬约束 | 子代理幻觉修了但伤害其他 case | - | 硬约束泛化容易伤害其他路径 |
| M2 强制输出最低保障 | LLM 输出"占位"被判 0 | - | 强制输出必须有真实内容保护 |

**核心教训**:**降本技巧的副作用难以预测,必须严格验证 trade-off。**