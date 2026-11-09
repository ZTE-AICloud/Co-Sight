---
description: 进入 AgentGenesis 开发模式 — 解锁自修改守卫（S-06），允许修改插件自身代码
allowed-tools: Bash(touch:*)
---

创建 `.claude/DEV_MODE` marker，解锁 `hooks/guard-self-modify.py` 对插件自身代码的写保护。

仅开发阶段使用；改完插件代码后应立即 `/dev-off` 恢复保护。

执行: `touch .claude/DEV_MODE`
