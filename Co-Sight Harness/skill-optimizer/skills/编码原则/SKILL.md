---
name: 编码原则
description: |
  代码任务自动触发(无需用户@)。写/读/改/重构/调试/分析/解释/审查/优化/补丁/修 bug/加新功能/迁移/合并/提取代码时强制 4 原则(不假设/最少代码/精准修改/目标驱动),避免过度工程、抽象蔓延、扩散式编辑。Use when reading, writing, refactoring, modifying, optimizing, reviewing, patching, debugging, or explaining code. Triggers: code 代码、读 read、看 look、改 modify、写 write、修 bug fix、重构 refactor、解释 explain、调试 debug、分析 analyze、审查 review、优化 optimize、补丁 patch、迁移 migrate、合并 merge、提取 extract、新增 implement、迁移 upgrade、开发 develop、清理 clean up、简化 simplify、抽象 abstract、改进 improve、改进代码 source code、读源码 read source。
license: MIT
---

# Karpathy Guidelines

> **自动触发**: 任何代码相关任务自动加载本 skill(无需用户显式 @)。**显性任务**(用户主动说要做的)与**隐性任务**(用户只是让你"看一下这个文件是干嘛的")同等处理。
>
> **显性触发词**: 重构 / refactor、修改 / modify、改写 / rewrite、优化 / optimize、补丁 / patch、代码审查 / review、简化 / simplify、清理 / clean up、修 bug / fix、改进 / improve、新增 / implement、迁移 / migrate、升级 / upgrade、合并 / merge、拆分 / split、提取 / extract、抽象 / abstract、写代码 / write code。
>
> **隐性触发词**(同等必读): **读** / read、**看** / look、**解释** / explain、**分析** / analyze、**调试** / debug、**理解** / understand、**查** / inspect、**阅读** / review、**读源码** / read source。

Behavioral guidelines to reduce common LLM coding mistakes, derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 📚 详细反例库(必读)

做**任何代码任务前**(显性或隐性),**先打开 [`references/examples.md`](references/examples.md) 查看与当前任务最相关的 do/don't 真实代码对比**。该文件包含 4 原则的真实反例:

- **§1 Think Before Coding** — 隐藏假设、默默选择解释、过度泛化的反例
- **§2 Simplicity First** — 30+ 行 setup 才算出简单结果的"过度工程"反例
- **§3 Surgical Changes** — 大改相邻代码、不必要的扩散式编辑的反例
- **§4 Goal-Driven Execution** — 没有成功标准、立即乱改的反例 + 正确的"先写测试 → 验证 → 修复"循环示例
- **§Anti-Patterns Summary** — 4 类反模式的快速对照表

**触发规则:**
- 用户说"重构 / 改 / 优化 / 修 / 简化" → 必读对应章节
- 用户说"读 / 看 / 解释 / 分析 / 调试 / 理解" → 必读 §1(避免默默做假设)
- 用户说"加新功能 / 实现 / 开发 / 添加" → 必读 §4(避免没有验证标准)
- 不确定时 → 读 Anti-Patterns Summary 总览
