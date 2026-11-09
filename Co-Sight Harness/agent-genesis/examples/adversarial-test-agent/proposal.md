---
project_id: adversarial-test-agent
project_name: "Adversarial Test Agent"
project_version: "1.0.0"
spec_type: agent
input_source: agentgenesis
created: "2026-09-29"
last_updated: "2026-09-29"
---

# Adversarial Test Agent — Proposal

## What This Is

一个**对抗式测试生成 Agent**：`test-writer` 与 `mutation-critic` 两个 SubAgent 在多轮循环中互相博弈——写手生成测试，批评家注入真实变异体（边界翻转、运算符互换、条件取反……）并运行测试，存活的变异体被打回写手强化，直到连续 2 轮零存活。交付的不只是测试套件，还有可审计的**击杀率报告**。

## Core Value

- **对抗出质量**：单 AI 一锤定音的测试生成没有质量机制；这里测试必须"通过战斗检验"——每个存活的变异体都是实证的责任单
- **可审计**：每轮的变异体清单、击杀记录、存活原因全程留痕（round-report.json），测试有效性是数据而不是感觉
- **零风险**：变异体只运行在沙箱副本中，你的源码树逐字节不变

## Context

行覆盖率无法度量断言强度。弱断言测试（只调函数不断言、只测 happy path）覆盖率漂亮但对回归保护为零。人工变异测试（mutation testing）效果好但配置重、算子枚举靠经验。本 Agent 把"生成"和"检验"拆给两个互不见面的专家，用博弈循环替代一次性生成。

## Constraints

- **博弈隔离 (G1)**：writer 与 critic 双向过程隔离——writer 只见存活变异体报告（不见变异设计），critic 只见测试代码（不见写手思路）；双方 forbidden_inputs 互相列入
- **沙箱安全 (CD2)**：变异体仅应用于 `work/mutation-sandbox/` 副本；`scripts/mutate.py` 层强制路径校验，拒绝作用于源码树；critic 的 settings deny 源码树写路径
- **知识边界 (CD3+K2)**：pytest/unittest API 语义以 `.claude/rules/pytest-api-notes.md` 为准，禁止凭记忆编造 API（HC-01 配对校验 ✓）
- **确定性操作脚本化**：变异注入与测试执行由 `scripts/` 完成（AST 变换 + 真实测试运行器），LLM 不做"看起来对"的判断
- **收敛上限**：max_rounds=5，未收敛输出 partial + 未击杀清单，不静默截断

## Requirements

- R1: FSM 轮次循环：WRITE → MUTATE → EVALUATE → (CONVERGED | NEXT_ROUND)，状态持久化可断点恢复（SM1）
- R2: 两个 SubAgent 独立 context + 双向 forbidden_inputs（G1 博弈机制）
- R3: 算子目录（K4）：boundary-flip / arithmetic-swap / negate-condition / remove-call / constant-tweak / off-by-one，含适用信号
- R4: 真实运行：critic 必须用 `scripts/run_tests.py` 执行测试，禁止"目测通过"
- R5: DF1 输出：`mutation-report.schema.json`（每轮 kill/survive、最终击杀率、未击杀清单）
- R6: IV1 进度：每轮输出一行 `[round N] kill 6/8 (streak=1)` 式进度

## Roadmap

- v1（本次交付）：Python 单模块对抗循环、AST 变异引擎、pytest/unittest 双运行器
- v1.1：多模块/包级测试、增量模式（对已有测试套件做对抗强化）
- v2：JS/Go 算子插件、CI 模式（mutation-score 阈值卡点）
