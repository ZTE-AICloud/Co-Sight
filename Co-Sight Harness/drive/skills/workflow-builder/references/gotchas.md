# 常见陷阱 (Gotchas)

## 1. 用户说"加一个阶段"——但没说插哪里

**症状**：用户说"加一个测试阶段"，没说插在 execute 前还是 execute 后。

**正确做法**：
- 先读现有的 `workflow.yaml`
- 列出 2-3 个合理的插入位置
- 让用户选择

```
现有流程：
1. analyze
2. plan
3. execute
4. evaluate

要加的"测试阶段"可以插在：
- execute 之后、evaluate 之前（推荐）
- analyze 之后（早期验证）
- 末尾（最终测试）

你想插哪里？
```

## 2. 用户给的 agent 名不存在

**症状**：用户说"用我的 reviewer"，但 `.claude/agents/reviewer.md` 不存在。

**正确做法**：
- 不要自动假设 agent 存在
- 列出实际可用的 agents（按 `name:` frontmatter 扫描，不靠文件名）
- 让用户选择或确认创建
- 用 scoped 地址区分 plugin / project：内置用 `drive:<name>`，项目自定义用裸名

```
你说的 "reviewer" 不在 .claude/agents/ 目录下。

可用 agents：
- drive:code-reviewer (drive 插件内置)
- drive:security-reviewer (drive 插件内置)
- ProtocolAnalyzer (项目本地，.claude/agents/.../...md 的 name: 字段)

哪个是你想要的？或者需要先创建 reviewer.md？
```

## 3. 用户不知道 gate 是什么

**症状**：用户说"加一个 X 阶段"，没提 gate 配置。

**正确做法**：
- gate 默认配置就够了（human_review + state_transition_guard）
- 不要让用户为每个 stage 重复配置 gate
- 直接使用模板里的默认 gate 配置

```yaml
# 默认 gate（适用于大多数场景）
gate:
  type: human_review
  enforced_by: hooks/state_transition_guard.py
  skip_when: [auto_mode]
```

## 4. 用户给的 workflow 有循环引用

**症状**：用户说"evaluate → plan → evaluate"，但这形成了循环。

**正确做法**：
- 循环是合法的（在 PROPOSAL §3.2 中明确支持）
- 用 `back_jump_limits` 限制次数（默认 3）
- 不要警告用户"这有风险"（已经是设计意图）

```yaml
allowed_back_jumps:
  evaluate: [plan]    # evaluate 可以回到 plan

back_jump_limits:
  evaluate: 3         # 最多 3 次
```

## 5. 用户已经写了 workflow.yaml，增量更新时破坏现有内容

**症状**：用户说"加一个测试阶段"，但现有 workflow.yaml 里有 `allowed_back_jumps` 和 `complexity_rules`。

**正确做法**：
- 先读完整文件
- 在编辑时**保留**其他字段
- 只修改用户要求的部分
- 用 Edit 工具（精确替换），不用 Write（整文件覆盖）

## 6. 用户想跳过某个阶段但用错了字段

**症状**：用户说"trivial 任务跳过 plan"，但写成了 `phases: [analyze, execute, evaluate]`。

**正确做法**：
- phases 列表**必须包含所有阶段**（即使会跳过）
- 用 `complexity_rules.skip_phases` 控制运行时跳过

```yaml
# 错误（会校验失败：跳过了 plan）
phases:
  - stage: analyze
  - stage: execute
  - stage: evaluate

# 正确
phases:
  - stage: analyze
  - stage: plan
  - stage: execute
  - stage: evaluate

complexity_rules:
  trivial:
    skip_phases: [plan]    # trivial 复杂度跳过 plan
```

## 7. 用户给的 stage 名是 `start`

**症状**：用户说"加一个 start 阶段"。

**正确做法**：
- 立刻拒绝
- 说明 start 已内化到 drive
- 推荐其他名字（init / bootstrap / setup）

```
start 阶段由 drive 内部自动调用，不能在 workflow.yaml 中配置。

建议改名为：
- init（初始化）
- bootstrap（启动）
- setup（设置）
```

## 8. 用户用中文名作为 stage

**症状**：用户说"加一个需求分析阶段"。

**正确做法**：
- stage 名称虽然自由，但仍推荐英文（便于跨工具兼容）
- 给出英文等价名

```
需求分析 = analyze (推荐)
或者：requirement-analysis / req-analysis

哪个好？或者就用中文"需求分析"（YAML 支持 unicode）？
```