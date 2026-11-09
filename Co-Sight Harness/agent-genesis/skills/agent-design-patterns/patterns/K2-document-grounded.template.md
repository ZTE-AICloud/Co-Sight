---
pattern_id: K2
pattern_name: Document-Grounded
category: knowledge
sub_dimension: knowledge_sources
selection_rule: "多选。至少选一个知识来源。推理必须基于用户提供的特定文档。"
solves: "推理必须基于用户提供的特定文档——每个结论都要能从文档中找到依据"
fills_spec_section: Knowledge Contract

variables:
  - name: DOC_PATHS
    description: "领域文档的文件路径列表（如：[3GPP_38.214.md, 算法思路.md]）"
    type: list
    source: user_input
    required: true
  - name: CITATION_LEVEL
    description: "引用精度要求——章节级(Chapter)/段落级(Paragraph)/句子级(Sentence)"
    type: string
    source: user_input
    required: true
    default: "段落级"
  - name: EMPTY_RESULT_ACTION
    description: "文档中无法找到依据时的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "阻断并告知用户：文档中未找到 [具体问题] 的依据，禁止猜测"
  - name: DOC_PRECEDENCE
    description: "文档与LLM知识冲突时的优先级声明"
    type: string
    source: llm_generate
    required: false
    default: "文档为准。LLM内嵌知识仅用于辅助理解文档内容"

constraints:
  - "每个推理结论必须引用文档具体章节/段落"
  - "文档中无法找到依据时，阻断并告知用户，禁止猜测"
  - "文档与LLM内嵌知识冲突时，以文档为准"
---

# Knowledge Contract

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 |
|---------|------|---------|:---:|
{{#each DOC_PATHS}}
| 领域文档 | `{{this}}` | Read全文读取 | ✅ |
{{/each}}
| LLM内嵌 | 模型训练数据 | 辅助理解文档 | ❌ 不可独立依赖 |

## 检索策略
- **引用精度**：每个推理结论必须引用文档的{{CITATION_LEVEL}}作为依据
- **空结果处理**：文档中无法找到依据时 → {{EMPTY_RESULT_ACTION}}
- **冲突处理**：{{DOC_PRECEDENCE}}

## 文档清单与用途
{{#each DOC_PATHS}}
| `{{this}}` | {{this.description}} |
{{/each}}

---
# Filled Example

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 |
|---------|------|---------|:---:|
| 领域文档 | `3GPP_38.214.md` | Read全文读取 | ✅ |
| 领域文档 | `算法思路.md` | Read全文读取 | ✅ |
| LLM内嵌 | 模型训练数据 | 辅助理解文档 | ❌ 不可独立依赖 |

## 检索策略
- **引用精度**：每个推理结论必须引用文档的段落级作为依据
- **空结果处理**：文档中无法找到依据时 → 阻断并告知用户：文档中未找到相关依据，禁止猜测
- **冲突处理**：文档为准。LLM内嵌知识仅用于辅助理解文档内容

## 文档清单与用途
| `3GPP_38.214.md` | 5G NR物理层协议规范，提供PDSCH/PUSCH处理流程定义 |
| `算法思路.md` | 算法设计思路文档，描述分析目标和方法论 |
