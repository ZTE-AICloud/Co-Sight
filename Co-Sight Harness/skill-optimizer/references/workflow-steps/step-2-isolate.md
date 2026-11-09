# Step 2: Isolate(隔离)— 并发 Read 历史 rounds diff,二分定位

> **对应 debug-pro Step 2**:缩小范围,用 `git bisect` 类比 — 对比历史 rounds diff,二分定位「哪个 case 在哪一轮开始失败/恢复」。

## 目标
跨轮建 3 类 case 清单 + mod 经验卡,为 Step 4 跨轮追溯打基础。

## 必做动作

**`Read`**:「📜 必读历史数据」清单中**每一轮的两份**(user prompt 顶部已按 round 升序列出,含 baseline)— **必读,不许只读一份、不许只读一类**:
- 每轮 **改动**(`round_K/skill_diff_round_K.md`)+ **结果**(`result_diff_report_*.md`)配对读

### skill_diff_round_*.md 的真实结构(避免误读)

skill_diff 是 **unified diff 格式**(`---` 删除 / `+++` 新增 / `@@ -行号,行数 +行号,行数 @@`),按 Skill 分段,每个 Skill 文件独立显示 diff:
```
## Skill: 问题域场景分析-用户需求分析汇总
- added: 21, removed: 3, changed_lines: 24

### SKILL.md
```diff
--- before/.../SKILL.md
+++ candidate_1/.../SKILL.md
@@ -44,11 +44,18 @@
- 旧内容
+ 新内容
```

无变更的 Skill 显式标记 `_(无变更)_`,不要误以为是"文件不存在"。
**`_read_audit.json` 必须记录每个 Skill 的改动行数**(added/removed/changed_lines)。

### 🆕 单轮对照分析(在跨轮对比前必走)

对**每一轮**(从 baseline 起按升序,逐轮处理),**同一个 message 内并发 Read 该轮的改动+结果**,回答两个问题:
1. **哪条 mod 救了哪个 case**(该轮 mod 段落 → 哪个 case 分数从 0/N 升到高分)
2. **哪条 mod 害了哪个 case**(该轮 mod 段落 → 哪个 case 分数从高分跌到 0/N)

输出:**该轮的"mod ↔ case"映射表**(mod 文本 + 触发 case + 净影响)。
**没有这张映射表就建不出跨轮的"复用/拒绝"依据** —— 单轮对照是 Step 4 之前必经的一步。

### 跨 round 二分对比

在单轮对照分析之后,建立 3 类 case 清单:
- **反复失败 case**(连续多轮 < 60) → Skill 难以处理的固有问题,mod 必针对它设计
- **波动 case**(某轮满分 → 某轮 0) → Skill 在某些场景下脆弱,可能 mod 误伤
- **稳定满分 case**(连续 ≥ 90) → 无需再加 mod,避免 `non_target_cases_risk`

### mod 经验分类

- **有效 mod**:历史某轮后某 case 分数持续上升 → 复用其模式
- **失效 mod**:历史某轮后某 case 分数下降 → **拒绝重复**

## 硬约束

- **禁止凭印象或历史记忆代替 Read**(user prompt 主约束)
- 跨轮对比必须先有"单轮 mod↔case 映射表",否则后续 mod 经验卡无依据

## 失败处理

如发现 case 既不在"反复失败"也不在"稳定"也不在"波动" → 标记 `unclassified`,需要再读一轮 diff 报告确认。