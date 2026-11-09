# Step 4: Instrument(仪器化)— 跨 rounds 追踪 mod ↔ case 映射

> **对应 debug-pro Step 4**:加日志/断点。对应到 Skill 优化 = 跨 rounds 建立「mod 改动 → case 分数变化」映射。

## 目标
基于 Step 2 的历史 rounds diff 对比,填「mod 经验卡」,为 Step 5 副作用预测打基础。

## 必做动作

### 数据源必须配对

某轮的 `round_K/skill_diff_round_K.md`(unified diff,能看到 mod 原文)
+ 该轮的 `result_diff_report_round_K.md`(每 case 4 段:gold / LLM / diff_notes / 资源消耗)。

**只有分数没有 `skill_diff_round_K.md`,就无法知道是哪条 mod 造成的涨跌 —— 禁止在此步凭印象归因。**

### skill_diff 真实结构(unified diff)

```
## Skill: <skill_name>
- added: 21, removed: 3, changed_lines: 24

### SKILL.md
```diff
--- before/<skill_name>/SKILL.md
+++ candidate_1/<skill_name>/SKILL.md
@@ -44,11 +44,18 @@
- 旧内容
+ 新内容
```
```

每个 Skill 一段,**无变更的 Skill 显式标记 `_(无变更)_`**(不是缺失)。Read 时记录:
- 改了哪些 Skill
- 每个 Skill 的 added/removed/changed_lines 数
- 每个 Skill 改了哪些文件(SKILL.md / scripts/*.py / templates / references/)

### 填「mod 经验卡」

```
mod_X(历史 round_2 改的某段文本,**从 round_2/skill_diff_round_2.md 摘录原文**):
  触发 case 列表: 假设改 case A 的某列 → A 是否真提升?(查 round_2 vs round_1 结果报告)
  副作用 case 列表: 假设改 case A → B/C/D 是否被误伤?(查同上)
  复用价值: 高/中/低(基于历史净效果)
```

## 硬约束

- ❌ 禁止凭印象归因(没有 diff 原文就不能写"是这条 mod 造成的")
- 复用价值判定必须基于**至少 2 轮 diff 报告对比**(否则数据不足以判断)
- 摘录 mod 原文时**直接复制 unified diff 的 `+`/`-` 行**,不要自己改写

## 失败处理

如某轮 `skill_diff_round_K.md` 缺失 → 标记 `no_diff_evidence`,该轮 mod 不能进经验卡。
如某 round 的 skill_diff 全是 `_(无变更)_` → 标记 `no_modifications`,该轮不参与"复用/拒绝"判断。