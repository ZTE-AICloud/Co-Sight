---
pattern_id: CD1
pattern_name: Input-Gating
category: constraints
sub_dimension: domain_templates
selection_rule: "可选，可多选。预置约束规则集，可与自定义规则共存。"
solves: "执行前必须确认所有关键输入存在且可读——先检查再执行"
fills_spec_section: Safety Constraints (输入门禁)

variables:
  - name: REQUIRED_INPUTS
    description: "必需的输入文件列表，每项包含：路径、描述、缺失时的处理动作"
    type: list
    source: user_input
    required: true
  - name: GATING_CHECK_TIMING
    description: "门禁检查的触发时机——Agent启动时 / 每个Phase开始时 / 每个SubAgent执行前"
    type: string
    source: user_input
    required: true
    default: "Agent启动时 + 每个Phase开始时 + 每个SubAgent执行前"
  - name: ON_MISSING_ACTION
    description: "门禁失败时的统一处理动作"
    type: string
    source: llm_generate
    required: false
    default: "阻断执行 + 告知用户缺失的具体文件 + 等待用户提供"

constraints:
  - "所有声明的必须输入文件在执行前必须存在且可读"
  - "缺失时阻断并明确告知用户"
---

# Safety Constraints

## 输入门禁（Input-Gating）

### 必须输入文件清单
| 文件路径 | 描述 | 缺失时处理 |
|---------|------|----------|
{{#each REQUIRED_INPUTS}}
| `{{this.path}}` | {{this.description}} | {{this.on_missing}} |
{{/each}}

### 门禁检查时机
{{GATING_CHECK_TIMING}}

### 门禁检查流程
1. 在每次检查时机触发时，逐一校验必须输入文件的存在性和可读性
2. 全部通过 → 继续执行
3. 任一文件缺失或不可读 → {{ON_MISSING_ACTION}}

### 门禁失败处理
- **阻断执行**：不跳过、不降级、不使用默认值替代
- **明确告知**：列出缺失的具体文件路径和用途
- **等待用户**：用户补充文件后重新执行门禁检查

---
# Filled Example

## 输入门禁（Input-Gating）

### 必须输入文件清单
| 文件路径 | 描述 | 缺失时处理 |
|---------|------|----------|
| `市场需求.md` | 需求描述文档，包含分析目标和场景 | 阻断，告知用户提供需求文档 |
| `算法思路.md` | 算法设计思路，包含分析方法和评价标准 | 阻断，告知用户提供算法思路 |
| `data/standard_scenarios.csv` | 标准场景表，场景名唯一来源 | 阻断，告知用户准备标准场景表 |
| `data/naming_conventions.yaml` | 命名规范，规定输出文件命名格式 | 警告，使用默认命名规范 |

### 门禁检查时机
Agent启动时 + 每个Phase开始时 + 每个SubAgent执行前

### 门禁检查流程
1. 在每次检查时机触发时，逐一校验必须输入文件的存在性和可读性
2. 全部通过 → 继续执行
3. 任一文件缺失或不可读 → 阻断执行 + 告知用户缺失的具体文件 + 等待用户提供

### 门禁失败处理
- **阻断执行**：不跳过、不降级、不使用默认值替代
- **明确告知**：列出缺失的具体文件路径和用途
- **等待用户**：用户补充文件后重新执行门禁检查
