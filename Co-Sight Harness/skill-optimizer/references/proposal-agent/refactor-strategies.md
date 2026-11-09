# 重构策略引导(生成 mod 前的操作层判断)

> **由 proposal-agent.md 引用。诊断完后、动手 Edit 前 Read。**
> **⚠️ 重要:这些是"如何改"的工具,**先评估是否能保分**再用,不能为降本而降本。**

诊断完之后、动手 Edit 之前,先按以下引导判断**改法**,而不是直接动手扩写 SKILL.md body。本节与 `self_check` 检查项互补:self_check 检查"结果是否达标",本节引导"怎么改才能达标"。

## 优先"提取到 L3"而非"扩写 SKILL.md body"

| 内容类型 | 优先改法 | 反例(禁止) |
|---|---|---|
| >100 行参考文档(规范、清单、长篇说明) | 提取到 `references/<topic>.md`,SKILL.md 加一行 `详见 references/xxx.md` 引用 | 内联到 SKILL.md body,撑爆行数 |
| >10 行确定性操作(校验/比对/转换/正则/数学) | 提取到 `scripts/<verb>_<noun>.py`,SKILL.md 用 `Bash python scripts/xxx.py <args>` 调用 | 内联 Python/Shell 代码块 |
| 可复用输入/输出格式 | 提取到 `templates/<name>.md`,SKILL.md 引用 | 模板混在 body 里 |
| 跨多个 SKILL.md 的共用规则 | 提取到 `references/_common.md`(多 Skill 模式) | 每个 SKILL 重复写一遍 |

## 渐进式披露触发条件(任一满足即触发 L3 拆分)

- SKILL.md body **> 300 行** → 必须把超出部分外移到 `references/`
- 内联 **>100 行** 参考文档或代码块 → 必须外移
- 同一概念在 SKILL.md **出现 ≥3 次** → 抽 references/ 一次性写,其他处用"详见 X 段"引用
- 内联 **>10 行 Python/Shell 代码** → 必须抽 `scripts/`(d7bcf0da 实战教训:LLM 做确定性操作会出错)

## 避免 SKILL.md 重复内容(每条 mod 应用前必问)

1. **同 SKILL 内重复**:这段内容是否已在其它 H2 章节写过?若是,只改 1 处,其他处加引用
2. **跨 SKILL 重复**:多个 SKILL.md 是否描述同一能力?若是,抽 `references/_common.md` 或合并 description
3. **幽灵引用**:`references/` 下文件是否在 SKILL.md 中被显式引用?没引用则删文件或加引用
4. **引用断链**:SKILL.md 引用的 `references/xxx.md` 是否真实存在?引用前必 `test -f` 验证

## scripts/ 改动前的 source 链预检(d7bcf0da 实战教训)

修改/合并/删除 `scripts/` 下任何文件前,必跑:

```bash
grep -rn "source\|if.*-f.*\.sh" scripts/   # 列出所有 source 引用点
```

逐个确认引用已同步,避免"删 config.sh 后 5 个脚本还引用它"导致 SKILL 失效。

## 流程图外移的中间层保留(d7bcf0da 实战教训)

把详细流程图外移到 `references/router.md` 时,**关键路径必须保留**:

- 关键链路标 `⚠️ 必须包含中间组件`,防止 Agent "简化路径"
- 即使 R 中的路径经过中间层(SMC/FCS 等),Agent 也要按 R 实际描述生成,不能跳过
- SKILL.md body 保留强制路径的 1-2 行关键描述,不要全外移

## ⚖️ 决策铁律(避免 round_1/2 副作用)

**改任何 L3 抽取前,先评估对未失败 case 的影响**:

1. **不要为抽而抽** —— L3 抽取节省 token,但**可能伤害当前能跑通的 case**
2. **修改前必看 score_history**:之前 0 分 case 现在几分了?之前中分的还在吗?
3. **失败经验**:Round 2 的 M1 ensure_user_analysis_row.py 抽取后,**反而把 5 个 case 的 09 文件覆盖破坏**,从 83→0
4. **改 SKILL.md body 优先于抽 references/**:除非真能省 token,否则**文字调整更安全**
5. **业务规则(列名/动词/术语/合法集)文字责任在 SKILL.md,代码只解析** — R8 反例:`extract_problem_candidates.py` 把 `PROBLEM_SOURCE_COLUMNS=['建议方案','触发原因',...]` 和 `goal_verbs=['提升','降低',...]` 硬编码到 Python → 改业务规则必须改代码(违反 KISS)。**正确分工**:
   - SKILL.md 加 `## 业务规则` 段(文字责任)
   - 脚本 `load_business_rules(skill_md_path)` 解析(代码责任)
   - 算法参数(max_chars / max_candidates / 阈值)才写到 `config/evolve-user-config.yaml` 的 `eval.thresholds` 段

**触发 L3 抽取的安全条件**(全部满足):
- ✅ SKILL.md > 300 行(或内联 >100 行)
- ✅ 该段 LLM 多次重读且无动态变化
- ✅ 修改不依赖上下文(纯静态参考文档)
- ✅ 已有 5+ 个 case 已通过,稳定可抽
- ⚠️ 任何一项不满足 → 优先用 `condense` / `edit_exact`,不动 L3