# workflow-builder

把你想跑的流程写成 `workflow.yaml`，drive 按它来调度 agent。

## 什么时候用

默认 drive 已经自带一个 4 阶段流程（analyze → plan → execute → evaluate）。如果这个流程就是你要的，**不需要这个 skill**。

需要它通常是以下场景：

| 你的需求 | 要做的事 |
|---|---|
| 加一个阶段（如 code-review） | 在默认流程后插入一个 phase |
| 删一个阶段 | 把某个 phase 删掉 |
| 改阶段顺序 | 调整 phases[] 的顺序 |
| 调整 agent（让某个阶段用你项目自己的 agent） | 改 `agent:` 字段 |
| 加回跳（如 evaluate 不通过回 plan） | 配 `allowed_back_jumps` |
| 简单任务跳过 plan | 用 trivial 级别的 `complexity_rules` |
| 完全自己定义一个流程 | 写新 `workflow.yaml`，从模板出发 |

## 快速上手

### 1. 跟 Claude 对话

直接用自然语言说需求，比如：

> 帮我加一个 code-review 阶段，agent 用我项目里那个 code-reviewer

> 我想加个回跳，evaluate 不通过时回到 plan 重做

> 给我的 trivial 任务跳过 plan 阶段

workflow-builder 会扫描你项目里的 agent 文件，问你几个澄清问题，生成 `workflow.yaml` 让你确认。

### 2. 看下生成结果

```bash
cat workflow.yaml
```

确认无误就保存。**写入前一定要看**，workflow-builder 不会自动应用。

### 3. 跑 drive

```
/drive
```

drive 读 `workflow.yaml`、按顺序派 agent。

## 三种 agent 写法

`workflow.yaml` 里 `agent:` 字段有三种合法写法：

| 写法 | 例子 | 含义 |
|---|---|---|
| `drive:<name>` | `drive:analyzer` | drive 自带的 agent，存在于 `03-drive-core/agents/<name>.md` |
| 裸名 | `ProtocolAnalyzer` | 你项目自己的 agent，存在于 `<项目根>/.claude/agents/**/*.md` 的 `name:` frontmatter |
| 内置类型 | `general-purpose` | Claude Code 内置的 subagent 类型（白名单内可直接用） |

`drive:` 前缀的 agent 你**不要自己写**——改 agent 文件也走 drive 自己的 `agents/<name>.md` 路径。

裸名 agent 你需要先在 `.claude/agents/<name>.md` 写好 frontmatter：

```markdown
---
name: MyAgent
description: "干什么用的"
tools: ["Read", "Write", "Bash"]
---

# 你的 agent body
```

## 最少示例

```yaml
phases:
  - stage: analyze
    agent: drive:analyzer
  - stage: plan
    agent: drive:planner
  - stage: execute
    agent: drive:executor
  - stage: evaluate
    agent: drive:evaluator
    terminal_stage: true
```

这是 drive 默认流程的完整定义。如果你不写 `workflow.yaml`，drive 用的就是这个。

## 常用模板

四个模板覆盖大部分场景，路径在 `references/templates.md`：

1. **单一阶段** — 只用 planner 一个 phase
2. **代码审查循环** — code-review → fix → verify，带回跳
3. **跳过 plan** — 默认 4 阶段 + trivial 跳 plan 的 complexity 规则
4. **分析模式** — 3-agent 只读流水线（DeepSearch 项目用）

## 校验

生成后**必须**通过 schema 校验。drive 的 `read_workflow.py` 会在 `/drive` 启动时自动跑一次。但你可以单独跑：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/drive/scripts/read_workflow.py" \--work-dir <你的项目根> --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

返回 JSON：`{"ok": true, ...}` 即通过。`ok: false` 会指出哪个 phase、哪个字段错。

## 字段说明

### 必填

| 字段 | 含义 |
|---|---|
| `name` | 显示名，UI 用 |
| `stage` | 阶段标识，列表内不可重复 |
| `agent` | scoped 地址（三种合法写法之一） |

### 可选

| 字段 | 含义 |
|---|---|
| `description` | 一句话说明 |
| `mode` | `code` 或 `analysis`。execute 阶段用 `code`；只读分析用 `analysis` |
| `wave_barrier` | true = wave 内并发 task，全部完成才进下一 wave。execute 阶段默认 true |
| `terminal_stage` | 收工点，**只能 1 个，且在最后一个 phase** |
| `gate` | 流转前的人工/前置检查（详见下） |
| `verdict_required` | 流转出本阶段前要求每个 verdict_required agent 的 verdict=pass（evaluate 阶段用） |
| `skip_git` | 本阶段不碰 git |

### gate 子字段

```yaml
gate:
  type: human_review       # human_review / input_check / artifact_check
  enforced_by: hooks/state_transition_guard.py   # 强制此 gate 的 hook 路径
  skip_when: [auto_mode]    # 命中此列表就跳过 gate
  on_revise: replan         # 用户回 "revise" 时怎么办
```

`enforced_by` 支持的路径：
- drive 自带：`hooks/state_transition_guard.py`
- 项目本地：`<项目根>/.claude/hooks/phase3-subagent-gate.mjs`（或 `hooks/...` 直接在项目根）
- cosight 风格：`<项目根>/.cosight/hooks/...`

drive 按 `plugin_root / enforced_by` → `work_dir / enforced_by` → `work_dir / .claude/hooks / enforced_by` → `work_dir / .cosight/hooks / enforced_by` 顺序查找。

### complexity_rules

```yaml
complexity_rules:
  trivial:
    skip_phases: [plan]    # 简单任务跳过的 phase
    evaluate_levels: [L0, L1]   # evaluate 阶段做到哪几级
  standard:
    evaluate_levels: [L0, L1, L2]
  complex:
    evaluate_levels: [L0, L1, L2]
```

`complexity` 由 startup 阶段根据输入和 readiness_score 判定。

### allowed_back_jumps

```yaml
allowed_back_jumps:
  evaluate: [plan]   # evaluate 阶段可以跳回 plan 阶段
back_jump_limits:
  evaluate: 3        # 最多回跳 3 次
```

回跳目标必须比当前 stage 早（不能往前跳）。`back_jump_limits` 不设默认无限。

## 常见错误

| 错误 | 原因 | 修法 |
|---|---|---|
| `phases 不能为空` | workflow.yaml 没写 phases | 至少写一个 phase |
| `stage='start' 已废弃` | start 是 drive 内部行为，不在 workflow.yaml | 删掉这行 |
| `agent 引用无效` | agent 名没找到 | 检查 `.claude/agents/<name>.md` 存在且 `name:` frontmatter 正确 |
| `gate.enforced_by 指向的 hook 不存在` | 路径错了 | 用 plugin_root / work_dir 相对路径；项目 hook 放 `.claude/hooks/` |
| `重复的 stage 名称` | 多个 phase 用了同一个 stage | 每个 phase 的 stage 唯一 |
| `terminal_stage 只能有一个` | 多个 phase 标了 terminal_stage | 只能 1 个，且在最后 |
| `terminal_stage 必须是最后一个 phase` | 标在了非末尾 | 把它移到 phases[] 最后 |

更多见 `references/gotchas.md`。

## 工作流

```
你  ──自然语言描述──>  workflow-builder  ──对话澄清──>  生成 YAML 草稿
                                                       │
你  <──  你确认  ──────────────────────────────────────┘
  │
  └──> workflow.yaml 写入磁盘
        │
        └──> drive 读它 / 派 agent / 跑流程
```

workflow-builder **不**：
- 创建 `agents/<name>.md`（agent 文件你自己写或找 Claude 帮你写）
- 改 drive 内部代码
- 执行 workflow（这是 drive skill 的事）

## 详细文档

- `references/agent-catalog.md` — drive 内置 agent 列表和说明
- `references/templates.md` — 4 个常用模板
- `references/output-template.md` — 输出格式示例
- `references/validation.md` — 校验脚本用法
- `references/gotchas.md` — 8 个易错场景
