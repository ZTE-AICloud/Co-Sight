---
pattern_id: K1
pattern_name: LLM-Native
category: knowledge
sub_dimension: knowledge_sources
selection_rule: "多选。至少选一个知识来源。K1通常与K2/K3/K4搭配使用。"
solves: "任务所需知识属于LLM训练数据覆盖范围——通用编程/分析/写作知识"
fills_spec_section: Knowledge Contract

variables:
  - name: TRUSTED_DOMAINS
    description: "可信赖LLM内嵌知识的领域列表（如：通用编程、算法设计、技术写作）"
    type: list
    source: user_input
    required: true
  - name: OTHER_SOURCES
    description: "同时选中的其他知识来源（K2/K3/K4），声明K1辅助哪些来源。仅K1时填'无'"
    type: list
    source: decision_table
    required: true

constraints:
  - "禁止编造不存在的数据/标准/规范"
  - "禁止以'根据相关资料'模糊引用"
  - "与其他知识源冲突时，以外源（K2/K3/K4）为准"
---

# Knowledge Contract

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 | 信任级别 |
|---------|------|---------|:---:|:---:|
| LLM内嵌 | 模型训练数据 | 直接使用 | ✅ | 辅助/参考 |
{{#each OTHER_SOURCES}}
| {{this.type}} | {{this.source}} | {{this.method}} | ✅ | 主要/权威 |
{{/each}}

## LLM 内嵌知识可依赖的领域
{{#each TRUSTED_DOMAINS}}
- {{this}}
{{/each}}

## 约束规则
- **禁止**编造不存在的数据、标准、规范、API
- **禁止**以"根据相关资料""一般来说""按照行业惯例"等模糊措辞引用
- 当 LLM 内嵌知识与外部知识源（{{OTHER_SOURCES}}）冲突时，**以外源为准**
- 上述可依赖领域之外的判断，必须从外部知识源检索确认

---
# Filled Example

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 | 信任级别 |
|---------|------|---------|:---:|:---:|
| LLM内嵌 | 模型训练数据 | 直接使用 | ✅ | 辅助/参考 |
| 领域文档 | 3GPP规范文档 | Read全文读取 | ✅ | 主要/权威 |
| 业务规则 | 标准场景表.csv | 启动时加载 | ✅ | 主要/权威 |

## LLM 内嵌知识可依赖的领域
- 通用编程知识（数据结构、算法、设计模式）
- 技术写作规范（Markdown格式、文档结构）
- 代码审查最佳实践
- 通用软件工程方法论

## 约束规则
- **禁止**编造不存在的数据、标准、规范、API
- **禁止**以"根据相关资料""一般来说""按照行业惯例"等模糊措辞引用
- 当 LLM 内嵌知识与 3GPP规范文档、标准场景表 冲突时，**以外源为准**
