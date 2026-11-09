# Runtime Adaptation Rules — AgentGenesis 运行时自适应规则

> 来源: CLAUDE.md 九、Runtime Adaptation — 经 Phase 3 架构分层重构提取
> 提取日期: 2026-05-03
> 关联模式: SM1-FSM
> 适用对象: AgentGenesis 运行时的状态恢复、故障分级处理、诊断置信度响应

---

## SM1 状态机自适应

AgentGenesis 的状态机在以下场景需要运行时自适应：

### 1. 部分产物已存在时的状态恢复 (phase_history)

会话中断后重新加载，Main Agent 读取 `work/{target-name}/progress-state.yaml` 的 `phase_history`：

```
load progress-state.yaml
  → 无文件或 phase_history=[] → 从 IDLE 开始
  → phase_history 非空:
      last = phase_history[-1]
      若 last.verdict ∈ {PASS, APPROVED}:
        从 last.phase 的下一状态继续，跳过已完成 Phase
      若 last.verdict == FAIL:
        检查 last.retry_count → 未达上限则重试当前 Phase
      若 last.verdict == REJECTED:
        回到 PHASE_1，retry_count 已记录
```

**恢复决策表：**

| phase_history 状态 | 自适应行为 | 进入状态 |
|-----------|-----------|---------|
| 空或不存在 | 正常启动 | IDLE |
| last=PHASE_0, verdict=PASS | 跳过 Phase 0 | PHASE_1 |
| last=PHASE_0, verdict=SKIP | Phase 0 快速通道（需求清晰） | PHASE_1 |
| last=PHASE_1, verdict=PASS | 跳过 Phase 1 | PHASE_2 |
| last=PHASE_2, verdict=PASS | 跳过 Phase 1-2 | PLAN_MODE |
| last=PLAN_MODE, verdict=APPROVED | 跳过 Phase 1-2 + Plan | PHASE_3 |
| last=PHASE_3, verdict=PASS | 跳过 Phase 1-3 | PHASE_4 |
| last=PHASE_4, verdict=PASS | 跳过 Phase 1-4 | PHASE_5 |
| last=PHASE_5, verdict=PASS | 全部完成 | DONE |
| last.verdict=FAIL, retry_count < 上限 | 重试当前 Phase | last.phase |
| last.verdict=FAIL, retry_count >= 上限 | 报告用户 | IDLE（等待人工） |
| last.verdict=REJECTED | 回到 Phase 1 | PHASE_1 |
| progress-state.yaml 损坏或不可读 | 重建状态 | IDLE |

### 2. 审查不通过的分级处理

| 不通过原因 | 自适应策略 |
|-----------|-----------|
| 完整性缺失（缺少章节） | 仅补充缺失章节，不重做已通过的章节 |
| 一致性冲突 | 定位冲突源，仅修正冲突字段，不重做整章 |
| 约束违规 | 移除违规内容，标注移除原因 |
| 来源缺失 | 补充来源标注，不重写内容 |
| 多处CRITICAL发现 | 标记整个Spec需要重做，回到PHASE_1重新匹配 |

**分级处理原则：**
- **单点问题**（1-2个CRITICAL）→ 精准修复，仅改问题点
- **系统性冲突**（3个以上相关CRITICAL）→ 重做相关章节
- **结构性缺陷**（多处CRITICAL分散在多个章节）→ 回到PHASE_1

### 3. 诊断模式的发现分级

| 诊断置信度 | 自适应策略 |
|:------:|-----------|
| high | 直接输出修复建议，等待用户确认执行 |
| medium | 输出诊断结果 + 替代可能性，请求用户提供更多信息 |
| low | 输出初步分析，建议用户进行人工排查 |

**置信度判定依据：**

| 条件 | 对置信度的影响 |
|------|:------:|
| causal_chain 中所有节点均匹配症状 | + (升高) |
| 单个 failed_pattern 能解释所有症状 | + |
| 多个模式都能部分解释症状 | - (降低) |
| 症状与 causal_chain 仅部分匹配 | - |
| 用户提供的信息不足以排除替代解释 | - |

---

## 不可自适应的情况

以下情况必须停止，不可自适应。AgentGenesis 应进入 IDLE 状态并请求人工介入：

1. **知识库文件损坏或缺失**
   - catalog/matcher/assembler/diagnoser 任一文件不存在或 YAML 无法解析
   - 无降级策略——这是核心能力来源

2. **用户需求在澄清后仍无法映射到任何模式**
   - 经过了完整的 IH2 澄清流程后，27个模式中仍无任何模式能覆盖核心需求
   - 这是需求超出当前知识边界的情况（CD3）

3. **匹配结果出现不可调和冲突**
   - 同一子维度两个模式互相排斥但都匹配用户需求
   - 例如：用户需求同时要求「全自动无交互」和「每步等待审批」

4. **SM1 状态机检测到未定义的状态转换**
   - 当前状态 + 触发事件 的组合在状态转换表中无定义
   - 例如：IDLE 状态下直接收到诊断请求（应先进入 DIAGNOSE 而非直接到 DONE）

**停止时应输出的内容：**
```
[AgentGenesis] 检测到不可自适应的情况，已停止：

  原因：{四类之一}
  详情：{具体说明}
  progress_state：已保存至 AgentGenesis-Code/work/{target-name}/progress-state.yaml

  建议：{人工介入方向}
```
