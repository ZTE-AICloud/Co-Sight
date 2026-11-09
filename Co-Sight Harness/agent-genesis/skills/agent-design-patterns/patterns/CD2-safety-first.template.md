---
pattern_id: CD2
pattern_name: Safety-First
category: constraints
sub_dimension: domain_templates
selection_rule: "可选，可多选。预置约束规则集，可与自定义规则共存。"
solves: "安全敏感场景，操作权限需要额外约束——沙箱、禁止操作、输入消毒"
fills_spec_section: Safety Constraints (安全约束)

variables:
  - name: FORBIDDEN_OPS
    description: "禁止操作列表，每项包含：操作描述、风险说明、替代方案"
    type: list
    source: user_input
    required: true
  - name: SANDBOX_TYPE
    description: "沙箱类型——Docker隔离 / 文件系统只读 / 网络隔离 / 全沙箱 / 无沙箱"
    type: string
    source: user_input
    required: true
    default: "文件系统限制（仅限指定目录读写）"
  - name: NETWORK_POLICY
    description: "网络策略——禁止外部访问 / 仅允许指定域名 / 无限制"
    type: string
    source: user_input
    required: true
    default: "禁止外部网络访问"
  - name: FILESYSTEM_SCOPE
    description: "文件系统读写范围——如：仅允许在项目目录下读写"
    type: string
    source: user_input
    required: true
    default: "仅允许在工作目录及其子目录下读写"
  - name: INPUT_SANITIZATION
    description: "输入消毒规则——如：对用户输入执行XSS过滤/路径遍历检查/代码注入扫描"
    type: string
    source: user_input
    required: false

constraints:
  - "禁止操作清单必须具体且可验证"
  - "沙箱约束必须声明类型和范围"
---

# Safety Constraints

## 安全约束（Safety-First）

### 沙箱约束
| 约束类型 | 配置 |
|---------|------|
| 沙箱类型 | {{SANDBOX_TYPE}} |
| 网络策略 | {{NETWORK_POLICY}} |
| 文件系统范围 | {{FILESYSTEM_SCOPE}} |

### 禁止操作清单
| 操作 | 风险说明 | 替代方案 |
|------|---------|---------|
{{#each FORBIDDEN_OPS}}
| ❌ {{this.operation}} | {{this.risk}} | {{this.alternative}} |
{{/each}}

### 输入消毒
{{#if INPUT_SANITIZATION}}
{{INPUT_SANITIZATION}}
{{else}}
- 用户输入中的路径必须校验在允许范围内（禁止路径遍历）
- 用户输入中的代码片段必须标记为只读展示
- 外部文件内容在解析前必须进行格式校验
{{/if}}

### 违规处理
- 任何触犯禁止操作的行为 → 立即阻断
- 阻断时输出违规详情：操作名称、触发条件、风险说明
- 建议用户调整输入或放宽约束（需用户显式确认）

---
# Filled Example

## 安全约束（Safety-First）

### 沙箱约束
| 约束类型 | 配置 |
|---------|------|
| 沙箱类型 | 文件系统限制（仅限指定目录读写） |
| 网络策略 | 禁止外部网络访问 |
| 文件系统范围 | 仅允许在工作目录及其子目录下读写 |

### 禁止操作清单
| 操作 | 风险说明 | 替代方案 |
|------|---------|---------|
| ❌ 修改源代码仓库中的文件 | 安全敏感场景下的未授权代码变更 | 生成修改建议Patch文件，由用户手动应用 |
| ❌ 执行系统级命令（sudo, chmod, chown） | 权限提升风险 | 报告需要的操作，由用户手动执行 |
| ❌ 访问外部网络（API调用、网络下载） | 数据泄露风险 | 离线分析，要求用户预先提供所需数据 |
| ❌ 操作数据库（DDL/DML） | 数据丢失或损坏风险 | 生成SQL脚本，由DBA审核后执行 |

### 输入消毒
- 用户输入中的路径必须校验在允许范围内（禁止路径遍历）
- 用户输入中的代码片段必须标记为只读展示
- 外部文件内容在解析前必须进行格式校验

### 违规处理
- 任何触犯禁止操作的行为 → 立即阻断
- 阻断时输出违规详情：操作名称、触发条件、风险说明
- 建议用户调整输入或放宽约束（需用户显式确认）
