---
pattern_id: W6
pattern_name: Self-Referential-Loop
category: workflow
sub_dimension: decomposition
type: "meta-decomposition-overlay"
selection_rule: "元分解叠加层。包装W1-W4，声明自引用循环语义——Agent在完成承诺前被重复喂入相同prompt，直到满足退出条件或达到最大迭代次数。"
solves: "需要Agent反复迭代改进直到满足客观完成标准的场景——Agent无法单次执行完成，需通过完成承诺令牌+Stop Hook机制实现自引用循环"
fills_spec_section: "Execution Workflow (self_referential_loop)"
wraps: [W1, W2, W3, W4]
note: "W6需要运行时hook机制支持。本模板描述语义和配置，实现参考ralph-loop（claude-plugins-official/ralph-loop/commands/ralph-loop.md）"

variables:
  - name: BASE_TOPOLOGY
    description: "基础拓扑模式（W1|W2|W3|W4 选一），循环内每次迭代使用此拓扑"
    type: string
    source: decision_table
    required: true
  - name: COMPLETION_TOKEN
    description: "完成承诺令牌——Agent只有在此声明完全为真时才能输出此令牌"
    type: string
    source: user_input
    required: true
    default: "DONE"
  - name: COMPLETION_CRITERIA
    description: "客观完成标准——可被Stop Hook程序化验证的条件列表"
    type: list
    source: user_input
    required: true
    schema:
      - field: criteria_id
        type: string
        description: "标准编号"
      - field: description
        type: string
        description: "完成标准描述（必须可客观验证）"
      - field: verification_method
        type: string
        description: "验证方法（如文件存在性检查、内容模式匹配、SHA256比对）"
  - name: MAX_ITERATIONS
    description: "最大迭代次数硬限制——防止无限循环"
    type: number
    source: decision_table
    required: true
    default: 10
  - name: STATE_FILE_SCHEMA
    description: "迭代状态文件schema——跨迭代持久化状态"
    type: object
    source: decision_table
    required: true
    schema:
      - field: session_id
        type: string
        description: "会话ID，用于隔离不同循环实例"
      - field: iteration
        type: number
        description: "当前迭代次数"
      - field: status
        type: string
        enum: ["running", "completed", "max_iterations_reached"]
      - field: artifacts
        type: list
        description: "当前迭代的产物文件路径列表"
      - field: completion_claimed
        type: boolean
        description: "Agent是否已输出完成令牌"
  - name: STOP_HOOK_BEHAVIOR
    description: "Stop Hook拦截行为描述——当Agent尝试退出时触发"
    type: string
    source: decision_table
    required: true
    default: "拦截Agent退出 → 检查COMPLETION_CRITERIA → 不满足则重新喂入相同prompt → 满足或达到MAX_ITERATIONS则放行"

constraints:
  - "必须声明base_topology（循环内每次迭代使用的拓扑）"
  - "完成令牌是Agent退出的唯一凭证——未输出令牌的退出尝试被Stop Hook拦截"
  - "完成标准必须可客观验证（不依赖LLM主观判断）——基于文件存在性、内容模式、SHA256等"
  - "每次迭代保留上一次的产物文件——Agent可以在上次基础上改进，不需要从头开始"
  - "最大迭代次数硬限制——达到后强制终止，记录状态为max_iterations_reached"
  - "状态文件必须持久化到磁盘——Agent可读取上次迭代状态作为改进依据"
  - "Stop Hook通过拦截Agent退出并重新提交相同prompt实现循环——从Agent视角看是被动重复调用"
  - "与W5的本质区别：W6是在同一拓扑内迭代收敛（不切换拓扑），W5是在不同拓扑间跳转"
---

# Execution Workflow

## 自引用循环声明

**基础拓扑**: {{BASE_TOPOLOGY}}
**最大迭代次数**: {{MAX_ITERATIONS}}
**完成令牌**: `<promise>{{COMPLETION_TOKEN}}</promise>`

> **机制说明**: W6需要运行时Hook机制支持。Agent完成工作尝试退出时，Stop Hook拦截退出请求，检查完成标准是否满足。若不满足，将相同的prompt重新喂给Agent，开始下一轮迭代。从Agent视角看，它被重复调用来改进之前的产物。实现参考 claude-plugins-official/ralph-loop。

## 循环语义

```
┌─────────────────────────────────────┐
│  [第N轮] Agent 接收 Prompt          │
│    ├─ 读取上次迭代状态（若N>1）     │
│    ├─ 以 {{BASE_TOPOLOGY}} 拓扑执行  │
│    ├─ 产出/改进产物                  │
│    ├─ 更新状态文件 (iteration: N)   │
│    └─ 输出完成令牌（若满足标准）     │
│         ↓                            │
│  [Stop Hook 拦截]                   │
│    ├─ 检查 COMPLETION_CRITERIA       │
│    ├─ 满足 → 放行（循环结束）        │
│    └─ 不满足 + N < MAX_ITERATIONS    │
│         └─ 重新喂入相同 Prompt → 循环│
└─────────────────────────────────────┘
```

## 完成标准

| 标准ID | 描述 | 验证方法 |
|--------|------|---------|
{{#each COMPLETION_CRITERIA}}
| {{this.criteria_id}} | {{this.description}} | {{this.verification_method}} |
{{/each}}

## 迭代状态文件

状态文件路径: `work/loop-state.yaml`

```yaml
session_id: "{{STATE_FILE_SCHEMA.session_id}}"
iteration: {{STATE_FILE_SCHEMA.iteration}}
status: "{{STATE_FILE_SCHEMA.status}}"
artifacts:
{{#each STATE_FILE_SCHEMA.artifacts}}
  - "{{this}}"
{{/each}}
completion_claimed: {{STATE_FILE_SCHEMA.completion_claimed}}
```

Agent在每轮迭代开始时读取此文件以了解上一轮状态，在迭代结束时更新此文件。

## Stop Hook 行为

{{STOP_HOOK_BEHAVIOR}}

## 安全约束

1. **迭代上限**: 达到 {{MAX_ITERATIONS}} 次后强制终止——记录 `status: max_iterations_reached`，保留最后产物
2. **完成令牌唯一性**: Agent只能在完成标准**完全且无歧义满足**时输出完成令牌——CRITICAL RULE
3. **状态持久性**: 每轮迭代结束后状态文件必须立即写入磁盘——防止Hook重启丢失进度
4. **产物累积**: 每轮迭代的产物文件保留在独立目录（如 `work/iter_N/`）——支持回溯和审计

---
# Filled Example

## 自引用循环声明

**基础拓扑**: W1-Pipeline
**最大迭代次数**: 10
**完成令牌**: `<promise>DONE</promise>`

> **机制说明**: W6需要运行时Hook机制支持。Agent完成工作尝试退出时，Stop Hook拦截退出请求，检查完成标准是否满足。若不满足，将相同的prompt重新喂给Agent，开始下一轮迭代。从Agent视角看，它被重复调用来改进之前的产物。实现参考 claude-plugins-official/ralph-loop。

## 循环语义

```
┌─────────────────────────────────────┐
│  [第N轮] Agent 接收 Prompt          │
│    ├─ 读取上次迭代状态（若N>1）     │
│    ├─ 以 W1-Pipeline 拓扑执行       │
│    ├─ 产出/改进产物                  │
│    ├─ 更新状态文件 (iteration: N)   │
│    └─ 输出完成令牌（若满足标准）     │
│         ↓                            │
│  [Stop Hook 拦截]                   │
│    ├─ 检查 COMPLETION_CRITERIA       │
│    ├─ 满足 → 放行（循环结束）        │
│    └─ 不满足 + N < MAX_ITERATIONS    │
│         └─ 重新喂入相同 Prompt → 循环│
└─────────────────────────────────────┘
```

## 完成标准

| 标准ID | 描述 | 验证方法 |
|--------|------|---------|
| C1 | CLAUDE.md 文件存在且包含所有必填字段（name, description, tools, model） | 文件存在性 + YAML schema校验 |
| C2 | SKILL.md 文件存在且包含完整工作流描述 | 文件存在性 + 内容长度 ≥ 500字符 |
| C3 | 所有声明的产物文件路径均存在且非空 | 逐一检查文件存在性 |
| C4 | 产物SHA256与上轮迭代不同（确保有实际改进） | SHA256比对 |

## 迭代状态文件

状态文件路径: `work/loop-state.yaml`

```yaml
session_id: "agent-spec-2026-07-03-001"
iteration: 3
status: "running"
artifacts:
  - "work/iter_3/CLAUDE.md"
  - "work/iter_3/SKILL.md"
  - "work/iter_3/agent-spec.yaml"
completion_claimed: false
```

Agent在每轮迭代开始时读取此文件以了解上一轮状态，在迭代结束时更新此文件。

## Stop Hook 行为

拦截Agent退出 → 依次检查C1-C4完成标准 → 全部满足则放行 → 任一不满足且iteration < 10则重新提交相同prompt → iteration ≥ 10则强制终止并记录max_iterations_reached

## 安全约束

1. **迭代上限**: 达到 10 次后强制终止——记录 `status: max_iterations_reached`，保留最后产物
2. **完成令牌唯一性**: Agent只能在完成标准**完全且无歧义满足**时输出完成令牌——CRITICAL RULE
3. **状态持久性**: 每轮迭代结束后状态文件必须立即写入磁盘——防止Hook重启丢失进度
4. **产物累积**: 每轮迭代的产物文件保留在独立目录（如 `work/iter_N/`）——支持回溯和审计
