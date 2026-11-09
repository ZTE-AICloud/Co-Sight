---
decision_id: matching-adversarial-test-agent-v1
timestamp: "2026-09-29"
pipeline: agent-creation
input: clarified-agent-requirements.yaml (task_mode: iterates_and_judges, confidence: 90)
---

# Pattern Matching Decision — adversarial-test-agent

## Tier 0: MN 判定

**判定: MN-Deterministic**

- 轮次循环结构固定（WRITE→MUTATE→EVALUATE→收敛判定），收敛条件可判定（survivor==0 连续 2 轮）
- 边界指引校验："复杂不等于探索性"——单步内的生成判断（写测试/选算子）不改变流程的确定性本质
- Tier 1 子集: [W1, W2, K2, K4, IH1, IT1-Optional, DT1, G1, DF1, CD1, CD2]

## Tier 2: 子域精细匹配

| 子维度 | 选中模式 | confidence | indicators | rationale |
|--------|---------|:----------:|-----------|-----------|
| 工作流 | **W2-FSM** | high | "对抗循环直至连续 2 轮 0 存活"、异常流"5 轮未收敛 → partial" | 轮次循环是显式状态机：WRITE → MUTATE → EVALUATE → {CONVERGED \| NEXT}，迁移条件全部可判定。状态表见 CLAUDE.md §五 |
| 拓扑 | **W4-LeaderWorker** | high | "Leader 判定收敛"、worker=writer/critic | Leader（主 Agent）拥有收敛判定权与资源调度权；worker 无跨任务通信，全部经 Leader 中转 |
| 审查 | **G1-Review-Gate（博弈语义）** | high | "互不见对方过程产物"、双向 forbidden_inputs | 本决策的最大卖点：G1 在此不是"事后审查"，而是**实时博弈机制**——critic 的存活报告是打回 writer 的否决票，writer 的强化测试是反驳。双方不知道对方策略，防止合谋过拟合 |
| 状态 | **SM1-FSM-Checkpoint** | medium | "每轮结束即写 round-state.yaml，kill 后可恢复" | 5 轮循环属长任务，每轮为 checkpoint 单元；恢复语义 = 读 round-state 跳过重放已完成轮 |
| 数据校验 | **DF1-Schema-Enforced** | high | "可审计的击杀率报告"、R5 | mutation-report.schema.json 为最终契约 |
| 约束-安全 | **CD2-Safety-First** | high | "用户源码零改动"、沙箱副本 | 双保险：脚本层路径强制 + settings deny |
| 约束-输入 | **CD1-Input-Gate** | medium | "指定目标模块" | 输入必须是可导入的单模块路径；不可导入/超 300 行 → 明确报错 |
| 知识 | **K4-Rules-Driven**（算子目录） | high | "边界翻转、运算符互换、条件取反"枚举 | 变异算子是内置规则资产（.claude/rules/mutation-operators.md），critic 选题必须引用条款号 |
| 知识边界 | **CD3-Knowledge-Boundary** | medium | "禁止凭记忆编造 pytest API" | 与 **K2**（.claude/rules/pytest-api-notes.md）配对满足 HC-01。边界域：测试框架 API 语义 |
| 交互 | **IH3-Plan-Approval** | medium | "人工批准后测试写入用户 tests/ 目录" | 收敛后、落盘前一次性审批（非每轮打断，不打断对抗节奏） |
| 工具策略 | **IT1-Enforced** | high | "必须用 scripts/run_tests.py 执行，禁止目测通过" | 测试通过与否是确定性事实，只允许脚本裁决 |
| 进度 | **IV1-Progress-Streaming** | high | "每轮输出一行进度" | `[round N] kill 6/8 (streak=1)` 式流式汇报 |
| 确定性命令 | **scripts/ 独立执行** | high | "AST 变异引擎"、R4 | 变异注入/测试执行/存活判定全部为 scripts/ 内确定性逻辑（DF-M4），LLM 只做生成与策略 |

**未选中（有理由拒绝）**:
- W1-Pipeline：核心循环带条件回边，W2 更准确；W1 仅描述轮内步骤序
- W5-Adaptive：轮次结构静态，无运行时拓扑自适应
- E1-E3 自进化：无运行时自修改需求；算子目录演进走版本发布
- IH1：被 IH3 显式覆盖（交付落盘需批准）
- K3：无检索语料；算子是封闭规则集（K4）

## Multi-Agent 拓扑（博弈结构）

```
                ┌────────────── 博弈隔离线 ──────────────┐
                │                                       │
  Main (Leader) │   test-writer        mutation-critic  │
    │ 收敛判定   │   tools: R,W,G,G     tools: R,W,G,G,B │
    │ 调度      │   只见: 存活报告       只见: 测试代码    │
    │ round-state│  不见: 变异设计       不见: 写手思路   │
                │                                       │
                └───────────────────────────────────────┘
   中转协议：writer◀──survivor report──Leader──test code──▶critic
```

双向 forbidden_inputs：writer 禁读 `mutation-sandbox/` 与 critic draft；critic 禁读 writer 的 `test-draft-notes.md`。

## 硬约束校验（HC-01~HC-06）

- HC-01: CD3 与 K2 配对 ✓（pytest-api-notes.md 随 Agent 分发）
- HC-02~HC-05: N/A（无 E 链 / W5）✓
- HC-06: G1×CD2 无互斥；W2×W4 为叠加关系（FSM 状态内的 LeaderWorker 执行）✓

## 置信度

整体 confidence: **high**（循环语义与收敛条件完全明确；唯一 medium 点是 CD3 范围裁剪，已在边界指引内）
