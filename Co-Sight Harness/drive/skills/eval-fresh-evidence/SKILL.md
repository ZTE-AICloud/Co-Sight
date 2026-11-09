---
name: eval-fresh-evidence
description: "Use when verifying completion claims after task execution and needing PASS/FAIL/INCOMPLETE verdict with fresh evidence (no 'should work' / 'probably' / 'seems to'). Activated by evaluator during Stage 4."
user-invocable: false
---

# Evaluation: Fresh Evidence + 3 Layers + 5-Axis

## 模式定义

drive Eval 阶段做 **3 层评测**：

| 层 | 评估对象 | 评估方法 | 置信度 |
|---|---------|---------|--------|
| **L0 规则** | 文件存在 / 格式 valid | 确定性 shell | 100% |
| **L1 Lint/格式** | markdownlint / eslint / tsc | 确定性 shell | 100% |
| **L2 语义** | AC | LLM Judge + 5-axis rubric | 0-100% |

最终 verdict = L0 AND L1 AND L2 综合判断（PASS/FAIL/INCOMPLETE）。

## 使用规则

### 1. Fresh Evidence 原则

**"It should work" is not verification.** Fresh test output / clean diagnostics / successful builds 是唯一可接受的证明。

**禁止措辞**：should work / probably / seems to / 应该 / 可能 / 看起来

**允许措辞**：

- "AC01 verified: 测试在 `tests/test_xxx.py` 通过，输出 `=== output ===`"
- "L0 check failed: `ls` 命令返回 `No such file or directory`"
- "AC02 PARTIAL: 缺少边界 case 测试"

### 2. L0 规则检查

确定性 shell 命令。命令清单见 `references/check-commands.md`。

L0 结果：PASS / FAIL（附具体命令输出）

### 3. L1 Lint/格式

按项目语言选工具。命令清单见 `references/check-commands.md`。

L1 结果：PASS / FAIL（附 fresh 输出）

### 4. L2 语义评分

#### 4.1 AC 状态

每个 AC 判定为以下之一：

| 状态 | 含义 | 要求 |
|------|------|------|
| **VERIFIED** | test 存在 + 通过 + 覆盖边界 | file:line + 引用 + fresh output |
| **PARTIAL** | test 存在但不完整 | 说明缺什么 |
| **MISSING** | 没有 test | 说明原因 |

#### 4.2 5-Axis Rubric

每个 VERIFIED 的 evidence 满足 5 维评分：

| 维度 | 评分标准 |
|------|------|
| **Accuracy** | 证据真实 |
| **Completeness** | 边界 case 也覆盖 |
| **Clarity** | file:line 准确 |
| **Actionability** | 失败能重试 |
| **Conciseness** | 不过度冗长 |

**5 维评分要 cite**：未 cite 具体文件/行号/输出的维度，score 自动降为 2。

**默认策略**：

- 4 维 ≥ 4 分 + 1 维 ≥ 3 分 → confidence 0.9
- 3 维 ≥ 4 分 + 2 维 ≥ 3 分 → confidence 0.7
- 否则 → confidence 0.5

#### 4.3 evidence 格式

每个 AC 的 evidence 含 `test_file` (file:line) / `test_output` / `artifact` / `artifact_quote` / `five_axis`。格式见 `references/eval-examples.md`。

### 5. verdict 计算

按优先级判定：

1. Verifier critical gap → **FAIL**
2. L0 或 L1 FAIL → **FAIL**
3. 有 AC MISSING → **FAIL**
4. 全部 VERIFIED 且 avg confidence ≥ 0.7 → **PASS**
5. 其余 → **INCOMPLETE**