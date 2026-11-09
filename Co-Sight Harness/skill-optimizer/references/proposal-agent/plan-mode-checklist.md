# proposal-agent plan-mode 强制清单(模仿 Claude Code 内置 EnterPlanMode 提示词结构)

> **目的**:让 proposal-agent 在 sub-agent 限制下**模拟 EnterPlanMode 的硬约束**。
>
> **借鉴来源**:`~/.claude/plans/*.md` 的内置 plan 结构(Context / 不做什么 / 方案 4 字段 / 验证 / 风险 / 批准决策点)。
>
> **使用方式**:本文件是 `proposal-agent.md` 的配套 reference。
> LLM 在 Step 3 (Hypothesize) → Step 6 (Fix) 之间**必须 Read 本文件**,按 6 步仪式逐项打勾,才能进入 Edit 阶段。
>
> **与 `time-and-depth-budget.md` 的区别**:
> - `time-and-depth-budget.md` 讲"约束阈值"(时长 / 文件数 / 探查深度)
> - 本文件讲"仪式流程"(模仿 EnterPlanMode 的"思考 → 校验 → 批准"闭环)

---

## 🔒 EnterPlanMode 模拟协议(强制 6 步)

### Step P.0 — Context(为什么提这个 mod)

> 模仿 `~/.claude/plans/*.md` 的 Context 段:在 `_plan_summary.md` 顶部写本轮"为什么"。

**必填 3 字段**:
- **现状**:当前轮分数 / baseline / 上轮 best(从 `config.json` 读)
- **问题**:失败 case 列表 + 共同特征(从 `result_diff_report_round_{N-1}.md` 抽)
- **预期**:本轮目标分数 + 期望修复的 case 列表

**完成判据**:
- [ ] `_plan_summary.md` 顶部 3 字段齐全
- [ ] 失败 case 列表引用了 result_diff_report 行号

### Step P.1 — 不做什么(显式排除项)

> 模仿真实 plan 的"不做什么"段:防止范围蔓延,LLM 必须**主动声明** 排除项。

**必填 3 类排除项**:
- **不复用失败路径**:上轮失败的 mod / 失效的硬约束 / 被证伪的策略
- **不写代码层改动**:本轮只改 SKILL.md,不修 verifier 脚本 / 不动 orchestrator
- **不动业务耦合字段**:不引入业务专属名词 / 不硬编码 case_id

**完成判据**:
- [ ] ≥ 3 条排除项已列
- [ ] 每条排除项有"为什么不写"理由

### Step P.2 — 多假设对比(强制 ≥ 3 候选)

**核心问题**:避免"只列 1 个 mod 方向、靠运气撞对"。

**动作**:
1. 在 `_plan_summary.md` 候选 mod 方向对比表填 ≥ 3 行
2. 每行必须有:`预期覆盖 case / non_target_cases_risk(0/1/2)/ net_impact / ROI`
3. **关键思考**:**每个候选的反例是什么?**(模仿 EnterPlanMode 的"Plan 制定→Plan 评估"思路)

**完成判据**:
- [ ] 候选表 ≥ 3 行
- [ ] 每行有 non_target_cases_risk 数字
- [ ] 至少 1 个候选被放弃,且理由含 ROI 量化

### Step P.3 — 历史 mod 决策(round > 1 必做)

**核心问题**:防止 R3 类矫枉过正(读了 R1+R2 diff 后反向修复 R2 成功 mod)。

**动作**:
1. Read `round_{N-1}/skill_diff_round_{N-1}.md` 和 `result_diff_report_round_{N-1}.md`
2. 在 `_plan_summary.md` 加"上轮 mod 决策矩阵"段(成功 mod → 本轮保留 / 软化 / 移除)
3. 任何"移除"必须有 reason

**完成判据**:
- [ ] 已 Read 上轮 diff 报告 2 份
- [ ] 决策矩阵含成功 mod(分数 ≥ baseline 的 round 中的 best_candidate mod)
- [ ] "removed" 决策全部带 reason

### Step P.4 — 反例假说(防乐观偏差)

**核心问题**:LLM 默认乐观,只列"能修复的 case",不列"可能破坏的 case"。

**动作**:
1. 对每个选中的 mod,在 `_plan_summary.md` 加"反例预测"段
2. 反例:哪些 case 在 baseline=100 可能被这个 mod 拖累?为什么?
3. 与 baseline per-case 分数比对:`grep 'baseline_score' config.json`

**完成判据**:
- [ ] 至少 1 个反例假说被显式列出
- [ ] 反例已和 baseline 100 分 case 一一比对

### Step P.5 — 验证 / 风险 / 批准决策点(模仿真实 plan 末段)

**核心问题**:让 LLM 在 Edit 前**主动声明**"怎么验证 + 风险 + 用户决策点"。

**动作**:在 `_plan_summary.md` 末尾写 3 段:
- **验证方案**:本轮 Edit 后跑哪条 orchestrator 命令验证?预期分数区间?
- **风险与缓解**:每个风险 ≥ 1 行缓解措施
- **批准决策点**:列出"如果用户确认就继续 / 如果分数未升就回滚 / 如果出现 X case 退步就暂停"选项

**完成判据**:
- [ ] 验证方案段含具体命令 + 分数区间
- [ ] ≥ 3 条风险/缓解对
- [ ] 批准决策点 ≥ 3 个选项

### Step P.6 — 退出条件校验(模仿 ExitPlanMode)

**触发时机**:Step 6 (Fix) 启动前。

**动作**:
1. 重新 Read `_plan_summary.md`(自检)
2. 校验"完成判据"清单全部打勾
3. **禁止** 在未打勾的情况下进入 Edit 阶段

**完成判据**:
- [ ] P.0 / P.1 / P.2 / P.3 / P.4 / P.5 全部勾选
- [ ] `_plan_summary.md` 内容已与基线数据比对
- [ ] 时长预算符合 `time-and-depth-budget.md`(≥ 600s)

### Step P.7 — 落盘 plan_mode_used

**触发时机**:`optimization_summary.md` 落盘前。

**动作**:
1. 在 `self_check.plan_mode_used` 字段填 `true`
2. framework 校验:`_plan_summary.md` 存在 + `self_check.plan_mode_used == true` → PASS,否则 REWORK

**完成判据**:
- [ ] `self_check.plan_mode_used: true`
- [ ] framework 校验通过(否则 REWORK)

---

## 📌 与真实 EnterPlanMode 的对比

| 维度 | 真实 EnterPlanMode | 本文件(模拟) |
|------|---------------------|--------------|
| 触发方式 | IDE 用户主动调用工具 | LLM 自检 Read 本文件 |
| Context 段 | LLM 自动生成 | `_plan_summary.md` 顶部必填 |
| Plan 输出 | 系统 Prompt 注入到 IDE | `_plan_summary.md` 落盘 |
| 验证 / 风险 | plan 文件末段固化 | 本文件 Step P.5 段 |
| 退出校验 | ExitPlanMode 工具 | framework 校验 `_plan_summary.md` |
| 强制力 | IDE 拦截 Edit | framework REWORK |
| **限制** | sub-agent **不可用** | **本文件是 fallback** |

---

## 🚨 反模式(LLM 常见走流程陷阱)

- ❌ **走过场式 plan**:只 Read 本文件 1 次,打勾 = `true`,但内容空洞
- ❌ **1 个候选 mod**:候选表只 1 行,看似合规实际逃避对比
- ❌ **复制上次 plan**:R{N} 的 plan 复制 R{N-1} 的开头,只改 mod 列表
- ❌ **跳过反例假说**:只预测"能修什么",不预测"会破坏什么"
- ❌ **历史 mod 不读**:round > 1 时不 Read `skill_diff_round_{N-1}.md`,直接出新 mod

---

## ✅ 落盘前必跑自检 bash

```bash
python3 -c "
import re, os
content = open('{cand_dir}/_plan_summary.md').read()
round_num = int(os.environ.get('ROUND_NUM', '1'))
# P.0 Context 段
assert '现状' in content and '问题' in content and '预期' in content, 'P.0 Context 段缺字段'
# P.1 不做什么
n_exclude = len(re.findall(r'^-?\s*(❌|不)', content, re.MULTILINE))
assert n_exclude >= 3, f'P.1 排除项数 {n_exclude} < 3'
# P.2 候选 mod ≥ 3
n_candidates = len(re.findall(r'^#? \| [ABC]\s*\|', content, re.MULTILINE))
assert n_candidates >= 3, f'P.2 候选 mod 数 {n_candidates} < 3'
# P.3 历史 mod 决策(round > 1)
if round_num > 1:
    assert '上轮 mod 决策矩阵' in content or '决策矩阵' in content, f'round={round_num} 缺 P.3 决策矩阵'
# P.4 反例假说
assert '反例' in content or '风险 case' in content, 'P.4 缺反例假说段'
# P.5 验证/风险/批准
assert '验证' in content and '风险' in content and ('批准' in content or '决策点' in content), 'P.5 缺验证/风险/批准决策点'
print('FOUND: plan-mode 7 步合规')
"
```

**违反任一项 → framework 强制 REWORK**(同 `overall_pass: false` 行为)。