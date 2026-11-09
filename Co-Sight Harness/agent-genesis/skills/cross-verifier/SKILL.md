---
name: cross-verifier
description: "独立验证 SubAgent 产物的工具。禁读被验证 SubAgent 的 final message/working notes；只看产物文件本身，给 PASS/FAIL。触发：任何 SubAgent X 声明 verdict=PASS 后。"
---

# Cross Verifier

## 触发条件

任何 SubAgent X 声明 `verdict=PASS` 之后，自动调 Y（即本 Skill 的执行实例）独立验证 X 的产物。

## 知识依赖

### references/
- `references/attack-patterns.md` — 4 SE-domain adversarial attack patterns（来源: verifier_patterns.md, math-olympiad）
- `references/adversarial-prompt-templates.md` — 7 adversary prompt templates（来源: adversarial_prompts.md, math-olympiad）

## 硬约束（必须遵守）

### forbidden_inputs

- ❌ X 的 final message（任何形式）
- ❌ X 的 working notes
- ❌ X 提到的 reasoning 链、thinking blocks
- ❌ X 的反思 / 自评段落

### required_inputs

- ✅ X 声明的产物文件路径（实际磁盘文件）
- ✅ 原始需求（`clarified-agent-requirements.yaml` 或对等物）
- ✅ 上游产物的核心字段（用来 cross-check 一致性）

### 工具白名单

| 工具 | 允许 | 用途 |
|------|:----:|------|
| Read | ✅ | 读产物文件 |
| Grep | ✅ | 关键 schema 字段检索 |
| Glob | ✅ | 列产物目录 |
| Bash | ⚠️ | 只允许 `wc`、`file`、`sha256sum` 等只读元数据；**禁**调用 X 用过的同类工具 |
| Skill | ❌ | 禁调用 X 类 skill |
| Web tools | ❌ | 不需要 |

## 执行流程

### Step 1: 提取 X 声称的产物清单
- Glob X 产物目录
- 列出所有声称产出文件

### Step 2: 抽样读取
- 对每个核心产物（CLAUDE.md / SKILL.md / phase-2-execution.md 等）：
  - Read 文件最前 50 行 + 最后 50 行
  - Grep 关键 schema 字段（cross-ref to upstream needs）
  - 验证必需字段存在（如 SCHEMA 必填字段）

### Step 3: 给 verdict

| Verdict | 含义 | 处理 |
|---------|------|------|
| PASS | X 产物符合需求，下游可消费 | 继续 |
| FAIL | 至少 1 个产物不符合需求（含具体缺失项）| 阻断，escalate |
| INCONCLUSIVE | 信息不足需 human 介入 | 报告用户 |

### 多验证者并行（Multi-Verifier Parallel）

对于高关键性产物（`criticality: high`），可启动 N 个 Y 实例并行独立验证同一产物。所有实例遵守相同的 forbidden_inputs 约束（互不读对方的 working notes / final message），物理隔离上下文空间。

- **并行实例数**: N（默认 3，高关键性产物推荐 5）
- **非对称投票**: 
  - `confirm_threshold`: 至少 N-1 个实例 verdict=PASS 时整体判定 PASS
  - `refute_threshold`: 至少 2 个实例 verdict=FAIL 时整体判定 FAIL
  - 其他情况 → INCONCLUSIVE（鸽巢退出）
- **最大轮次**: 3（超过后强制 INCONCLUSIVE → escalate）
- **来源**: math-olympiad asymmetric voting（4-confirm/2-refute，鸽巢退出机制）

## 输出格式

`work/{name}/{phase}-cross-verify.yaml`:

```yaml
verify_target: X-agent-name
verify_time: ISO-8601
inputs_used:
  - "产物文件路径列表 (5-15 个)"
inputs_not_used:
  - "X final message (forbidden)"
findings:
  - file: "..."
    check: "..."
    verdict: PASS | FAIL
    evidence: "..."
    confidence: 0.0-1.0  # 验证者对本次判断的信心度
    attack_pattern: "pattern_id"  # 可选，若通过攻击模式发现，标注模式ID（来源: references/attack-patterns.md）
overall: PASS | FAIL | INCONCLUSIVE
```

## 一致性矩阵（与 X 报告交叉）

| X 报告 | Y 验证 | 处理 |
|--------|--------|------|
| PASS   | PASS   | outcome=verified |
| PASS   | FAIL   | outcome=blocked，escalate |
| FAIL   | PASS   | outcome=blocked，需 human 复审 |
| FAIL   | FAIL   | outcome=verified（一致地失败）|

## 与 V2 机制对应

- M3 — Cross-Verification anti-complicity（V2 §三 机制 3）
- 目的：在物理上切断 final summary 流向验证者
- 来源分析：`ROOT-CAUSE-ANALYSIS.md` §一 原因 3（SubAgent 信息级联信任）；`AGENTGENESIS-FEEDBACK.md` §A6

## 非对称投票配置

高关键性产物使用多验证者并行时的投票配置（来源: math-olympiad asymmetric voting）：

```yaml
verifier_config:
  parallel_count: 5           # N 个 Y 实例并行独立验证
  confirm_threshold: 4        # 至少 N-1 个 PASS → 整体 PASS
  refute_threshold: 2         # 至少 2 个 FAIL → 整体 FAIL
  max_rounds: 3               # 最大轮次，超过后强制 INCONCLUSIVE
  pigeonhole_exit: true       # 鸽巢退出：既不满足 confirm 也不满足 refute → INCONCLUSIVE
  context_isolation: true     # 所有实例物理隔离上下文（禁读其他实例的 final message / working notes）
```

**运行时的模型分层配置**（来源: model_tier_defaults.md, math-olympiad）：

| 模型层 | 并行实例数 | confirm_threshold | refute_threshold |
|--------|:---:|:---:|:---:|
| haiku | 7 | 5 | 3 |
| sonnet | 5 | 4 | 2 |
| opus | 4 | 4 | 2 |

> 原则：能力越弱的模型，并行实例数越多以补偿个体判断的噪声。
