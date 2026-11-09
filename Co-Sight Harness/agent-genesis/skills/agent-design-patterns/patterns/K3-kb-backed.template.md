---
pattern_id: K3
pattern_name: KB-Backed
category: knowledge
sub_dimension: knowledge_sources
selection_rule: "多选。至少选一个知识来源。知识库存放结构化知识，需要检索后注入上下文。"
solves: "知识存放在结构化知识库中，量大无法全部放入上下文，需要检索后注入"
fills_spec_section: Knowledge Contract

variables:
  - name: KB_PATHS
    description: "知识库路径列表（文件系统路径、数据库连接串、API endpoint）"
    type: list
    source: user_input
    required: true
  - name: RETRIEVAL_METHOD
    description: "检索方式：Embedding语义检索 / 图遍历 / SQL查询 / 全文搜索 / 多路召回"
    type: string
    source: user_input
    required: true
  - name: TOP_K
    description: "每次检索返回的最大结果数"
    type: string
    source: user_input
    required: true
    default: "5"
  - name: SIMILARITY_THRESHOLD
    description: "相似度阈值，低于此值的结果标记为低置信度"
    type: string
    source: user_input
    required: true
    default: "0.7"
  - name: EMPTY_RESULT_ACTION
    description: "检索结果为空时的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "阻断并告知用户检索无结果，不猜测。提示用户可能的知识库路径或检索词"
  - name: LOW_CONFIDENCE_ACTION
    description: "检索结果低于阈值时的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "使用结果但标注[低置信度: 相似度=X]，提示用户可能需要人工验证"

constraints:
  - "检索结果为空时，阻断并告知用户（不猜测）"
  - "检索结果低于阈值时，声明低置信度"
---

# Knowledge Contract

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 |
|---------|------|---------|:---:|
{{#each KB_PATHS}}
| 结构化知识库 | `{{this.path}}` | {{this.method}} | ✅ |
{{/each}}

## 检索策略
- **检索方式**：{{RETRIEVAL_METHOD}}
- **检索参数**：TopK={{TOP_K}}，相似度阈值={{SIMILARITY_THRESHOLD}}
- **空结果处理**：检索结果为空时 → {{EMPTY_RESULT_ACTION}}
- **低置信度处理**：检索结果低于阈值({{SIMILARITY_THRESHOLD}})时 → {{LOW_CONFIDENCE_ACTION}}

## 知识库清单
{{#each KB_PATHS}}
| `{{this.path}}` | {{this.description}} | {{this.method}} |
{{/each}}

---
# Filled Example

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 |
|---------|------|---------|:---:|
| 结构化知识库 | `data/consume_lib/` | Embedding语义检索 | ✅ |

## 检索策略
- **检索方式**：Embedding语义检索
- **检索参数**：TopK=5，相似度阈值=0.7
- **空结果处理**：检索结果为空时 → 阻断并告知用户检索无结果，不猜测。提示用户检查知识库路径和检索词
- **低置信度处理**：检索结果低于阈值(0.7)时 → 使用结果但标注[低置信度: 相似度=X]，提示用户可能需要人工验证

## 知识库清单
| `data/consume_lib/` | NR协议消费端知识库，包含协议过程、消息结构、参数定义 | Embedding语义检索 |
