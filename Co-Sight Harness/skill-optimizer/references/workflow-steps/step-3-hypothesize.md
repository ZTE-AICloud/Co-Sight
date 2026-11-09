# Step 3: Hypothesize(假设)— 对每个失败 case 形成可测试根因

> **对应 debug-pro Step 3**:形成具体、可测试的根因理论。

## 目标
为每个 unpass case 建「5 维根因卡」,形成可被 Step 5 验证、可被 Step 6 转 mod 的假设。

## 必做动作

### 1. 重新 Read 最新一份 diff 报告

避免一次性 Read 后遗忘,**重新 Read 清单中最新的那份**。

### 2. 每 unpass case 必填「5 维根因卡」

```
case_id: <RAN-xxx>
F1: <分数>(失败)
失败模式: M1-M7 之一
5 维评分:
  主题一致性: ? / 20
  粒度对等性: ? / 20
  主体/视角: ? / 20
  行为/状态: ? / 20
  限定条件: ? / 20
根因假设:
  gold 三列(用户/场景/问题): <...>
  LLM 三列(用户/场景/问题): <...>
  失分列: <列名>(gold=<...> vs LLM=<...>)
可测试 mod 方向: SKILL.md 加<...> / scripts 加<...>
```

### 3. 多假设对比(2026-07-31 新增)

为每个 case 列**至少 2 个候选假设**,不只 1 个:
- 假设 A:5 维评分指向的主因
- 假设 B:另一维度可能失分(如:RAN-4988439 用户列错配也可能是场景列错配)
- 假设 C(如有):流程触发问题(mod 改的不是内容而是触发条件)

每个假设附 `likelihood`(高/中/低)+ evidence(具体引用 result_diff_report 行号)。

## 硬约束

- 每条根因假设**必须可测试**(Step 5 才能 verify)
- `risk_evidence` 字段必须引用 `result_diff_report.md` 第 N 段的具体 case_id + 列名
- ❌ 禁止只列 1 个假设就跳 Step 6 — 写不进 `multi_hypothesis_compared` 字段

## 失败处理

如某 case 没有 diff_notes 引用 → 标记 `insufficient_evidence`,**禁止**生成 mod,留待下轮再探查。