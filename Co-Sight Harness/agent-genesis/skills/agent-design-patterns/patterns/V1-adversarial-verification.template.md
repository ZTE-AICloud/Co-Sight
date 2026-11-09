---
pattern_id: V1
pattern_name: Adversarial-Verification
category: constraints
sub_dimension: adversarial_verification
selection_rule: "可选叠加层。包装任意SubAgent产物验证步骤，对产物执行对抗性压力测试——多个验证者从攻击视角独立审查，非对称投票决定通过/驳回。"
solves: "SubAgent单次执行存在隐蔽缺陷：过度泛化（proves-too-much）、自封闭逻辑（tautological-reduction）、过于简洁的结论（too-simple-to-be-wrong）、投机取巧（specification-gaming）。单验证者易遗漏，需多验证者从对抗视角独立审查。"
fills_spec_section: "Safety Constraints (对抗验证)"
overlay_target: "任意SubAgent的产物验证步骤"

variables:
  - name: FORBIDDEN_INPUTS
    description: "验证者禁止接触的信息——保证独立验证，切断级联信任"
    type: list
    source: decision_table
    required: true
    schema:
      - field: input_type
        type: string
        description: "禁止的信息类型"
      - field: reason
        type: string
        description: "禁止原因"
  - name: REQUIRED_INPUTS
    description: "验证者必须接触的信息"
    type: list
    source: decision_table
    required: true
    schema:
      - field: input_type
        type: string
        description: "必需的信息类型"
      - field: purpose
        type: string
        description: "用途"
  - name: VERIFICATION_STEPS
    description: "对抗验证流程步骤（从原始实现8步工作流中提取）"
    type: list
    source: decision_table
    required: true
    schema:
      - field: step_id
        type: string
        description: "步骤编号"
      - field: name
        type: string
        description: "步骤名称"
      - field: description
        type: string
        description: "步骤描述"
      - field: model
        type: string
        enum: ["opus", "sonnet", "haiku"]
        description: "推荐模型"
      - field: parallel_count
        type: number
        description: "并行实例数"
  - name: VOTING_CONFIG
    description: "非对称投票配置——确认门槛高于反驳门槛，防止假阳性通过"
    type: object
    source: decision_table
    required: true
    schema:
      - field: confirm_threshold
        type: number
        description: "确认通过所需的最少PASS票数"
      - field: refute_threshold
        type: number
        description: "触发驳回所需的FAIL票数"
      - field: max_rounds
        type: number
        description: "最大修订轮次"
      - field: pigeonhole_exit
        type: boolean
        description: "是否启用鸽巢退出（任一验证者给出明确FAIL且证据充分时立即退出）"
  - name: ATTACK_PATTERNS
    description: "对抗攻击模式列表——验证者携带的攻击检测模式"
    type: list
    source: llm_generate
    required: true
    schema:
      - field: pattern_id
        type: string
        description: "模式编号（如 #4, #18, #40, #60）"
      - field: pattern_name
        type: string
        description: "模式名称"
      - field: original_domain
        type: string
        description: "原始领域"
      - field: mapped_domain
        type: string
        description: "映射到SE领域的名称"
      - field: description
        type: string
        description: "攻击模式描述"
      - field: detection_heuristic
        type: string
        description: "检测启发式——验证者如何发现此模式"
  - name: ADVERSARIAL_PROMPT_TEMPLATES
    description: "对抗prompt模板文件路径列表——验证者使用的攻击prompt"
    type: list
    source: user_input
    required: true
  - name: MODEL_TIER_CONFIG
    description: "按模型分层的并行数和参数配置——不同模型用不同宽度补偿能力差异"
    type: list
    source: decision_table
    required: true
    schema:
      - field: model
        type: string
        enum: ["opus", "sonnet", "haiku"]
      - field: solver_count
        type: number
        description: "并行solver数量"
      - field: verifier_count
        type: number
        description: "并行verifier数量"
      - field: confirm_threshold
        type: number
        description: "确认门槛"
      - field: refute_threshold
        type: number
      - field: strategy
        type: string
        description: "该层的策略说明"
  - name: ABSTENTION_CONDITIONS
    description: "验证者声明弃权的条件——当验证者无法做出明确判断时"
    type: string
    source: llm_generate
    required: true
    default: "验证者对产物的正确性无法达到确认/反驳门槛时，声明 'I am not confident' 并记录具体不确定点"
  - name: HOLE_REPORT_FORMAT
    description: "缺陷报告输出格式"
    type: string
    source: llm_generate
    required: true
    default: "每个发现包含: pattern_id, severity(critical/high/medium/low), description, evidence, suggested_fix"

constraints:
  - "dual_context_isolation: 验证者禁止读取被验证SubAgent的工作笔记/final message/推理链/自评段落"
  - "verifier_isolation: 多个验证者之间禁止通信——各自独立审查，防止群体思维"
  - "非对称投票: 确认门槛(confirm_threshold) > 反驳门槛(refute_threshold)，防止假阳性通过"
  - "鸽巢退出: 任一验证者给出明确FAIL且证据充分时，立即终止本轮验证，无需等待其他验证者"
  - "校准弃权: 验证者可声明弃权，但必须记录具体不确定点——不允许静默弃权"
  - "最大修订轮次硬限制: 达到max_rounds后强制终止，输出当前最佳结果"
  - "安全关键产物必须使用opus模型进行对抗验证"
  - "所有攻击模式检测结果必须追溯到具体pattern_id"
  - "验证结果必须独立记录——每个验证者产出独立的hole report后，再进行投票聚合"
---

# Safety Constraints

## 对抗验证（Adversarial-Verification）

### 上下文隔离

验证者必须与以下信息物理隔离：

| 禁止接触 | 原因 |
|----------|------|
{{#each FORBIDDEN_INPUTS}}
| {{this.input_type}} | {{this.reason}} |
{{/each}}

| 必需接触 | 用途 |
|----------|------|
{{#each REQUIRED_INPUTS}}
| {{this.input_type}} | {{this.purpose}} |
{{/each}}

### 验证流程

| 步骤 | 名称 | 描述 | 模型 | 并行数 |
|------|------|------|:---:|:---:|
{{#each VERIFICATION_STEPS}}
| {{this.step_id}} | {{this.name}} | {{this.description}} | **{{this.model}}** | {{this.parallel_count}} |
{{/each}}

### 攻击模式库

验证者携带以下攻击检测模式，审查产物时主动匹配：

| 模式ID | 名称 | 原始领域 | SE映射 | 描述 | 检测启发式 |
|--------|------|---------|--------|------|-----------|
{{#each ATTACK_PATTERNS}}
| {{this.pattern_id}} | {{this.pattern_name}} | {{this.original_domain}} | {{this.mapped_domain}} | {{this.description}} | {{this.detection_heuristic}} |
{{/each}}

### 对抗Prompt模板

验证者使用以下攻击prompt对产物进行压力测试：

{{#each ADVERSARIAL_PROMPT_TEMPLATES}}
- `{{this}}`
{{/each}}

### 非对称投票配置

| 参数 | 值 | 说明 |
|------|:--:|------|
| 确认门槛 | **{{VOTING_CONFIG.confirm_threshold}}** | 需要至少这么多PASS票才能通过 |
| 反驳门槛 | **{{VOTING_CONFIG.refute_threshold}}** | 达到这么多FAIL票立即驳回 |
| 最大轮次 | **{{VOTING_CONFIG.max_rounds}}** | 超过此轮次强制终止 |
| 鸽巢退出 | **{{VOTING_CONFIG.pigeonhole_exit}}** | 任一充分证据的FAIL立即退出 |

### 模型分层配置

不同模型用不同并行宽度补偿能力差异：

| 模型 | Solver数 | Verifier数 | 确认门槛 | 反驳门槛 | 策略 |
|:---:|:---:|:---:|:---:|:---:|------|
{{#each MODEL_TIER_CONFIG}}
| **{{this.model}}** | {{this.solver_count}} | {{this.verifier_count}} | {{this.confirm_threshold}} | {{this.refute_threshold}} | {{this.strategy}} |
{{/each}}

### 校准弃权

{{ABSTENTION_CONDITIONS}}

### 缺陷报告格式

{{HOLE_REPORT_FORMAT}}

### 投票聚合规则

1. 每个验证者独立产出hole report
2. 聚合: 收集所有hole report → 按pattern_id归类 → 按severity排序
3. 判定:
   - PASS票 ≥ confirm_threshold 且 FAIL票 < refute_threshold → **PASS**
   - FAIL票 ≥ refute_threshold → **FAIL**（附带缺陷清单）
   - 其他情况 → **INCONCLUSIVE**（升级人工审核）

---
# Filled Example

## 对抗验证（Adversarial-Verification）

### 上下文隔离

验证者必须与以下信息物理隔离：

| 禁止接触 | 原因 |
|----------|------|
| 被验证SubAgent的final message | 防止验证者被SubAgent的自评结论影响（级联信任） |
| 被验证SubAgent的working notes/推理链 | 防止验证者复现SubAgent的推理路径（独立验证失效） |
| 被验证SubAgent的反思/自评段落 | 防止验证者被SubAgent的自我修正过程干扰 |
| 其他验证者的hole report | 防止验证者之间的群体思维（verifier isolation） |

| 必需接触 | 用途 |
|----------|------|
| 被验证SubAgent的产物文件（实际磁盘文件） | 验证的唯一依据——只看最终产物 |
| 原始需求规格（clarified-agent-requirements.yaml） | 对照需求检查产物完整性 |
| 上游产物的核心字段 | Cross-check产物间一致性 |

### 验证流程

| 步骤 | 名称 | 描述 | 模型 | 并行数 |
|------|------|------|:---:|:---:|
| S1 | 需求对齐检查 | 验证者对需求的理解是否与原始需求一致——防止理解偏差导致后续验证失效 | **sonnet** | 2 |
| S2 | 并行产物生成 | 多个solver独立生成候选产物（用于后续比较基准） | **sonnet** | 6 |
| S3 | 上下文清洗 | 提取solver产物的纯内容，剥离推理过程和工作笔记 | **haiku** | 1 |
| S4 | 对抗验证 | 验证者携带攻击模式库，从对抗视角审查每个产物 | **sonnet** | 5 |
| S5 | 非对称投票 | 收集所有hole report，按confirm/refute门槛投票 | **sonnet** | 1 |
| S6 | 修订 | 若FAIL，将hole report反馈给solver修订，最多3轮 | **sonnet** | 1 |
| S7 | 校准弃权 | 若经max_rounds仍无法达成共识，验证者声明弃权 | **opus** | 1 |
| S8 | 最终呈现 | 输出最终验证报告，包含通过/驳回/弃权状态及缺陷清单 | **sonnet** | 1 |

### 攻击模式库

验证者携带以下攻击检测模式，审查产物时主动匹配：

| 模式ID | 名称 | 原始领域 | SE映射 | 描述 | 检测启发式 |
|--------|------|---------|--------|------|-----------|
| #4 | proves-too-much | 数学证明 | overgeneralization（过度泛化） | 产物的某个声明如果成立，会推导出明显错误的结论——说明声明范围过大 | 尝试将声明应用于极端/边界情况，检查是否会崩溃 |
| #18 | tautological-reduction | 数学证明 | self-sealing（自封闭逻辑） | 产物使用自身的结论作为前提——形成循环论证，看似正确但无信息增量 | 提取关键声明，回溯其依赖的假设，检查是否直接或间接依赖自身 |
| #40 | one-line-proof-too-clean | 数学证明 | too-simple-to-be-wrong（过于简洁） | 一个异常简短的方案声称解决了复杂问题——通常跳过了关键边界条件 | 提取方案中的一般性原则，构造一个符合原则但明显失败的反例 |
| #60 | specification-gaming | 数学证明 | output-token-gaming（投机取巧） | 产物选择需求的最宽松解释来最小化工作量——形式上满足但实质上未解决问题 | 用需求的最严格解释重新评估产物，检查是否存在可量化的差距 |

### 对抗Prompt模板

验证者使用以下攻击prompt对产物进行压力测试：

- `references/adversarial-prompt-templates.md` (§1 General Adversarial)
- `references/adversarial-prompt-templates.md` (§2 Pattern #4 — proves-too-much)
- `references/adversarial-prompt-templates.md` (§3 Pattern #40 — too-clean)
- `references/adversarial-prompt-templates.md` (§4 Pattern #18 — tautological)
- `references/adversarial-prompt-templates.md` (§5 Pattern #60 — gaming)
- `references/adversarial-prompt-templates.md` (§6 Consecutive-Verify 5-pass)
- `references/adversarial-prompt-templates.md` (§7 Adversarial Brief — for reviser when #40 fires)

### 非对称投票配置

| 参数 | 值 | 说明 |
|------|:--:|------|
| 确认门槛 | **4** | 需要至少4个PASS票才能通过（多数确认） |
| 反驳门槛 | **2** | 达到2个FAIL票立即驳回（少数即可否决） |
| 最大轮次 | **3** | 超过3轮修订仍无法通过则强制终止 |
| 鸽巢退出 | **true** | 任一验证者给出明确FAIL且证据充分时立即退出本轮 |

### 模型分层配置

不同模型用不同并行宽度补偿能力差异：

| 模型 | Solver数 | Verifier数 | 确认门槛 | 反驳门槛 | 策略 |
|:---:|:---:|:---:|:---:|:---:|------|
| **haiku** | 12 | 7 | 5 | 3 | 宽度补偿噪音——大量并行的低成本验证弥补单次精度不足 |
| **sonnet** | 6 | 5 | 4 | 2 | 平衡——中等并行的可靠性，默认选项 |
| **opus** | 4 | 5+12 | 4 | 2 | 深度优先——少量高精度solver + 大量pattern专用verifier + 最多修订轮次 |

### 校准弃权

验证者对产物的正确性无法达到确认/反驳门槛时，声明 "I am not confident" 并记录具体不确定点——不允许静默弃权。常见弃权触发：产物涉及不熟悉的领域/技术栈、需求本身存在歧义导致无法判定、攻击模式匹配到边界情况无法确定是否为误报。

### 缺陷报告格式

每个发现包含: pattern_id（匹配的攻击模式ID）, severity（critical/high/medium/low）, description（缺陷描述）, evidence（产物中的具体引用位置）, suggested_fix（建议修复方向）

### 投票聚合规则

1. 每个验证者独立产出hole report
2. 聚合: 收集所有hole report → 按pattern_id归类 → 按severity排序
3. 判定:
   - PASS票 ≥ 4 且 FAIL票 < 2 → **PASS**
   - FAIL票 ≥ 2 → **FAIL**（附带缺陷清单）
   - 其他情况 → **INCONCLUSIVE**（升级人工审核）
