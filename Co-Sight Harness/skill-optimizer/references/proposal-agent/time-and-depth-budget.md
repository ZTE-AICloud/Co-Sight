# proposal-agent 时长与探查深度硬约束

> **目的**:避免 LLM 把单次 proposal 调用压缩在 5 分钟内"草草了事"、Plan 阶段只列单线 mod、consume_lib 流于形式。
>
> **使用方式**:本文件是 `agents/proposal-agent.md` 的配套约束,prompt 里通过「按需 Read」引用,LLM 在落盘 `optimization_summary.md` 前**必须 Read 本文件**。

---

## ⏱ 时长硬约束

**目标**:单次 proposal 调用 **600-900 秒**(10-15 分钟)。

| 检查项 | 阈值 | 违反动作 |
|--------|------|----------|
| **单次 LLM 调用总时长** | ≥ 600s(10 分钟) | 若 < 600s,LLM 必须在落盘前主动追加一轮探查(再 Read 2-3 个相关文件 / 再 grep 1 轮关键模式 / 再扩展一次 consume_lib 探查),而不是直接 Edit 落盘 |
| **Step 3 (Hypothesize) 阶段耗时占比** | ≥ 120s(20% 总时长) | 用 Read 工具计数 + Edit 之间的时间间隔粗略自评,过低说明跳过 5 维根因卡 |
| **Plan 整理耗时** | ≥ 60s,落盘 `_plan_summary.md` | 必须显式落盘(`ls {cand_dir}/_plan_summary.md` 存在性自检) |
| **自我提醒触发器** | 每 5 分钟(300s) | 在 Step 6 之前若累计 Read < 15 个文件,主动追加 Read 不进 Edit |

**LLM 自检命令**(落盘 `optimization_summary.md` 前必须执行):
```bash
# Step A: 文件落盘存在性自检
ls -la {cand_dir}/_read_audit.json {cand_dir}/_plan_summary.md 2>&1
echo "---"
# Step B: plan 落盘内容自检(必须有 ≥2 个候选 mod 方向,不能只列 1 个)
grep -c '^|' {cand_dir}/_plan_summary.md  # 应 ≥ 5 行 mod 候选
echo "---"
# Step C: consume_lib 探查深度自检
grep -c '"path":' {cand_dir}/_read_audit.json  # files_read 字段的 path 数
```

**禁止"为达标编造耗时"**:`proposal_metrics.json` 中 `latency_ms` 由 framework 在调用开始/结束时打点,**LLM 无法篡改**。如自评"我做了 15 分钟"但实际 348s,后续 review 会与 metrics 不一致被识别。

**deep_analysis 加分项**:
- ✅ 单次调用 ≥ 600s + `overall_pass: true` → 标记 `deep_analysis: true`
- ✅ ≥ 900s + `overall_pass: true` → 标记 `ultra_deep_analysis: true`(超时上限保护,避免无意义延展)
- ✅ Plan 阶段有 ≥ 3 个候选 mod 方向对比 → 标记 `plan_thoroughness: high`

---

## 📋 Plan 阶段内容硬要求

**`_plan_summary.md` 强制格式**(LLM 必须按这个骨架写):
```markdown
# Plan 摘要 (round=N, <起点> → 候选 K)

## 起点
- baseline_avg / 上轮 avg = <分数> / 100 (<case 数> case)
- 失败模式分布:
  - 0 分 (<case 数> case): <case_id 列表> — <共性根因 1 行>
  - 中分 (<case 数> case): <case_id 列表> — <共性根因 1 行>
  - 高分 (<case 数> case): <case_id 列表> — <勿动,避免 risk>

## 候选 mod 方向对比表(必填 ≥ 3 行,不允许只列 1 个)
| # | 方向 | 预期覆盖 case | non_target_cases_risk | net_impact | ROI |
|---|------|---------------|----------------------|-----------|-----|
| A | <方向 1 描述> | <case 列表> | 0/1/2 | <正负值> | 高/中/低 |
| B | <方向 2 描述> | <case 列表> | 0/1/2 | <正负值> | 高/中/低 |
| C | <方向 3 描述> | <case 列表> | 0/1/2 | <正负值> | 高/中/低 |

## 决策(选 A+B 或 A+C 等)
- 选中的组合 + 理由(< = 80 字)
- 放弃的组合 + 理由(< = 80 字/每条)

## 执行顺序
1. <mod 1 + file + 预期 case>
2. <mod 2 + file + 预期 case>
3. <mod 3 + file + 预期 case>
```

**LLM 自检**(落盘前必跑):
- `grep -c '^|' _plan_summary.md` 应 ≥ 5 行(mod 候选表至少 3 行 + 表头 + 分隔线)
- 每个候选必须有 `non_target_cases_risk` 数字字段
- 决策段非空

**❌ 禁止的做法**:
- ❌ 只列 1 个 mod 方向(没有对比)
- ❌ 候选表缺失 `non_target_cases_risk` 字段
- ❌ "放弃候选"只有 1-2 行理由,无 ROI 量化
- ❌ 在 Edit 完之后才补 plan 摘要(顺序必须是 plan 摘要先落盘 → 再 Edit → 再落 optimization_summary)

---

## 📚 consume_lib 探查深度硬要求

**强制要求**(LLM 必须满足,否则视为"无全局视角"):

| 检查项 | 阈值 | 证据落盘位置 |
|--------|------|--------------|
| **文件探查数** | ≥ 3 个代表性 .md(不能再 1-2 文件就走) | `_read_audit.json.consume_lib_exploration.files_read_count` |
| **目录探查深度** | ≥ 2 层子目录(只看根目录 = 0 分) | `_read_audit.json.consume_lib_exploration.depth` |
| **insights 数量** | ≥ 2 条(必须有具体方法论,不是空泛说"无更高视角") | `optimization_summary.md.self_check.knowledge_used.insights` |
| **mod ↔ 知识库关联** | 每条 mod 至少引用 1 个 consume_lib 路径/原则 | `modification.knowledge_ref` 字段(可选,但建议填) |

**禁止的"假探查"模式**:
- ❌ 只 `find` 不 Read(等于查目录清单)
- ❌ 只 Read 1 个文件就走(深度不够,跨场景共性拿不到)
- ❌ insights 写"无更高视角可补" — **必须写明具体方法论**,即使是"本轮 case 确实无通用方法论,因 case 都特异化",也要给出理由
- ❌ 探查路径全在 `consume_lib` 根目录,不进子目录

**自我验证命令**(落盘前必跑):
```bash
# 校验 consume_lib 探查深度
python3 -c "
import json
d = json.load(open('_read_audit.json'))
cl = d.get('consume_lib_exploration', {})
n_files = cl.get('files_read_count', 0)
depth = cl.get('depth', 0)
assert n_files >= 3, f'consume_lib files_read_count={n_files} < 3,补读至少 1 个文件'
assert depth >= 2, f'consume_lib depth={depth} < 2,进入至少 1 个子目录'
insights = json.load(open('optimization_summary.md_header.json'))['self_check']['knowledge_used']['insights']
assert len(insights) >= 2, f'insights 数量 {len(insights)} < 2,提炼至少 2 条方法论'
print('FOUND: consume_lib 探查合规')
"
```