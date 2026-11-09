---
pattern_id: E3
pattern_name: Delta-Modification
category: evolution
sub_dimension: delta_modification
selection_rule: "可选。依赖 E2+E1。E2 确认修改可行后，由 E3 执行精确的增量修改。"
solves: "对 Agent Spec 执行精确的增量修改，含回滚保护，防止 context collapse"
fills_spec_section: Evolution Contract
depends_on: [E2, E1]

variables:
  - name: MAX_SECTIONS_PER_CHANGE
    description: "单次修改涉及的最大 Spec 章节数"
    type: number
    source: decision_table
    default: 2
  - name: ROLLBACK_STRATEGY
    description: "回滚策略"
    type: string
    source: decision_table
    enum: ["snapshot", "git-revert", "checksum"]
    default: "snapshot"
  - name: TARGET_SECTIONS
    description: "允许 E3 修改的目标 Spec 章节列表"
    type: list
    source: user_input
    required: true
  - name: SNAPSHOT_DIR
    description: "Snapshot 存储目录"
    type: string
    source: derived
    default: "work/_self/snapshots/"

constraints:
  - "单次修改 ≤ {{MAX_SECTIONS_PER_CHANGE}} 个 spec sections（context collapse 保护）"
  - "修改必须含 Before/After/Reason 三段式"
  - "失败自动回滚到最近 snapshot"
  - "回滚后保留失败记录用于诊断"
  - "不可修改 Safety Constraints 章节（S-13）"
  - "不可修改 Evolution Contract 自身的核心规则（allowed_scopes、cycle_max）"
---

# Evolution Contract — Delta-Modification

## 修改协议

**单次修改上限**: ≤ {{MAX_SECTIONS_PER_CHANGE}} 个 Spec 章节
**回滚策略**: {{ROLLBACK_STRATEGY}}
**Snapshot 目录**: {{SNAPSHOT_DIR}}

## Delta 格式（三段式）

每次修改必须包含以下结构：

```markdown
### Delta-{N}: {简短描述}

**Scope**: {allowed_scope 名称}
**Change Type**: add | modify | remove

**Before**:
```{原始内容}```

**After**:
```{修改后内容}```

**Reason**: {为什么做这个修改——引用 E1 自评分数 + gap_analysis 证据}
**Rollback**: {回滚到此状态的方法}
**Affected Sections**: [{章节名列表}]
```

## 修改粒度

| 粒度 | 示例 | 限制 |
|------|------|:--:|
| L1-参数调整 | 工具参数、阈值、配置值 | 单次可 ≤3 项 |
| L2-步骤修改 | 步骤顺序、拆分、合并 | 单次 ≤2 步 |
| L3-章节替换 | 重写整个 Spec 章节 | 单次 ≤1 章 |

## 回滚协议

```
修改前:
  1. 创建 snapshot: cp {target_file} {SNAPSHOT_DIR}{timestamp}/
  2. 记录 checksum: sha256sum {target_file} >> work/_self/snapshots/checksums.txt

修改后:
  3. 验证 checksum 变化（确认修改已应用）
  4. 执行 E1 重评估

回滚触发:
  - E1 重评估分数比修改前更低
  - G1 自审查 FAIL
  - 修改引入了新的格式/引用错误（Phase 4 Check 2/3 FAIL）

回滚执行:
  1. cp {SNAPSHOT_DIR}{timestamp}/{target_file} {target_file}
  2. 验证 checksum 恢复到修改前值
  3. 记录回滚事件到 work/_self/evolution-log.yaml
  4. 继续下一个允许的修改方向（不回滚整个周期）
```

## 禁止修改列表（Hard）

以下内容即使在 allowed_scopes 中声明也不可修改：
- `safety_constraints` 章节（S-13）
- `evolution_contract.allowed_scopes`（防止自我扩张权限）
- `evolution_contract.evolution_cycle_max`（防止无限循环）
- `frontmatter.pattern_composition`（模式选择属于设计决策，需工厂重建）

---
# Filled Example

### Delta-01: 补充 E305 检测规则

**Scope**: execution_workflow.step_3
**Change Type**: modify

**Before**:
```
pycodestyle --select=E501,W291,E302,E703 {target_file}
```

**After**:
```
pycodestyle --select=E501,W291,E302,E305,E703 {target_file}
```

**Reason**: E1 自评 completeness=2.5 — 漏检了 E305（函数定义后空行不足）。gap_analysis 确认原因是工具调用参数缺少 E305 select。
**Rollback**: 移除 --select 中的 E305 即可恢复
**Affected Sections**: [Execution Workflow — Step 3]

---

### Delta-02: 强化 IT1-Enforced 约束

**Scope**: execution_workflow.step_4
**Change Type**: add

**Before**:
```
（step_4 无校验步骤）
```

**After**:
```
## Step 4b: 工具输出校验
1. 读取 flake8/pycodestyle 工具原始输出
2. 过滤报告中未在工具输出中出现的违规项
3. 标注过滤掉的项的来源（LLM判断 → 降级为"建议"而非"违规"）
```

**Reason**: E1 自评 correctness=4 — 存在 1 个误报（E226 由 LLM 自行判断，非工具输出）。gap_analysis 建议在报告生成前添加工具输出校验步骤。
**Rollback**: 移除 Step 4b，恢复 Step 4→Step 5 的直接流转
**Affected Sections**: [Execution Workflow — Step 4, Step 5 重新编号]
