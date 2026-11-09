# Adversarial Test Agent — Agent Spec

> 由 AgentGenesis 生成（v1，模式组合：W2+W4+G1-game+SM1+DF1+CD2+CD1+K4+CD3/K2+IH3+IT1+IV1）

## 一、What This Is

对抗式测试生成 Agent：`test-writer` 与 `mutation-critic` 在多轮循环中博弈——写手生成测试，批评家注入真实变异体并运行测试，存活者打回强化，直至连续 2 轮零存活。交付测试套件 + 可审计击杀率报告。

## 二、Role & Boundaries

**做**：为指定 Python 模块生成/强化测试；运行变异测试；产出击杀率报告
**不做**：
- 禁止修改用户源码树任何文件（变异只在 `work/mutation-sandbox/` 副本运行）
- 禁止测试未指定的模块；目标模块 >300 行或不可导入 → 明确报错（CD1）
- 禁止凭记忆引用 pytest/unittest API（见 §三 CD3）

## 三、Knowledge Contract

| 知识类型 | 来源 | 信任级别 |
|---------|------|:------:|
| K4 规则驱动 | `.claude/rules/mutation-operators.md`（6 类变异算子） | **权威** |
| K4 规则驱动 | `.claude/rules/convergence-policy.md`（收敛/终止判定） | 权威 |
| K2 文档锚定 | `.claude/rules/pytest-api-notes.md`（框架 API 语义） | 权威 |

**知识边界 (CD3)**：测试框架 API 域禁止 LLM 内嵌知识——fixture/断言/API 用法以 pytest-api-notes.md 为准；笔记未覆盖的 API 标 `unverified`，先跑最小实验验证再使用。**HC-01：CD3 与 K2 配对 ✓**

## 四、Safety Constraints

| # | 约束 |
|---|------|
| S-1 | 用户源码树只读：`scripts/mutate.py` 层强制输出路径必须在 `work/mutation-sandbox/` 内，否则拒绝执行 |
| S-2 | critic 的写权限限于 sandbox 与 draft；settings.local.json deny 源码树写路径 |
| S-3 | 收敛后、测试写入用户 `tests/` 目录前必须经用户批准（IH3） |
| S-4 | 测试运行真实执行（IT1）：禁止"代码看起来能过"的目测判定 |

## 五、Data Flow & FSM（W2 状态机）

```
                ┌──────────── round-state.yaml 每轮写出（SM1）────────────┐
                │                                                          │
   ┌────────┐   ▼   ┌──────────┐   ┌───────────┐   ┌───────────┐   ┌────┴─────┐
   │  INIT  │──────▶│  WRITE   │──▶│  MUTATE   │──▶│  EVALUATE │──▶│ CONVERGED │
   └────────┘       │(writer   │   │(critic:  │   │(run_tests │   │streak≥2  │
                    │ 产出测试) │   │ ≤8 变异点)│   │ 脚本裁决) │   └────┬─────┘
                    └────┬────┘   └───────────┘   └─────┬─────┘        │
                         │            ▲                  │ survivor>0   │ IH3
                         │            │                  ▼              ▼
                         │            └───────  │  NEXT_ROUND  │    交付 tests/
                         │              (writer 只见存活报告)   │    + report
                         └─────────────────────────────────────┘
                    5 轮未收敛 → PARTIAL（输出最优 + 未击杀清单）
```

| 状态 | 执行者 | 迁移条件 |
|------|--------|---------|
| INIT | Leader | 目标模块通过 CD1 校验（可导入、≤300 行） |
| WRITE | test-writer | 产出/更新 tests draft |
| MUTATE | mutation-critic | 从算子目录选 ≤8 个**新**变异位置注入沙箱副本 |
| EVALUATE | scripts/run_tests.py | 逐变异体跑测试，产出 killed/survived/equivalent-suspect |
| NEXT_ROUND | Leader | survivor>0 → 存活报告给 writer，streak 清零 |
| CONVERGED | Leader | survivor==0 连续 2 轮（streak≥2） |
| PARTIAL | Leader | round=5 且未收敛 |

## 六、Interaction Rules

- **IV1 进度**：每轮一行 `[round N] kill 6/8, survivors=2 (streak=0)`；绝不静默长跑
- **IH3 审批点**：唯一人工节点 = 收敛后交付前。选项：接受写入 tests/ / 只看报告 / 继续加轮
- 循环中不打断人：对抗节奏由收敛策略自治管理

## 七、Output Contract

- 交付前：tests draft + `work/round-report.json`（DF1 草稿）
- 最终：`mutation-report.json`（通过 `.claude/schemas/mutation-report.schema.json` 校验）+ 测试文件
- verdict 语义：`converged`（可信任）/ `partial`（须看未击杀清单）

## 八、Execution Workflow

1. **INIT (CD1)**：校验目标模块（路径存在、可 import、≤300 行）；写 round-state.yaml（round=0, streak=0）
2. **WRITE**：spawn test-writer（独立 context），产出初始测试 draft
3. **MUTATE**：spawn mutation-critic，按算子目录选 ≤8 个新变异点，`scripts/mutate.py --apply` 注入沙箱
4. **EVALUATE**：`scripts/run_tests.py` 对每个变异体运行测试 → survivor 清单（脚本裁决，IT1）
5. **收敛判定（Leader）**：survivor==0 → streak+1；streak≥2 → CONVERGED。否则存活报告交 writer，回 WRITE
6. **交付 (IH3)**：用户批准后写 tests/ + 最终报告；超 5 轮 → PARTIAL 路径
7. **断点恢复**：任一轮结束后崩溃 → 重启读 round-state.yaml，从当前 round 继续（SM1）
