---
pattern_id: CD4
pattern_name: Environment-Preflight
category: constraints
sub_dimension: domain_templates
selection_rule: "可选，可多选。预置约束规则集，可与自定义规则共存。"
solves: "执行前检查环境就绪状态——分析工具链、构建工具链、源码完整性、可选上下文。失败时给出精确修复指令，避免执行到一半才发现环境问题。"
fills_spec_section: Safety Constraints (环境预检)

variables:
  - name: ENVIRONMENT_CHECKS
    description: "环境检查项列表，每项包含：check_id、描述、检查命令、期望输出、warning时的处理、error时的处理"
    type: list
    source: user_input
    required: true
    schema:
      - field: check_id
        type: string
        description: "检查编号 (Check 1, Check 2, ...)"
      - field: description
        type: string
        description: "检查项描述"
      - field: command
        type: string
        description: "检查命令（如 command -v scc）"
      - field: expected_output
        type: string
        description: "期望输出或通过条件"
      - field: on_warning
        type: string
        description: "⚠️ 状态时的处理动作（自动修复或降级说明）"
      - field: on_error
        type: string
        description: "❌ 状态时的处理动作（阻断 + 修复指令）"
  - name: CHECK_TIMING
    description: "预检的触发时机"
    type: string
    source: user_input
    required: true
    default: "Agent启动时（在所有SubAgent派发前执行一次完整预检）"
  - name: REPORT_OUTPUT_PATH
    description: "预检报告输出路径"
    type: string
    source: user_input
    required: true
    default: "work/PREFLIGHT.md"
  - name: COMMAND_READINESS_MATRIX
    description: "每项检查对各命令/阶段的就绪判定矩阵——哪些检查是哪些命令的前置条件"
    type: list
    source: user_input
    required: true
    schema:
      - field: command_name
        type: string
        description: "命令或阶段名称"
      - field: requires_checks
        type: string
        description: "需要哪些检查通过（如 Check 1-2 green + Check 4 low-missing）"
      - field: degraded_if
        type: string
        description: "降级条件（什么情况下从 Ready 降为 Ready-with-gaps）"

constraints:
  - "所有检查必须全部执行，即使前面的检查失败也不跳过——目标是输出一份完整的就绪报告，而不是第一个错误"
  - "三态信号：✅ 通过 / ⚠️ 警告（可自动修复或降级）/ ❌ 失败（阻断 + 精确修复指令）"
  - "⚠️ 状态必须给出自动修复命令（如 brew install scc）"
  - "❌ 状态必须给出精确诊断和修复指令，不允许仅报告'失败'"
  - "聚合判定：全部 ✅ → READY / 存在 ⚠️ 无 ❌ → READY-WITH-GAPS / 存在 ❌ → NOT-READY"
  - "构建工具链检查（Check 3）必须做冒烟测试（对真实代码运行语法检查），不能仅检查工具是否存在"
---

# Safety Constraints

## 环境预检（Environment-Preflight）

### 预检时机
{{CHECK_TIMING}}

**关键原则**: 所有检查必须全部执行，即使前面的检查失败也不跳过。目标是输出一份完整的就绪报告，而不是第一个错误。

### 环境检查清单

| 检查ID | 描述 | 检查命令 | 期望输出 |
|--------|------|---------|---------|
{{#each ENVIRONMENT_CHECKS}}
| {{this.check_id}} | {{this.description}} | `{{this.command}}` | {{this.expected_output}} |
{{/each}}

### 三态信号处理

| 状态 | 含义 | 处理方式 |
|------|------|---------|
| ✅ | 通过 | 无需处理 |
| ⚠️ | 警告 — 可降级继续 | {{#each ENVIRONMENT_CHECKS}}{{#if this.on_warning}}**{{this.check_id}}**: {{this.on_warning}}{{/if}}{{/each}} |
| ❌ | 失败 — 阻断 | {{#each ENVIRONMENT_CHECKS}}{{#if this.on_error}}**{{this.check_id}}**: {{this.on_error}}{{/if}}{{/each}} |

### 各命令就绪判定

| 命令/阶段 | 前置检查要求 | 降级条件 |
|-----------|-------------|---------|
{{#each COMMAND_READINESS_MATRIX}}
| {{this.command_name}} | {{this.requires_checks}} | {{this.degraded_if}} |
{{/each}}

### 聚合判定规则

1. 全部检查 ✅ → **READY** — 所有命令可正常执行
2. 存在 ⚠️ 但无 ❌ → **READY-WITH-GAPS** — 部分功能降级，列出受影响的能力
3. 存在 ❌ → **NOT-READY** — 阻断执行，输出修复指令清单

### 报告输出

预检结果写入 `{{REPORT_OUTPUT_PATH}}`：
- 状态表（每行一个检查，含状态、发现、修复指令）
- 聚合判定
- 如果有 ❌，列出最关键的 1 个修复（优先级最高）

---
# Filled Example

## 环境预检（Environment-Preflight）

### 预检时机
Agent启动时（在所有SubAgent派发前执行一次完整预检）

**关键原则**: 所有检查必须全部执行，即使前面的检查失败也不跳过。目标是输出一份完整的就绪报告，而不是第一个错误。

### 环境检查清单

| 检查ID | 描述 | 检查命令 | 期望输出 |
|--------|------|---------|---------|
| Check 1 | 检测技术栈 — 从文件扩展名和清单文件指纹识别语言、构建系统、部署/配置描述符 | `file legacy/$1/**/*` + 扩展名统计 | 输出检测到的语言、构建系统及文件分布 |
| Check 2 | 分析工具链 — 检查 scc/cloc、lizard、glow、delta 等工具是否可用 | `command -v scc && command -v lizard && command -v glow && command -v delta` | 每个工具输出版本号；缺失时给出安装命令 |
| Check 3 | 构建工具链冒烟测试 — 对真实代码运行语法检查（非仅检查工具是否存在）| 对代表源文件运行语法编译（如 `cobc -fsyntax-only`、`javac`、`gcc -fsyntax-only`） | 编译通过；失败时诊断：缺失copybook/include路径、缺失dialect flag、固定vs自由格式、缺失依赖jar |
| Check 4 | 源码完整性 — 检查引用但缺失的include、部署/配置描述符、数据定义、无源码的二进制制品 | `grep` 引用声明 vs `find` 实际文件 | 列出缺失的include名称、缺失的配置/DDL/二进制制品清单 |
| Check 5 | 可选上下文 — 可观测性/APM MCP server是否连接、版本控制历史是否可用 | 检查 MCP server 连接状态 + `git log --oneline -5` | 可用/不可用 + 影响说明 |

### 三态信号处理

| 状态 | 含义 | 处理方式 |
|------|------|---------|
| ✅ | 通过 | 无需处理 |
| ⚠️ | 警告 — 可降级继续 | **Check 2**: 缺失工具给出平台对应的安装命令（`brew install scc` / `apt install cloc` / `pip install lizard`），并说明降级影响（如 scc 缺失时 LOC/复杂度估算降级为 `find`+`wc`，COCOMO 估算变粗糙）；**Check 3**: 目标栈工具链缺失给出安装指令，legacy栈红色降级为 Ready-with-gaps（等价性测试回退到录制trace/golden-master） |
| ❌ | 失败 — 阻断 | **Check 3**: 冒烟测试失败 → 诊断具体错误（缺失copybook/include路径、缺失dialect flag如 `-std=ibm`、固定vs自由格式、缺失依赖jar），输出精确修复指令；**Check 4**: 关键配置/DDL缺失 → 阻断，告知用户补充文件路径 |

### 各命令就绪判定

| 命令/阶段 | 前置检查要求 | 降级条件 |
|-----------|-------------|---------|
| assess + map + extract-rules | Check 1-2 基本 green + Check 4 缺失include数量低 | Check 2 工具缺失 → 指标估算精度下降 |
| brief | 仅需3个探索产物（不依赖工具链）| 几乎不降级 |
| transform + reimagine | 额外需要 Check 3 target栈 green | legacy构建工具链红色 → Ready-with-gaps（等价性测试回退到录制trace/golden-master，常见于CICS/IMS等无本地运行时的代码）|
| harden | Check 2 + 栈特定SAST工具 | SAST工具缺失 → 安全分析覆盖不完整 |

### 聚合判定规则

1. 全部检查 ✅ → **READY** — 所有命令可正常执行
2. 存在 ⚠️ 但无 ❌ → **READY-WITH-GAPS** — 部分功能降级，列出受影响的能力
3. 存在 ❌ → **NOT-READY** — 阻断执行，输出修复指令清单

### 报告输出

预检结果写入 `work/PREFLIGHT.md`：
- 状态表（每行一个检查，含状态、发现、修复指令）
- 聚合判定
- 如果有 ❌，列出最关键的 1 个修复（优先级最高）
