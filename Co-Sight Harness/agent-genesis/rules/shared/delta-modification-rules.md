# 增量修改规则 — AgentGenesis Optimizer + E3 自进化

> 加载策略: L2 — Agent Spec 增量修改时全量 Read
> 适用: 基于诊断报告对 Agent Spec 执行局部 Delta 修改
> 适用: E3 Delta-Modification 自进化协议的执行层规范
> 依赖: problem-diagnosis-rules.md, knowledge/shared/failure-patterns.yaml, feedback-loop-rules.md

---

## 1. 模式 → 修复映射

从 `knowledge/shared/failure-patterns.yaml` 的 `repair_targets` 加载：

| 失效模式 | 修复目标章节 | 修复方法 |
|---------|-------------|---------|
| CD3 | Knowledge Contract → 知识边界 | 增加"禁止依赖LLM内嵌知识"的领域条目 |
| Hard-Constraint | Safety Constraints → 约束规则表 | 增加一条 Hard 约束 |
| CD2 | Safety Constraints → 安全约束 | 应用 CD2 域模板：声明沙箱类型、网络策略 |
| G1 | Execution Workflow → 审查门禁 | 增加具体审查维度 + 可验证通过标准 + 不通过示例 |
| DF1 | Data Flow → 数据校验规则 + schemas/ | 增加 JSON Schema 文件 + 校验规则声明 |
| K2 | Knowledge Contract → K2 检索策略 | 增加"每个结论引用文档具体段落"要求 |
| K3 | Knowledge Contract → K3 检索策略 | 调整 TopK/阈值/增加多路召回 |
| DT1 | Data Flow → 数据流转图 | 补充缺失的数据实体行 |
| DT2 | Data Flow → 共享状态文件 | 明确每个共享状态文件的维护者和读写权限 |
| IH3 | Interaction Rules → 确认节点 | 在关键决策节点增加 IH3 审批步骤 |
| IV1 | Execution Workflow → 汇报规则 | 增加阶段开始/结束时的汇报格式声明 |
| Context-Collapse | 不修改 Agent Spec | 委托 Delta 修改流程——增量追加而非全量重写 |

---

## 2. 修改原则

### 2.1 最小修改原则

- **只改动与根因直接相关的章节**，不重写整个 Agent Spec
- 修改前先记录当前状态的校验和（`sha256sum`）
- 修改后仅被改动章节有变更

### 2.2 模式内闭合

修改后检查该模式的所有约束自洽：
- CD3 + K2/K3：有"禁止"也有"替代来源"
- G1 + DF1：审查维度覆盖 Schema 校验项
- DT1 + DF1：数据流中有 Schema 声明，Schema 文件存在

### 2.3 跨模式兼容

修改不破坏其他模式：
- 新增约束不与其他已有约束矛盾
- 新增数据实体不破坏已有流转图闭合性
- 新增审查维度不与已有维度重复

### 2.4 Context Collapse 防护

**每次修改范围 ≤ 2 个 Spec 章节**。禁止全量重写。

原因：全量重写时 LLM 倾向于回归到通用模板，丢失历史积累的领域特定细节。
这是从 Haseeb 2025 上下文工程研究和对 AgentGenesis 自身使用经验得出的关键约束。

### 2.5 保留已有内容

- 不删除、不重写与问题无关的章节
- 新增条目追加到已有列表末尾（如约束表、知识源表）
- 修改段落时保留周围的原文内容

---

## 3. 增量修改流程

```
diagnosis_report.md (from Step 8)
    │
    ▼
1. 确认修改范围
   ├── 识别目标章节（≤ 2 个）
   ├── 确认修改类型（追加/替换/新增）
   └── 记录修改前内容 + 校验和
    │
    ▼
2. 执行 Delta 修改
   ├── 如追加：在目标段落后增加新条目
   ├── 如替换：只替换与根因相关的具体段落
   └── 如新增：在合适位置插入新章节
    │
    ▼
3. 模式内闭合检查
   └── 修改后的模式约束是否自洽？
    │
    ▼
4. 跨模式兼容检查
   └── 修改是否破坏其他模式的兼容性？
    │
    ▼
5. 输出 Diff
   └── 三段式 Diff（修改前 → 修改后 + 原因）
```

---

## 4. Diff 输出格式

每次修改输出三段式 Diff：

```markdown
--- 修改前（{{file}}:{{line_range}}）
{{original_content}}
+++ 修改后
{{modified_content}}
=== 原因
{{why_changed}} —— 引用诊断报告的根因假设
```

### 示例

```markdown
--- 修改前（CLAUDE.md:120-125）
## 四、Knowledge Contract
| 知识类型 | 来源 | 信任级别 |
|---------|------|:------:|
| K1 LLM内嵌 | 通用编程知识 | 参考 |

+++ 修改后
## 四、Knowledge Contract
| 知识类型 | 来源 | 信任级别 |
|---------|------|:------:|
| K1 LLM内嵌 | 通用编程知识 | 参考 |
| K2 3GPP规范 | TS 38.211-38.214 | 权威 — 协议参数以此为准 |

**知识边界 (CD3)**:
- 3GPP 协议参数域：禁止依赖 LLM 内嵌知识，必须从规范文档检索
- 违反判定：编造不存在于 3GPP 规范中的参数名或值

=== 原因
诊断报告 DR-001：Agent 编造了不存在的协议参数 "quantumPrecodingFactor"。
根因：CD3 未声明 3GPP 协议域为"禁止依赖 LLM 内嵌知识"。
修复：在 Knowledge Contract 增加 K2 知识源引用 + CD3 知识边界声明。
```

---

## 5. 修改约束检查清单

修改后逐项验证：

- [ ] 修改范围 ≤ 2 个 Spec 章节
- [ ] 未修改章节内容完整保留（校验和一致）
- [ ] 修改后该模式约束自洽（如 CD3 + K2 互补）
- [ ] 跨模式兼容（无新增矛盾约��）
- [ ] Diff 格式完整（修改前 + 修改后 + 原因）
- [ ] Diff 中引用了诊断报告 ID

---

## 6. 禁止操作

- **禁止全量重写** — 不论问题多严重，不重写整个 Spec。如果问题确实需要大改，建议返回 Creator 而非在 Optimizer 中全量重写。
- **禁止跨模式笼统修改** — 如"增强整体安全性"类修改。每个修改必须指向具体的失效模式。
- **禁止不输出 Diff** — 每次修改必须有修改前/后/原因的三段式 Diff。
- **禁止 Context Collapse** — 修改不能退化 Agent Spec 的领域特异性。

---

## 7. E3 自进化触发条件 (E3 Trigger from E2)

### 7.1 触发入口

E3 不自发执行修改。仅在 E2 Controlled-Evolution Step E2.3 下发修改指令时执行：

```
E2.3: 生成 Delta 修改 → 调用 E3 协议
  │
  ├── 输入: E1 gap_analysis + E2 allowed_scopes 确认
  ├── 执行: E3 三段式 Diff 协议
  └── 输出: Delta diff → 返回 E2 继续 Step E2.4 自审查
```

### 7.2 前置条件

E3 执行前必须确认以下条件全部满足：

- [ ] E2 已确认修改在 allowed_scopes 内
- [ ] Snapshot 已创建（见第 8 节）
- [ ] 修改范围 ≤ 2 个 Spec 章节
- [ ] 修改不涉及 Safety Constraints 章节（S-13）
- [ ] 修改不涉及 Evolution Contract 核心规则（allowed_scopes、cycle_max）
- [ ] E1 gap_analysis 提供了具体修改方向的证据

---

## 8. Snapshot 与回滚协议 (E3 Rollback Protocol)

### 8.1 Snapshot 创建

在每次 E3 修改执行前，E2 必须创建 snapshot：

```bash
# Snapshot 目录结构
work/_self/snapshots/{ISO8601_timestamp}/
  ├── original/          # 修改前的原始文件副本
  │   └── CLAUDE.md
  │   └── (其他受影响文件)
  └── manifest.yaml      # Snapshot 元数据
```

**manifest.yaml 格式**:
```yaml
snapshot:
  id: "snap-{timestamp}"
  timestamp: "ISO 8601"
  evolution_cycle: N
  e1_score_before: {weighted_total: N.N, verdict: FAIL}
  target_files:
    - path: "CLAUDE.md"
      checksum_before: "sha256"
  change_summary: "E2 gap_analysis 摘要"
```

### 8.2 回滚触发条件

以下任一条件触发回滚：

1. **E1 退化**: 修改后 E1 重评估分数 ≤ 修改前分数
2. **G1 自审查 FAIL**: E2 Step E2.4 自审查不通过
3. **格式/引用错误**: Phase 4 Check 2/3 级错误被引入
4. **Scope 越界**: 修改后发现实际变更超出了 allowed_scopes

### 8.3 回滚执行

```
回滚触发
  │
  ▼
1. 定位最近 snapshot: work/_self/snapshots/{timestamp}/
2. 恢复所有 target_files: cp original/* → 目标路径
3. 验证 checksum 恢复到修改前值
4. 记录回滚事件到 work/_self/evolution-log.yaml
5. 继续尝试其他允许的修改方向（不回滚整个进化周期）
```

**evolution-log.yaml 回滚记录格式**:
```yaml
rollback_event:
  timestamp: "ISO 8601"
  snapshot_id: "snap-{timestamp}"
  trigger: "E1_degradation | G1_fail | format_error | scope_violation"
  attempted_change: "delta diff 摘要"
  e1_score_after_rollback: {weighted_total: N.N}
```

### 8.4 禁止回滚的例外

- E1 分数从 2.5 退化到 2.3 — 仍应回滚（任何退化都不可接受）
- 修改只影响格式但导致 E1 actionability 降低 — 仍应回滚
- 回滚本身失败 — **阻断**，保留当前状态，Escalation Gate
