---
description: 退出 AgentGenesis 开发模式 — 恢复自修改守卫（S-06）写保护
allowed-tools: Bash(rm:*)
---

删除 `.claude/DEV_MODE` marker，`hooks/guard-self-modify.py` 重新拦截对插件自身代码的 Write/Edit。

日常运行 pipeline 时应保持此状态。

执行: `rm -f .claude/DEV_MODE`
