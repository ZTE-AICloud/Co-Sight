---
pattern_id: DP1
pattern_name: Traceable-Lineage
category: data
sub_dimension: provenance
selection_rule: "可选。叠加到任意数据拓扑(DT1/DT2)之上。"
solves: "输出的每条结论需能追溯到输入来源——用于审计和调试"
fills_spec_section: Data Flow (可追溯性要求)

variables:
  - name: LINEAGE_FORMAT
    description: "溯源标注格式——如：每条结论后追加 [来源: {文件}:{章节}, 推理: {步骤}]"
    type: string
    source: user_input
    required: true
    default: "[来源: {file}:{section}] → [推理: {logic}] → [结论: {conclusion}]"
  - name: UNTRACEABLE_ACTION
    description: "无法追溯到来源的结论的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "标记为[待验证]并附加置信度。待验证项在最终输出中集中列出"
  - name: LINEAGE_SCOPE
    description: "溯源需要覆盖的范围——所有结论 / 仅关键结论 / 仅数据引用"
    type: string
    source: user_input
    required: true
    default: "所有结论"

constraints:
  - "每条结论标注来源、推理路径"
  - "无法溯源的结论标记为[待验证]"
---

# Data Flow — 可追溯性要求

## 溯源约束
- **覆盖范围**：{{LINEAGE_SCOPE}} 均需标注来源
- **标注格式**：{{LINEAGE_FORMAT}}
- **无法溯源处理**：{{UNTRACEABLE_ACTION}}

## 溯源链要求
每条分析结论必须包含以下溯源信息：
1. **来源步骤**：该结论由哪个执行步骤产出
2. **输入来源**：结论依据的输入文件及具体章节/段落
3. **推理路径**：从输入到结论的推理链路（关键转换逻辑）

## 溯源格式示例
```
## 结论
[具体结论内容]

**来源标注**：[来源: 3GPP_38.214.md §5.1.2] → [推理: 基于PDSCH资源分配定义推导] → [置信度: 高]
```

## 待验证项处理
- {{UNTRACEABLE_ACTION}}
- 待验证项不影响整体执行流程，但必须在最终输出中集中列出

---
# Filled Example

## 溯源约束
- **覆盖范围**：所有结论 均需标注来源
- **标注格式**：[来源: {file}:{section}] → [推理: {logic}] → [置信度: {level}]
- **无法溯源处理**：标记为[待验证]并附加置信度。待验证项在最终输出中集中列出

## 溯源链要求
每条分析结论必须包含以下溯源信息：
1. **来源步骤**：该结论由哪个执行步骤产出
2. **输入来源**：结论依据的输入文件及具体章节/段落
3. **推理路径**：从输入到结论的推理链路

## 溯源格式示例
```
## 结论：PDSCH资源分配方案为Type0
[具体分析内容...]

**来源标注**：[来源: 3GPP_38.214.md §5.1.2] → [推理: 基于PDSCH资源分配类型对比表推导] → [置信度: 高]
```

## 待验证项处理
- 标记为[待验证]并附加置信度。待验证项在最终输出中集中列出
- 待验证项不影响整体执行流程
