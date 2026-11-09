# Workflow.yaml 模板（DAG 模式）

> **核心原则**：插件已经内置了 4 阶段 workflow（analyze→plan→execute→evaluate）。如果用户的流程和默认一致，**不需要创建** workflow.yaml。只有需要自定义时才用以下模板。
>
> drive-2.3 起只生成 `mode: dag`,workflow-builder 不再生成 phase 模式模板。

## 何时需要自定义 workflow.yaml

| 用户需求 | 是否需要 workflow.yaml |
|---------|----------------------|
| 跑标准开发流程 | ❌ 用默认 |
| trivial 任务跳过 plan | ✅ 用 trivial 复杂度规则 |
| 加一个审查节点 | ✅ 用并行审查模板 |
| 加一个安全审计节点 | ✅ 自定义 agent |
| 审查不通过要回退 | ✅ 用 depends_on 重排 |
| 完全自研流程 | ✅ 用自定义模板 |

## 模板

### 1. 单一节点（最简）

```yaml
mode: dag

orchestration:
  max_concurrent_agents: 16

agents:
  - id: planner
    agent: drive:planner
    depends_on: []
    terminal: true
    verdict_required: true

complexity_rules:
  trivial:
    skip_agents: [planner]
```

适用：用户只想用 planner 帮忙规划，其他不跑。

### 2. 并行审查（4 路并发 review）

```yaml
mode: dag

orchestration:
  max_concurrent_agents: 16

agents:
  - id: code-reviewer
    agent: drive:code-reviewer
    depends_on: [build]
    terminal: true
    verdict_required: true

  # 与 code-reviewer 同 wave 并发
  - id: security-reviewer
    agent: drive:security-reviewer
    depends_on: [build]

  - id: e2e-runner
    agent: drive:e2e-runner
    depends_on: [build]

  - id: silent-failure-hunter
    agent: drive:silent-failure-hunter
    depends_on: [build]
```

适用：构建后 4 路并行审查，最后以 code-review 终态收尾。

### 3. 跳过 plan（trivial 复杂度规则）

```yaml
mode: dag

orchestration:
  max_concurrent_agents: 16

agents:
  - id: planner
    agent: drive:planner
    depends_on: []

  - id: executor
    agent: drive:executor
    depends_on: [planner]

  - id: evaluator
    agent: drive:evaluator
    depends_on: [executor]
    terminal: true
    verdict_required: true

complexity_rules:
  trivial:
    skip_agents: [planner]   # 简单任务跳过规划
  standard:
    evaluate_levels: [L0, L1, L2]
  complex:
    evaluate_levels: [L0, L1, L2]
```

适用：日常开发流程，trivial 任务（如简单 bug 修复）跳过 planner。

### 4. 分析模式（不写代码）

```yaml
mode: dag

orchestration:
  max_concurrent_agents: 8

agents:
  - id: index
    agent: "@indexer"          # 项目本地 agent
    depends_on: []

  - id: search
    agent: "@searcher"          # 项目本地 agent
    depends_on: [index]

  - id: analyzer
    agent: drive:analyzer
    depends_on: [search]
    terminal: true
    verdict_required: true
```

适用：只读分析（不写代码），比如 DeepSearch 项目。

## 模板使用建议

- **从模板出发**：选一个最接近用户需求的模板作为起点
- **删掉不用的字段**：用户没要求的字段（如 `complexity_rules`、`orchestration`）直接删
- **agent 引用四种合法写法**：
  - `drive:<name>` —— 内置 agent（`drive:analyzer` / `drive:planner` / `drive:executor` / `drive:evaluator` / `drive:code-reviewer` / `drive:security-reviewer` / `drive:e2e-runner` / `drive:silent-failure-hunter` / `drive:gate-human`）
  - 裸名 —— 项目本地 agent（需 `.claude/agents/<name>.md` 的 `name:` frontmatter）
  - `@xxx` —— `@-mention`（跳过校验，交给 Claude Code 解析）
  - `plugin:<name>` —— 第三方 plugin agent
- **至少一个 `terminal: true` + `verdict_required: true`** —— 否则 extract_verdict 不知道何时触发
- **校验后写入**：模板是参考，**必须**跑 `read_workflow.py --validate` 通过后再用