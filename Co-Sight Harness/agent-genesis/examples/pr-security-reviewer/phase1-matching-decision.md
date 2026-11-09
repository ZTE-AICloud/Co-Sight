---
decision_id: matching-pr-security-reviewer-v1
timestamp: "2026-09-29"
pipeline: agent-creation
input: clarified-agent-requirements.yaml (task_mode: fetch_filter_rank, confidence: 92)
---

# Pattern Matching Decision — pr-security-reviewer

## Tier 0: MN 判定

**判定: MN-Deterministic**

判定问题（cascading-matcher.yaml Q1-Q4）：
- 输出格式是否预先确定？→ 是（JSON Schema 已指定，DF1）
- 步骤序列是否固定？→ 是（解析 → 三维审查 → 汇总 → 校验 → 报告，W1 串行）
- 是否依赖动态探索/发现？→ 否（审查维度与规则库均已声明）
- 知识来源是否权威文档/规则？→ 是（OWASP 规则文件，K4）

→ 命中 `MN-Deterministic` 的 yes_indicates 组合。Tier 1 子集:
[W1, W2, K2, K4, IH1, IT1-Optional, DT1, G1, DF1, CD1, CD2]

## Tier 2: 子域精细匹配

| 子维度 | 选中模式 | confidence | indicators（用户需求原文） | rationale |
|--------|---------|:----------:|---------------------------|-----------|
| 工作流 | **W1-Pipeline** | high | "按安全、性能、可维护性三个维度审查" → 固定串行/并行阶段 | 审查阶段固定，无状态回溯；MapReduce 语义由 3 个维度 SubAgent 承担（见 Multi-Agent 拓扑） |
| 知识 | **K4-Rules-Driven** | high | "必须引用 OWASP 规则库，不允许凭记忆编造" | 知识以 rules/ 文件形式随 Agent 分发，加载即权威。K2（外部文档锚定）不选：规则库是 Agent 内置资产而非外部检索 |
| 知识边界 | **CD3-Knowledge-Boundary** | high | "不允许凭记忆编造 CWE 编号" | 声明 CWE/OWASP 域禁止 LLM 内嵌知识；违反判定 = 报告中出现规则库不存在的编号。**HC-01 校验：与 K4 配对 ✓** |
| 交互 | **IH3-Plan-Approval** | high | "高危问题时先停下来等我确认" | 关键决策点人工审批。注意：MN-Deterministic 默认倾向 IH1，但需求显式声明审批点 → Tier 2 以需求指示覆盖 cascade 倾向 |
| 约束-安全 | **CD2-Safety-First** | high | "只出报告不自动改代码" | 只读审查 + 写范围限定报告文件 |
| 约束-输入 | **CD1-Input-Gate** | medium | "读取 git diff"（输入形态明确） | 输入校验：仅统一 diff / 分支比较，非 git 环境快速失败 |
| 数据流 | **DT1-Linear-Pass-Through** | high | "读取 git diff → … → 输出 JSON 报告" | diff → findings → report 线性传递，无共享状态回写 |
| 数据校验 | **DF1-Schema-Enforced** | high | "输出固定 JSON Schema 的审查结果" | .claude/schemas/review-report.schema.json 为输出契约 |
| 审查 | **G1-Review-Gate** | medium | "方便 CI 消费"（质量确定性要求高） | 报告写出前过 Schema 校验门禁（确定性校验替代独立 Reviewer，轻量实现） |
| 工具策略 | **IT1-Enforced** | high | "必须引用 OWASP 规则库" | 安全审查必须先 Read rules/owasp-top10.md 再下结论，禁止裸 LLM 判断 |
| 进度 | **IV1-Progress-Streaming** | low | 三维审查耗时可感知 | 每维度完成即汇报一行进度 |

**未选中（有理由拒绝）**:
- W2-FSM：无状态机需求，审查不循环
- K2/K3：知识内置（K4）而非外部文档/检索
- IH1：被 IH3 显式覆盖（见上）
- SM1：单次短任务，无断点恢复需求
- E1-E3 自进化：v1 不需要运行时自修改

## Multi-Agent 拓扑

```
Main Agent (orchestrator)
  ├── Agent: security-reviewer   (K4 规则加载 + CD3 边界 + Bash 禁用于被审仓库)
  ├── Agent: perf-reviewer       (独立 context)
  └── Agent: maintainability-reviewer (独立 context)
```
三个维度审查为无依赖并行（W1 阶段内 MapReduce），汇总后 DF1 校验 → IH3 审批。

## 硬约束校验（HC-01~HC-06）

- HC-01: CD3 与 K4 配对 ✓
- HC-02: 未选 E 链，N/A ✓
- HC-03: MN-Deterministic 与 W4/W5 无冲突 ✓
- HC-04: 未选 E2，N/A ✓
- HC-05: 未选 W5，N/A ✓
- HC-06: 无 incompatible_with 命中 ✓

## 置信度

整体 confidence: **high**（需求 6 维全部明确，无 UNCERTAIN 节点）
