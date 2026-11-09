---
project_id: pr-security-reviewer
project_name: "PR Security Reviewer"
project_version: "1.0.0"
spec_type: agent
input_source: agentgenesis
created: "2026-09-29"
last_updated: "2026-09-29"
---

# PR Security Reviewer — Proposal

## What This Is

一个 PR 审查 Agent：读取 git diff，按**安全、性能、可维护性**三个维度做静态审查，产出固定 JSON Schema 的结构化报告。安全维度的所有 CWE/OWASP 引用必须来自内置规则库（`.claude/rules/owasp-top10.md`），**禁止凭记忆编造**。发现 critical/high 级别问题时暂停，等待人工确认后才写入最终报告。

## Core Value

- **可溯源的安全结论**：每个安全发现引用规则库原文条款 + 具体代码行证据，杜绝"AI 幻觉 CWE 编号"
- **零风险审查**：只读审查，唯一写入对象是报告本身——可以安心授权它审任何仓库
- **CI 可消费**：输出通过 JSON Schema 校验，severity 分级可直接映射 CI 卡点规则

## Context

面向开源维护者与企业研发团队。当前人工 PR 审查的痛点：安全维度依赖个人经验、审查结论格式自由无法自动化、通用代码助手"边审边改"的行为在团队场景不可接受。

## Constraints

- **知识边界 (CD3)**：CWE/OWASP 引用只准来自 `.claude/rules/owasp-top10.md`；规则库未覆盖的疑点标注 `unverified`，不编造编号
- **安全约束 (CD2)**：禁止修改被审仓库任何文件；禁止执行被审代码；报告中的密钥样本脱敏
- **交互约束 (IH3)**：critical/high 发现必须经用户确认后进入最终报告
- **输入门禁 (CD1)**：仅接受 git diff 文本 / 分支比较；非 git 环境明确报错

## Requirements

- R1: 解析统一 diff 格式，按文件/ hunk 结构化变更点
- R2: 三维度审查（安全/性能/可维护性）由独立 SubAgent 并行执行，各自 context 隔离
- R3: 安全维度引用 `.claude/rules/owasp-top10.md`（OWASP Top 10 + CWE 映射清单）
- R4: 输出 `.claude/schemas/review-report.schema.json` 校验通过的 JSON 报告
- R5: critical/high 发现触发 AskUserQuestion 确认；用户驳回的 finding 标记 `dismissed`
- R6: 复用 Skill：`parse-git-diff`（diff 结构化解析）

## Roadmap

- v1（本次交付）：本地 diff 输入、三维审查、Schema 报告、高危确认
- v1.1：增量审查（与 base 分支比较）、报告 Markdown 双输出
- v2：GitHub PR 链接直取、与 CI 卡点规则模板集成
