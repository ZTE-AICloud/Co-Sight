# 问题诊断规则 — AgentGenesis Phase 4a Optimizer 手动模式

> 加载策略: L2 — Agent 执行问题诊断时全量 Read
> 适用: Agent 执行出现异常后的根因定位
> 依赖: knowledge/shared/failure-patterns.yaml（问题模式库）

---

## 1. 诊断流程

```
问题描述 → 匹配问题模式 → 反查设计模式 → 定位 Spec 章节 → 生成根因假设
```

### 1.1 步骤详解

| 步骤 | 动作 | 输入 | 输出 |
|:---:|------|------|------|
| 1 | 提取关键事实 | 用户反馈 + Agent 执行日志 | 结构化症状列表 |
| 2 | 匹配问题模式 | 症状列表 + failure-patterns.yaml | 候选失效模式（1-3 个） |
| 3 | 反查设计模式 | 失效模式 → 对应的设计模式 | 哪些模式约束不足 |
| 4 | 定位 Spec 章节 | 设计模式 → Spec 章节映射 | 受影响的具体章节 |
| 5 | 生成根因假设 | 章节内容 + 模式约束 | 根因 + 修复方向 |

### 1.2 因果推理原则

- **禁止查表式诊断**: 不能仅根据"问题现象"匹配"可能模式"，必须理解 WHY 这个模式失效会产生这个症状
- **复合失效优先**: 同一问题可能涉及多个模式复合失效（如幻觉 = CD3 缺失 + K2 约束不足），不要满足于找到第一个匹配
- **Skill 委托**: 如果根因指向 Skill 质量（而非 Agent 模式），委托 Skill-Builder Optimizer 诊断

---

## 2. 问题模式 → 设计模式映射

从 `knowledge/shared/failure-patterns.yaml` 加载。以下是速查表：

### 2.1 知识完整性问题

| 问题现象 | 失效模式 | 定位 Spec 章节 | 严重度 |
|---------|---------|---------------|:---:|
| Agent 输出知识源中不存在的事实 | CD3 知识边界缺失 | Knowledge Contract → 知识边界 | HIGH |
| Agent 引用正确文档但结论不符 | K2 约束不足（未要求引用段落） | Knowledge Contract → K2 检索策略 | HIGH |
| Agent 检索返回空后自行猜测 | K3 检索策略不当 | Knowledge Contract → K3 检索策略 | MEDIUM |
| Agent 应该检索但没有检索 | CD3 未强制检索 + IT1 Optional | Safety Constraints + 工具策略 | MEDIUM |

### 2.2 流程完整性问题

| 问题现象 | 失效模式 | 定位 Spec 章节 | 严重度 |
|---------|---------|---------------|:---:|
| Agent 跳过某步骤 | W1 约束不足 + Hard 约束缺失 | Execution Workflow + Safety Constraints | HIGH |
| Agent 越权执行不该做的操作 | Role & Boundaries 未落实为 Hard 约束 | Safety Constraints → 禁止操作清单 | HIGH |
| 中间产物丢失，下游报错 | DT1 数据流转图不闭合 | Data Flow → 数据流转图 | MEDIUM |
| 输出格式不符预期 | DF1 Schema 校验缺失 | Data Flow → 数据校验规则 | MEDIUM |
| 多组件状态不同步 | DT2 读写权限不清晰 | Data Flow → 共享状态文件 | MEDIUM |

### 2.3 质量控制问题

| 问题现象 | 失效模式 | 定位 Spec 章节 | 严重度 |
|---------|---------|---------------|:---:|
| 审查总通过但有问题的输出 | G1 审查维度太模糊 | Execution Workflow → 审查门禁 | HIGH |
| 同一 Agent 既执行又审查 | G1 自审叠加规则被忽略 | 检查是否有独立 Reviewer | HIGH |

### 2.4 交互体验问题

| 问题现象 | 失效模式 | 定位 Spec 章节 | 严重度 |
|---------|---------|---------------|:---:|
| 长流程无进度更新 | IV1 Progress-Streaming 缺失 | Execution Workflow → 汇报规则 | LOW |
| Agent 替用户做了决定 | IH3 Plan-Approval 缺失 | Interaction Rules → 确认节点 | MEDIUM |

### 2.5 跨维度问题

| 问题现象 | 根因 | 处理 |
|---------|------|------|
| Prompt 坍缩为简短通用指令 | 全量重写导致历史积累丢失 | Optimizer 强制增量修改 |

---

## 3. 诊断报告模板

```markdown
## 问题诊断报告

**诊断时间**: {{timestamp}}
**问题来源**: {{user_report | execution_log}}

### 症状描述
{{symptom_description}} — 引用用户反馈或执行日志中的原话

### 失效模式
| # | 模式 | 置信度 | 匹配依据 |
|---|------|:---:|---------|
| 1 | {{failed_pattern_1}} | high | {{evidence_1}} |
| 2 | {{failed_pattern_2}} | medium | {{evidence_2}} |

### 根因假设
**主因**: {{primary_root_cause}} — 为什么这个模式失效会产生这个症状
**次因**: {{secondary_root_cause}}（如有）

### 定位章节
| Spec 文件 | 章节 | 当前状态 | 问题 |
|-----------|------|---------|------|
| {{spec_file}} | {{section}} | {{current_state_summary}} | {{what_is_missing_or_wrong}} |

### 修复方向
{{fix_direction}} — 不是具体修改内容，而是修改策略和原则

### 严重度
{{HIGH|MEDIUM|LOW}} — 影响范围：{{impact_scope}}

### 建议下一步
- [ ] 执行增量修改（见 delta-modification-rules.md）
- [ ] 修改后重验证（7 项检查）
- [ ] {{additional_step}}
```

---

## 4. 诊断测试场景

### 场景 A: Agent 编造不存在的协议参数

**输入**: "Agent 在报告中写入了'5G NR 协议定义 PUSCH-Config.quantumPrecodingFactor 参数'，但 3GPP 规范中不存在此参数"

**诊断推理**:
1. 症状：输出知识源中不存在的事实
2. 匹配 failure-patterns.yaml → knowledge_integrity → CD3 (Knowledge-Boundary)
3. 定位 Spec 章节：Knowledge Contract → 知识边界 → 是否声明"协议参数以 3GPP 规范为准"？
4. 根因：CD3 未声明 3GPP 协议域为"禁止依赖 LLM 内嵌知识"
5. 修复方向：在 CD3 知识边界表中新增条目，声明"协议参数必须从 3GPP 规范检索，不得编造"

### 场景 B: Agent 跳过安全审查步骤

**输入**: "Agent 在输出最终报告前没有执行安全审查——跳过了 Phase 2 审查门禁"

**诊断推理**:
1. 症状：跳过审查步骤
2. 匹配 → workflow_integrity → G1 + Hard-Constraint
3. 定位：Execution Workflow → 是否有"禁止跳过步骤"约束？Safety Constraints → 是否有 Hard 规则？
4. 根因：G1 审查门禁约束不足——步骤间无强制前置条件检查
5. 修复方向：增加 Hard 约束 + 每步完成后校验输出完整性

### 场景 C: 中间产物丢失导致下游报错

**输入**: "Phase 3 报告'找不到 analysis-result.json'，但 Phase 2 应该生成此文件"

**诊断推理**:
1. 症状：下游找不到输入文件
2. 匹配 → data_flow_integrity → DT1 (Linear-Pass-Through)
3. 定位：Data Flow → 数据流转图 → 检查 analysis-result.json 是否有声明生产者
4. 根因：DT1 数据流转图不闭合——中间产物有消费者但没有生产者声明
5. 修复方向：补充数据实体行，声明生产者和输出路径
