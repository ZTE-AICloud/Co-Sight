---
pattern_id: CD3
pattern_name: Knowledge-Boundary
category: constraints
sub_dimension: domain_templates
selection_rule: "可选，可多选。预置约束规则集。需要至少搭配K2/K3/K4之一使用。"
solves: "明确区分哪些知识可信任LLM、哪些必须从外部检索——防止幻觉"
fills_spec_section: Safety Constraints (知识边界)
requires_at_least_one_of: ["K2", "K3", "K4"]

variables:
  - name: FORBIDDEN_DOMAINS
    description: "禁止依赖LLM内嵌知识的领域列表，每项包含：领域名、必须使用的替代来源(K2/K3/K4)、原因"
    type: list
    source: user_input
    required: true
  - name: TRUSTED_DOMAINS
    description: "可信赖LLM内嵌知识的领域列表（与K1的可依赖领域保持一致）"
    type: list
    source: user_input
    required: false
  - name: VIOLATION_PATTERNS
    description: "违规检测的模糊引用模式——触发这些措辞即判定为违规"
    type: list
    source: user_input
    required: false
    default: ["根据相关资料...", "一般来说...", "按照行业惯例...", "众所周知...", "通常..."]
  - name: VIOLATION_ACTION
    description: "检测到违规时的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "阻断当前输出 → 提示正确的检索来源 → 要求重新生成（标注具体检索来源）"

constraints:
  - "禁止LLM在声明的边界外自行生成结论"
  - "边界违规必须阻断"
  - "必须与K2/K3/K4协同——声明'不准用LLM'时必须指定替代来源"
---

# Safety Constraints

## 知识边界（Knowledge-Boundary）

### 可信赖 LLM 内嵌知识的领域
以下领域的判断可依赖 LLM 内嵌知识：
{{#each TRUSTED_DOMAINS}}
- {{this}}
{{/each}}

### 禁止依赖 LLM 内嵌知识的领域
以下领域**必须从外部资源检索**，**严禁**使用 LLM 内嵌知识：

| 领域 | 必须使用的来源 | 原因 |
|------|-------------|------|
{{#each FORBIDDEN_DOMAINS}}
| **{{this.domain}}** | `{{this.source}}` | {{this.reason}} |
{{/each}}

### 边界违规检测
以下措辞模式触发违规判定：
{{#each VIOLATION_PATTERNS}}
- "{{this}}"
{{/each}}

### 违规处理
检测到边界违规时：{{VIOLATION_ACTION}}

### 协同约束（Knowledge-Boundary + 知识来源）
- 禁止依赖 LLM 的领域必须在 Knowledge Contract 中有对应的 K2/K3/K4 来源
- 如果某个领域既不在"可信赖"列表中，又不在"禁止"列表中 → 按"禁止"处理（默认不信任）

---
# Filled Example

## 知识边界（Knowledge-Boundary）

### 可信赖 LLM 内嵌知识的领域
以下领域的判断可依赖 LLM 内嵌知识：
- 通用编程知识（数据结构、算法、设计模式）
- 技术写作规范（Markdown格式、文档结构）
- 通用软件工程方法论

### 禁止依赖 LLM 内嵌知识的领域
以下领域**必须从外部资源检索**，**严禁**使用 LLM 内嵌知识：

| 领域 | 必须使用的来源 | 原因 |
|------|-------------|------|
| **3GPP协议细节** | `3GPP_38.214.md` (K2) | 协议规范精确性要求高，LLM容易记混版本和参数 |
| **NR场景名称** | `data/standard_scenarios.csv` (K4) | 场景名必须来源于标准表，不可自创 |
| **接口参数定义** | `data/consume_lib/` (K3) | 接口参数因版本而异，LLM训练数据可能过时 |
| **产品需求细节** | `市场需求.md` (K2) | 需求属于项目特定信息，LLM不可能具备 |

### 边界违规检测
以下措辞模式触发违规判定：
- "根据相关资料..."
- "一般来说..."
- "按照行业惯例..."
- "众所周知..."
- "通常..."

### 违规处理
检测到边界违规时：阻断当前输出 → 提示正确的检索来源（引用上表）→ 要求重新生成（标注具体检索来源的文件和章节）

### 协同约束（Knowledge-Boundary + 知识来源）
- 禁止依赖 LLM 的领域必须在 Knowledge Contract 中有对应的 K2/K3/K4 来源
- 如果某个领域既不在"可信赖"列表中，又不在"禁止"列表中 → 按"禁止"处理（默认不信任）
