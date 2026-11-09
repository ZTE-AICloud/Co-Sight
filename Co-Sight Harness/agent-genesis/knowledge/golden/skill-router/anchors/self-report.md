---
mode: create
skill_or_agent_name: skill-router
anchored_mode: W2-Router
summary:
  verdict: PASS
  file_counts:
    generated: 4
revision_rounds: 0
---

# self-report（skill-router 过程锚, derived）

> derived: true——外部启发过程锚（策展人按改造后资产撰写）, 非真实构建
> 产物。本报告对应 G0 试抽批次六步全程（§3.5）。

## 重塑裁定（粒度——G2 批同类裁量先例）

**裁定：源为 8-Skill 插件集 → 提炼重塑为单 Skill 包。**

理由：池教的是"路由与分发"模式的形态与机制，不是源项目的业务功能。
8 个业务 Skill（think/check/hunt/read/write/learn/health/design）是源
项目的实现选择；模式本质是四机制（阶段分路路由表、特异性消歧、手动
链式、fat-vs-script 决策框架），由单 Skill + 3 件 L3 参考即可完整承载。
保留 plugin 多 Skill 形态只会把"业务功能清单"误当"模式知识"教给
builder。G2 批遇同类多能力源项目时按此先例：提炼模式机制，不搬业务
清单。

## 六步留痕

1. 选件：源库 complete 档 waza（fast lane 相关性排序入选首批 5 包）。
2. 重映射：pattern_mapping 旧词汇 → 现行词汇（源文档已用现行 W2-Router
   词汇，无漂移项需重译；IH1/K4/CD1/DT1 均为现行 id，照收）。
3. 挂靠：mode_id=W2-Router（货架位）, anchor_fit=real——RESOLVER 即
   W2-Router 纯正实现，非强制贴合。
4. 重塑：按 skill 线形态（SKILL.md + references/ L3）重写四机制；
   清洗标识（源项目名/作者/输出标记/项目内 Skill 名全部移除，通用化
   为目标能力名）；文件自有命名（routing-table / disambiguation-rules /
   fat-vs-script）。
5. 补锚：本 build-plan + 本 report，derived: true。
6. 准入：§3.4 流程，G028 skill-build 档 failures=0。

## 交付描述

单 Skill 包：主件 SKILL.md（四机制 + When to Use + Execution Steps +
Not for）+ 3 件 L3 参考（路由表骨架/消歧规则集/决策框架）。全部内容
为重塑后自有表述，无源项目标识残留。
