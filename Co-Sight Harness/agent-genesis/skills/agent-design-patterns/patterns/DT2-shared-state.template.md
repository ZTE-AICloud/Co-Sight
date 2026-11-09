---
pattern_id: DT2
pattern_name: Shared-State
category: data
sub_dimension: topology
selection_rule: "可混合使用。与DT1可共存。"
solves: "多个组件需要读写同一个共享状态，协调执行进度"
fills_spec_section: Data Flow

variables:
  - name: STATE_FILES
    description: "共享状态文件列表，每项包含：文件名、Schema路径、维护者、读写权限声明"
    type: list
    source: user_input
    required: true
  - name: CONCURRENCY_MODEL
    description: "并发控制模型——串行执行(无并发冲突) / 文件锁 / 乐观锁(版本号校验)"
    type: string
    source: user_input
    required: true
    default: "串行执行，无并发冲突"
  - name: STATE_SCHEMA_DIR
    description: "状态文件Schema存放目录"
    type: string
    source: llm_generate
    required: false
    default: "schemas/"

constraints:
  - "每个共享状态文件必须声明唯一的维护者"
  - "必须声明读写权限和并发控制策略"
---

# Data Flow

## 共享状态文件

{{#each STATE_FILES}}
### {{this.name}}
- **Schema**: `{{STATE_SCHEMA_DIR}}{{this.name}}.schema.json`
- **用途**: {{this.description}}
- **维护者**: {{this.maintainer}}
- **读写权限**:
  - {{this.maintainer}}：读写
  - 其他组件：只读（自身条目除外）
- **并发控制**: {{CONCURRENCY_MODEL}}

{{/each}}

## 共享状态一致性规则
- 每个状态文件由单一维护者负责更新
- 读方在每次访问前重新读取最新版本
- 并发控制：{{CONCURRENCY_MODEL}}
- 状态文件损坏或格式不符合 Schema → 阻断执行并报告

---
# Filled Example

## 共享状态文件

### phase_status.json
- **Schema**: `schemas/phase_status.schema.json`
- **用途**: 记录当前执行阶段、每个阶段的完成状态、时间戳
- **维护者**: Hooks 自动维护
- **读写权限**:
  - Hooks：读写
  - Main Agent / SubAgent：只读
- **并发控制**: 串行执行，无并发冲突

### 执行计划.json
- **Schema**: `schemas/plan.schema.json`
- **用途**: 记录 SubAgent 清单、任务分配、依赖关系
- **维护者**: Main Agent
- **读写权限**:
  - Main Agent：读写
  - SubAgent：只读（自身任务条目）
- **并发控制**: 串行执行，无并发冲突

## 共享状态一致性规则
- 每个状态文件由单一维护者负责更新
- 读方在每次访问前重新读取最新版本
- 并发控制：串行执行，无并发冲突
- 状态文件损坏或格式不符合 Schema → 阻断执行并报告
