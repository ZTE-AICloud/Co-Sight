---
name: hello-agent
description: "示例 agent 定义，展示所有可用的 frontmatter 字段。当用户请求 'hello' 相关任务时使用此 agent。"
tools: ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
disallowedTools: ["Agent"]
model: inherit
permissionMode: default
maxTurns: 50
skills:
  - api-conventions
  - error-handling-patterns
mcpServers:
  - playwright:
      type: stdio
      command: npx
      args: ["-y", "@playwright/mcp@latest"]
  - github
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-command.sh"
  PostToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: "./scripts/run-linter.sh"
memory: project
background: false
effort: medium
isolation: worktree
color: blue
initialPrompt: "开始工作前，先检查项目结构和依赖关系"
---

# Hello Agent 完整字段说明

这是一个展示所有可用 frontmatter 字段的示例 agent 定义文件。

## Frontmatter 字段完整列表

### 必需字段 (Required)

#### `name` (必需)
- **类型**: string
- **说明**: agent 的唯一标识符，使用小写字母和连字符
- **约束**:
  - 只能包含小写字母、数字、连字符
  - 不能包含冒号 `:` (保留给 plugin scoped 标识符，如 `my-plugin:reviewer`)
  - 文件名不必与 name 匹配
- **示例**: `hello-agent`, `code-reviewer`, `db-analyzer`
- **传递给 hooks**: 作为 `agent_type` 参数

#### `description` (必需)
- **类型**: string
- **说明**: 描述何时 Claude 应该将任务委托给此 agent
- **最佳实践**:
  - 写清楚触发条件和用途
  - 包含 "Use proactively" 鼓励主动委托
  - 前置关键用例（描述会被截断到 1536 字符）
- **示例**: 
  ```yaml
  description: "Reviews code for quality and best practices. Use proactively after writing or modifying code."
  ```

### 工具控制字段 (Tool Control)

#### `tools`
- **类型**: string[] (数组)
- **说明**: agent 可以使用的工具白名单
- **默认**: 如果省略，继承所有 subagent 可用的工具
- **特殊语法**:
  - `Agent(worker, researcher)`: 限制只能生成特定类型的 subagent
  - `Agent`: 允许生成任何 subagent
  - `mcp__<server>`: 授予特定 MCP server 的所有工具
  - `mcp__<server>__*`: 同上（等价写法）
- **示例**:
  ```yaml
  tools: ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
  tools: ["Agent(worker, researcher)", "Read", "Bash"]
  ```
- **注意**: 如果列表中没有任何条目解析为有效工具，agent 通常无法启动

#### `disallowedTools`
- **类型**: string[] (数组)
- **说明**: 要拒绝的工具黑名单，从继承或指定的工具列表中移除
- **特殊语法**:
  - `mcp__<server>`: 移除特定 MCP server 的所有工具
  - `mcp__*`: 移除所有 MCP 工具
- **示例**:
  ```yaml
  disallowedTools: ["Write", "Edit"]
  disallowedTools: ["mcp__github"]
  ```
- **处理顺序**: 先应用 `disallowedTools`，再解析 `tools`

#### `Skill` 工具预加载
- **字段**: `skills`
- **类型**: string[] (数组)
- **说明**: 在 agent 启动时将 skill 内容注入到上下文中
- **用途**: 提供领域知识，无需在执行期间发现和加载
- **示例**:
  ```yaml
  skills:
    - api-conventions
    - error-handling-patterns
  ```
- **注意**:
  - agent 仍可通过 Skill 工具调用未列出的 skills
  - 无法预加载设置了 `disable-model-invocation: true` 的 skills
  - 缺失或禁用的 skill 会被跳过并记录警告

### 模型配置 (Model Configuration)

#### `model`
- **类型**: string
- **说明**: agent 使用的 AI 模型
- **默认与推荐**: `inherit`（跟随主对话的模型）。**自定义网关 / 企业网关环境下必须用 `inherit` 或省略该字段**
- **可选值**:
  - **继承**: `inherit` (使用主对话的模型)
  - **省略**: 默认为 `inherit`
  - **模型别名**: `sonnet`, `opus`, `haiku`, `fable` —— 由引擎按**自己的别名表**解析成内置型号
    （如 `sonnet` → `claude-sonnet-5-5`），**不读取会话模型**；网关未提供该型号时子代理直接
    `model_not_found`（HTTP 404），而主代理仍可正常工作
  - **完整模型 ID**: 仅当网关确实提供该型号时使用
- **解析优先级** (从高到低):
  1. `CLAUDE_CODE_SUBAGENT_MODEL` 环境变量
  2. 调用时传递的 `model` 参数
  3. agent 定义的 `model` frontmatter
  4. 主对话的模型
- **示例**:
  ```yaml
  model: inherit            # 推荐：跟随会话模型，跨网关安全
  # model: sonnet           # 别名：依赖引擎别名表，自定义网关可能没有该型号
  # model: claude-sonnet-5   # 完整 ID：仅当网关提供该型号
  ```

#### `effort`
- **类型**: string
- **说明**: agent 活跃时的推理强度等级，覆盖 session 的 effort 设置
- **可选值**: `low`, `medium`, `high`, `xhigh`, `max`
- **默认**: 从 session 继承
- **可用等级**: 取决于模型
- **示例**:
  ```yaml
  effort: high
  ```

### 权限与隔离 (Permissions & Isolation)

#### `permissionMode`
- **类型**: string
- **说明**: 控制 agent 如何处理权限提示
- **可选值**:
  - `default` / `manual`: 标准权限检查，带提示
  - `acceptEdits`: 自动接受工作目录内的文件编辑和常见文件系统命令
  - `auto`: 自动模式，后台分类器审查命令和受保护目录写入
  - `dontAsk`: 自动拒绝权限提示（显式允许的工具仍可工作）
  - `bypassPermissions`: 跳过权限提示（谨慎使用）
  - `plan`: 计划模式（只读探索）
- **优先级**: 父级的 `bypassPermissions` / `acceptEdits` / `auto` 优先，不可覆盖
- **示例**:
  ```yaml
  permissionMode: acceptEdits
  ```
- **注意**: Plugin subagents 忽略此字段

#### `isolation`
- **类型**: string
- **说明**: 设置 agent 的隔离模式
- **可选值**: `worktree`
- **行为**: 
  - `worktree`: 在临时 git worktree 中运行 agent
  - 默认从 default branch 分支（而非父 session 的 HEAD）
  - 如果 agent 没有做任何更改，worktree 自动清理
- **示例**:
  ```yaml
  isolation: worktree
  ```

### MCP 服务器配置 (MCP Servers)

#### `mcpServers`
- **类型**: (string | object)[] (数组)
- **说明**: 此 agent 可访问的 MCP 服务器
- **条目类型**:
  - **字符串引用**: 引用已配置的 server (如 `"slack"`)
  - **内联定义**: 完整的 MCP server 配置对象
- **行为**:
  - 内联定义的 server: agent 启动时连接，完成时断开
  - 字符串引用: 共享父 session 的连接
- **示例**:
  ```yaml
  mcpServers:
    # 内联定义: 仅限此 agent
    - playwright:
        type: stdio
        command: npx
        args: ["-y", "@playwright/mcp@latest"]
    # 字符串引用: 复用已配置的 server
    - github
  ```
- **支持的类型**: `stdio`, `http`, `sse`, `ws`
- **注意**: Plugin subagents 忽略此字段

### 生命周期钩子 (Lifecycle Hooks)

#### `hooks`
- **类型**: object
- **说明**: agent 生命周期内运行的钩子
- **支持的事件**:
  - `PreToolUse`: 工具执行前
  - `PostToolUse`: 工具执行后
  - `Stop`: agent 完成时（在 subagent 中自动转换为 SubagentStop）
- **示例**:
  ```yaml
  hooks:
    PreToolUse:
      - matcher: "Bash"
        hooks:
          - type: command
            command: "./scripts/validate-command.sh"
    PostToolUse:
      - matcher: "Edit|Write"
        hooks:
          - type: command
            command: "./scripts/run-linter.sh"
  ```
- **注意**: Plugin subagents 忽略此字段

### 持久化内存 (Persistent Memory)

#### `memory`
- **类型**: string
- **说明**: 为 agent 提供跨对话持久化的目录
- **可选值**:
  - `user`: `~/.claude/agent-memory/<name>/` (跨所有项目)
  - `project`: `.claude/agent-memory/<name>/` (项目特定，可版本控制)
  - `local`: `.claude/agent-memory-local/<name>/` (项目特定，不进版本控制)
- **行为**:
  - agent 系统提示包含读写内存目录的指令
  - 自动加载 `MEMORY.md` 的前 200 行或 25KB
  - 自动启用 Read, Write, Edit 工具
- **依赖**: 需要启用 auto memory (不能设置 `CLAUDE_CODE_DISABLE_AUTO_MEMORY`)
- **示例**:
  ```yaml
  memory: project
  ```

### 执行控制 (Execution Control)

#### `maxTurns`
- **类型**: number (整数)
- **说明**: agent 停止前的最大 agentic turns 数量
- **示例**:
  ```yaml
  maxTurns: 50
  ```

#### `background`
- **类型**: boolean
- **说明**: 是否始终在后台运行此 agent
- **默认**: 未设置时，Claude 自行选择（v2.1.198+ 默认后台运行）
- **行为**:
  - `true`: 即使 Claude 需要立即获取结果，也在后台运行
  - `false`: 前台运行
  - 后台 agent 的工具集受限（仅保留部分内置工具 + 所有 MCP 工具）
- **示例**:
  ```yaml
  background: false
  ```

#### `initialPrompt`
- **类型**: string
- **说明**: 当此 agent 作为主 session 运行时（通过 `--agent` 或 `agent` 设置）自动提交的首个用户 turn
- **行为**:
  - 处理命令和 skills
  - 如果用户提供了 prompt，此字段内容会前置
- **示例**:
  ```yaml
  initialPrompt: "开始工作前，先检查项目结构和依赖关系"
  ```

### 显示配置 (Display)

#### `color`
- **类型**: string
- **说明**: agent 在任务列表和 transcript 中的显示颜色
- **可选值**: `red`, `blue`, `green`, `yellow`, `purple`, `orange`, `pink`, `cyan`
- **示例**:
  ```yaml
  color: blue
  ```

## Agent Body (System Prompt)

Frontmatter 之后的 Markdown 内容成为 agent 的系统提示（system prompt）。

```markdown
---
name: code-reviewer
description: Reviews code for quality and best practices
tools: ["Read", "Grep", "Glob"]
model: inherit
---

# Code Reviewer System Prompt

You are an expert code reviewer specializing in software quality, security, 
and best practices.

## Your Responsibilities

1. **Code Quality**: Check for readability, maintainability, and consistency
2. **Security**: Identify potential vulnerabilities (SQL injection, XSS, etc.)
3. **Best Practices**: Ensure adherence to language-specific conventions
4. **Performance**: Flag inefficient algorithms or resource usage

## Output Format

For each issue found:
- **Severity**: CRITICAL / HIGH / MEDIUM / LOW
- **Location**: file:line
- **Issue**: Brief description
- **Recommendation**: Specific fix or improvement

Focus on actionable feedback with concrete examples.
```

## 字段组合示例

### 只读研究型 Agent

```yaml
---
name: researcher
description: "Fast read-only agent for codebase exploration and analysis"
tools: ["Read", "Grep", "Glob", "Bash"]
model: inherit
permissionMode: plan
---
```

### 带内存的代码审查 Agent

```yaml
---
name: code-reviewer
description: "Reviews code for quality and best practices. Use proactively after code changes."
tools: ["Read", "Grep", "Glob"]
model: inherit
memory: project
---
```

### 隔离环境的并发测试 Agent

```yaml
---
name: test-runner
description: "Runs tests in isolated environment"
tools: ["Read", "Bash"]
model: inherit
isolation: worktree
background: true
---
```

### 受限数据库查询 Agent

```yaml
---
name: db-reader
description: "Execute read-only database queries"
tools: ["Bash"]
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-readonly-query.sh"
---
```

### 多工具协调器 Agent

```yaml
---
name: coordinator
description: "Coordinates work across specialized agents"
tools: ["Agent(worker, researcher)", "Read", "Bash"]
model: inherit
maxTurns: 100
effort: high
---
```

## 注意事项

1. **必需字段**: `name` 和 `description` 是唯一必需的字段
2. **Plugin 限制**: Plugin subagents 不支持 `hooks`, `mcpServers`, `permissionMode`
3. **工具解析顺序**: 先 `disallowedTools`，后 `tools`
4. **权限优先级**: 父级的 `bypassPermissions` / `acceptEdits` / `auto` 不可覆盖
5. **内存依赖**: `memory` 字段需要启用 auto memory 功能
6. **工作目录**: Agent 从主对话的当前工作目录启动（除非 `isolation: worktree`）
7. **扩展思考**: Subagents 从 v2.1.198+ 继承主对话的 extended thinking 配置

## 相关文档

- Claude Code Sub-agents 官方文档: https://code.claude.com/docs/en/sub-agents
- Agent Teams: https://code.claude.com/docs/en/agent-teams
- Hooks: https://code.claude.com/docs/en/hooks
- MCP Servers: https://code.claude.com/docs/en/mcp
- Skills: https://code.claude.com/docs/en/skills

---

## AgentGenesis 生成规范（本厂增补）

> 平台字段以上文字典为准；本节是 AgentGenesis 生成 SubAgent 时的**本厂规范**（build-planner 编译工序卡
> 的原料）。来源: executor-generation-quality 方案 S1 + 仓库 SubAgent 实践 + forbidden_inputs/tools 合规底线（原 G018/G020 机检已删，为评审期人工核对不变量）。

### frontmatter 增补字段（平台字段之外的 AgentGenesis 约定）

| 字段 | 约定 | 依据 |
|------|------|------|
| `context_isolation` | `required`（恒） | 独立上下文是盲评/隔离架构的基础声明 |
| `forbidden_inputs` | 非空数组，逐项点名具体文件名（禁止"等其他文件"） | 评审期人工核对非空（原 G018 机检已删）；点名到文件才可执行层校验 |
| `tools` | 必须含 `Write`（写自己的产出） | 评审期人工核对（原 G020 机检已删）；只读审查类角色用白名单收窄（不含 Write/Edit 即表达 CD2） |
| `model` | 默认 `sonnet`，偏离须在 description 或注释给理由 | M1 模型选择默认值 |
| `maxTurns` / `effort` | 按任务量估（10-100 / medium-high） | 与仓库现役 SubAgent 区间一致 |

### 正文五段结构（生成时的章节顺序）

1. **职责**: 一句话角色 + 边界声明句。盲评/审查类角色必须含纪律句式——"**你不参与 X 过程。
   你只能看到 Y。**"（如 runtime-evaluator）
2. **输入**: 逐条列输入文件/参数（含来源 step）
3. **禁止读取**: 逐条列 forbidden_inputs 并各附一句"为什么不能读"（破坏什么独立性/防什么锚定）
4. **执行流程**: 编号步骤（Step 1-N），每步输入→动作→输出可追；物化的模式决策写进步骤内容
5. **注意**: 该角色的特殊红线（不自审/不评分/不扩大范围等）

### description 公式（SF-6）

`「做什么」+「何时触发」+「接收什么输入」+「产出什么输出」`——四要素缺一即不合格（G023
content_contains 可机检关键词，人审清单判断质量）。

### 命名

kebab-case；角色名即文件名（`{role}.md`），跨文件引用（其他 agent 的 forbidden_inputs、
workflow 的调度表）必须同名同义。

## 最小合规样例

```markdown
---
name: example-reviewer
description: >
  示例审查 SubAgent。触发于主 Agent 调度审查时；输入为 e2e-results/ 与验收标准；
  输出为评分报告（4 维加权 + 诊断）。不参与产物构建与测试执行。
tools: [Read, Write, Grep, Glob, Bash]
context_isolation: required
forbidden_inputs:
  - build-plan.md
  - human-review.md
model: inherit
maxTurns: 25
effort: high
---

# Example Reviewer

## 职责
对产物评分。**你不参与构建与测试过程。你只能看到测试结果和验收标准。**

## 输入
- e2e-results/（前序测试步骤产出）
- clarified-agent-requirements.yaml 的 acceptance_criteria

## 禁止读取
- build-plan.md（不知道设计方案——防锚定）
- human-review.md（不知道审批材料——防评分漂移）

## 执行流程
### Step 1: 加载测试结果 → 明细列表
### Step 2: 4 维评分（correctness 40% / completeness 30% / format 15% / actionability 15%）
  PASS 阈值: weighted ≥ 3.5
### Step 3: 诊断（若 FAIL）→ probable_causes + suggestions
### Step 4: 输出 runtime-eval.md（schema: runtime-eval.schema.yaml）

## 注意
- 评估只基于可观察事实，证据不足标 confidence: low 而非猜测
- 不修改被评产物
```
