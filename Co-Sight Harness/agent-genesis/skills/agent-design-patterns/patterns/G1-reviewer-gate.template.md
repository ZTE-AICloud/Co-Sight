---
pattern_id: G1
pattern_name: Reviewer-Gate
category: workflow
sub_dimension: quality_gate
selection_rule: "可选。可叠加到W1-W4任意分解模式之上。"
solves: "每步产出需要独立质检，不通过则不能继续。审查由独立Agent执行。"
fills_spec_section: Execution Workflow (审查门禁子章节)
overlay_rules:
  W1: "每个Step之后插入审查门禁"
  W2: "每个分支路径的步骤之后插入"
  W3: "每个并行子任务完成后插入"
  W4: "每个Worker完成后+Leader汇总后插入"

variables:
  - name: REVIEW_DIMENSIONS
    description: "审查维度列表，每项必须是可客观验证的判定标准（如：Schema合规性、引用完整性、数值范围校验），禁止模糊维度"
    type: list
    source: user_input
    required: true
  - name: REVIEWER_AGENT
    description: "执行审查的独立Agent名称，必须与执行Agent不同"
    type: string
    source: user_input
    required: true
  - name: MAX_RETRIES
    description: "最大重试次数，超出后阻断执行"
    type: string
    source: user_input
    required: true
    default: "3"
  - name: STEP_OUTPUT_TO_REVIEW
    description: "需要审查的步骤输出文件名列表（或使用通配模式，如'每个Step的输出'）"
    type: list
    source: user_input
    required: true
  - name: PASS_CRITERIA
    description: "通过的明确判定标准（如：所有审查维度均通过且无Critical问题）"
    type: string
    source: llm_generate
    required: false
    default: "所有审查维度均标记为PASS，无任何FAIL项"
  - name: FAIL_EXAMPLES
    description: "不通过的典型示例，帮助审查Agent理解判定边界"
    type: list
    source: user_input
    required: false

constraints:
  - "审查必须由独立Agent执行（非自审）"
  - "必须声明最大重试次数"
  - "重试超限必须阻断"
---

# 审查门禁

## 审查执行约束
- **审查必须由独立 Agent [{{REVIEWER_AGENT}}] 执行，执行 Agent 不得自审**
- **最大重试次数：{{MAX_RETRIES}}，超出后阻断**
- **每个目标步骤/子任务完成后强制触发审查**

## 审查流程
1. 执行 Agent 产出：[{{STEP_OUTPUT_TO_REVIEW}}]
2. 调用 `{{REVIEWER_AGENT}}` 对产出进行审查
3. 审查维度：
{{#each REVIEW_DIMENSIONS}}
   - {{@index+1}}. {{this}}
{{/each}}

## 审查判定
| 结果 | 条件 | 后续动作 |
|------|------|---------|
| **通过** | {{PASS_CRITERIA}} | 进入下一步骤 |
| **驳回** | 存在可修复的 FAIL 项，且未达重试上限 | 修正后重新提交审查 |
| **阻断** | 超过最大重试次数({{MAX_RETRIES}}) 或 存在不可修复的根本性错误 | 停止执行并告知用户原因 |

{{#if FAIL_EXAMPLES}}
## 不通过示例
{{#each FAIL_EXAMPLES}}
- ❌ {{this}}
{{/each}}
{{/if}}

---
# Filled Example

## 审查门禁

## 审查执行约束
- **审查必须由独立 Agent [ReviewAgent-QA] 执行，执行 Agent 不得自审**
- **最大重试次数：3，超出后阻断**

## 审查流程
1. 执行 Agent 产出：[分析结果汇总.md]
2. 调用 `ReviewAgent-QA` 对产出进行审查
3. 审查维度：
   - 1. 每个分析结论是否标注了来源文档的具体章节
   - 2. 场景名称是否在标准场景表中存在（非自创）
   - 3. 数据流转图中的每个中间产物是否都有生产者和消费者
   - 4. JSON 输出是否符合 Schema 定义

## 审查判定
| 结果 | 条件 | 后续动作 |
|------|------|---------|
| **通过** | 所有审查维度均标记为 PASS，无任何 FAIL 项 | 进入下一步骤 |
| **驳回** | 存在可修复的 FAIL 项，且未达重试上限 | 修正后重新提交审查 |
| **阻断** | 超过最大重试次数(3) 或 存在不可修复的根本性错误 | 停止执行并告知用户原因 |

## 不通过示例
- ❌ 场景名使用了标准场景表中不存在的名称（自创）
- ❌ 结论引用了文档中不存在的段落编号
- ❌ JSON 输出缺少 Schema 中的 required 字段
