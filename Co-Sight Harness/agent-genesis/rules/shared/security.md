# Security Constraints — AgentGenesis 安全约束

> 来源: CLAUDE.md §四 SAFETY CONSTRAINTS (S-01~S-13)

## Hard Constraints

| # | 约束 | 强度 |
|:--:|------|:--:|
| S-01 | 禁止修改 knowledge/ 和 skills/ 已有文件 | Hard |
| S-02 | 禁止跳过审查 (Phase 2) 或 Plan Mode | Hard |
| S-03 | 禁止低置信度模式赋予高优先级 | Hard |
| S-04 | 禁止未经确认修改知识库 | Hard |
| S-05 | 禁止编造 catalog 外的设计模式 | Hard |
| S-06 | 自身代码受 Hook 写保护，/dev 解锁 | Hard |
| S-07 | Main Agent 禁止替代 SubAgent 执行 Phase 任务 | Hard |
| S-08 | Plan 必须 APPROVED 后进入 Phase 3 | Hard |
| S-09 | Agent 必须通过 Phase 5 评估才能 DONE | Hard |
| S-10 | E2 allowed_scopes 外修改 → Escalation Gate | Hard |
| S-11 | E3 修改前必须 snapshot | Hard |
| S-12 | E2/E3 修改不得绕过 G1 | Hard |
| S-13 | 自进化 Agent 禁止修改自身 Safety Constraints | Hard |

## 密钥管理
- 禁止在源代码中硬编码密钥
- 必须使用环境变量或密钥管理器
- 启动时验证所需密钥存在
