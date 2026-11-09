---
name: workflow-builder
description: "Use when the user wants to generate, modify, or restructure a workflow.yaml file. Triggers on '帮我生成 workflow' / '加一个阶段' / '让 evaluate 回到 plan' / '改一下编排' / 'workflow 太复杂了简化一下'. Do not create agents or modify drive internals."
user-invocable: true
allowed-tools: Bash(python3 *validate_workflow.py*), Bash(python3 *render_dag.py*), Bash(cp *workflow.yaml*), Read(workflow.yaml), Read(agents/*.md), Glob(agents/*.md), Read(.claude/agents/**/*.md), Glob(.claude/agents/**/*.md), Write(workflow.yaml), Edit(workflow.yaml)
---

# Workflow Builder（grill-me 风格）

把用户的自然语言描述翻译成 `workflow.yaml`（**mode: dag**）。

## 设计原则

1. **simplify-by-default**：生成的 workflow.yaml 不输出 `background` 字段——绝大多数用户不需要面对这个概念
2. **DAG 模式唯一**：workflow-builder 只生成 `mode: dag`，不复用 phase 模式生成逻辑（DAG 是 phase 严格超集，能力无损）
3. **grill-me 风格**：决策树 frontier 驱动 + 每问题附推荐答案（详见 §工作流程）
4. **不擅自动作**：所有改动需用户显式确认
5. **frontier 清空才停**：决策树走完才生成 YAML

## 触发条件（何时激活）

只有用户**明确**想改 `workflow.yaml` 时才激活。日常的"跑一下 workflow" / "看 plan 阶段" / "理解阶段流转"——**不**激活这个 skill。

## 工作流程（grill-me 风格）

按 5 轮推进 frontier，每轮问"已可问"的子问题集 + 附推荐答案。

### Round 1：扫描候选 agents + 提取候选节点

派子 agent 扫文件（不让用户列清单）：

- 扫描 `<work_dir>/.claude/agents/**/*.md` 读 `name:` frontmatter → 项目本地 agent
- 扫描 `<plugin_root>/agents/*.md` 读 `name:` frontmatter → drive 内置 agent（analyzer / planner / executor / evaluator / code-reviewer / security-reviewer / gate-human）
- 扫描产物：可用 agent 列表（含 scoped 解析）

然后 grill：

```
❓ Q1 - **节点完整性**：下面这些节点够了吗？

候选节点（按出现顺序）：
1. 需求分析 → 推荐 agent = drive:analyzer
2. auth实现 → agent = ?（未识别，需用户指认）
3. api实现 → agent = ?（未识别，需用户指认）
4. 代码审查 → 推荐 agent = drive:code-reviewer

➡️ 推荐：4 个节点齐全，按上表分配
➡️ 如要改 auth/api 实现 agent，请提供 agent 名或 .md 文件路径
```

### Round 2：明确依赖关系（拓扑推断 + 确认）

子 agent 推断依赖（不让人手工列）：

```
❓ Q2 - **依赖关系**：下面这张图对吗？

  analyzer ─┬─→ impl-auth  ─┐
           └─→ impl-api    ─┼─→ reviewer
                          （impl-auth 与 impl-api 并发）

➤ 推导依据：
  - "先分析需求" → analyzer 是源点（depends_on: []）
  - "auth 和 api 并行" → 两者都依赖 analyzer
  - "最后 reviewer" → reviewer 依赖 impl-auth 和 impl-api

➡️ 推荐：yes，按图生成 DAG 边
➡️ 注意：未发现 reviewer → 任何上游的回跳，意味着评审失败 workflow 结束
```

**关键词识别**：
- "X 后" / "X 完成后再" / "after X" → 串行（X 是上游）
- "并行" / "同时" / "并发" / "with X" → X 与当前 agent 同 wave
- 无关键词 + 看起来相关的 agent → 默认并行（再 grill 确认）
- "reviewer" / "review" / "审查" → 加 reviewer 节点 + 依赖前序
- 末尾的"评估" / "verify" / "测试" → 加 evaluator + verdict_required: true + terminal: true

### Round 3：gate / terminal / complexity 配置

```
❓ Q3 - **HITL gate**：要不要在任何节点间插人审环节？

可选位置：
- analyzer 后插 drive:gate-human（需求分析确认后再开发）
- reviewer 后插 drive:gate-human（评审通过后再宣布完成）

➡️ 推荐：不插 gate（保持全自动）
➡️ 如要插：指定 "analyzer 后插一个" 或 "reviewer 前插一个"

❓ Q4 - **workflow 终点**：哪个 agent 是 terminal？

➡️ 推荐：reviewer 是 terminal（它是 DAG 最下游）➡️ terminal 必须配 verdict_required=true，否则 extract_verdict 不知道何时触发
```

### Round 4：复杂度策略 + 回跳

```
❓ Q5 - **复杂度策略**：当 complexity=trivial 时跳哪些节点？

trivial 场景下：
- 可跳：reviewer（自动评审）
- 不可跳：analyzer / impl-auth / impl-api（业务必须做）

➡️ 推荐：trivial 时 skip_agents: [reviewer]
➡️ 如要保留 reviewer，请显式说"trivial 也跑 reviewer"

❓ Q6 - **回跳配置**：要不要给某些节点配回跳？

可选回跳：
- reviewer → impl-auth（评审 auth 不过重做）
- reviewer → impl-api（评审 api 不过重做）

➡️ 推荐：不配回跳（评审失败直接结束，由用户决定是否手工重启）
➡️ 如要配：建议限定次数（默认 3 次）
```

### Round 5：生成预览 + 校验 + 写入

```
❓ Q7 - **生成 workflow.yaml？**

预览（根据以上回答生成）：
```yaml
mode: dag

orchestration:
  max_concurrent_agents: 16

agents:
  - id: analyzer
    agent: drive:analyzer
    depends_on: []
  - id: impl-auth
    agent: AuthImplementer
    depends_on: [analyzer]
  - id: impl-api
    agent: ApiImplementer
    depends_on: [analyzer]
  - id: reviewer
    agent: drive:code-reviewer
    depends_on: [impl-auth, impl-api]
    terminal: true
    verdict_required: true

complexity_rules:
  trivial:
    skip_agents: [reviewer]
```

校验：read_workflow.py --validate ✅（环检测通过、wave 计算正确、agent 引用全部解析）

**视觉预览**（plan-review HTML，与 drive 03-phase / 03-dag prototype 一致）：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/workflow-builder/scripts/render_dag.py" \
  --work-dir <work_dir> \
  --selected <第一个 gate 或第一个 agent> \
  --out <work_dir>/.workflow-preview.html
```

写入 `<work_dir>/.workflow-preview.html`。**告诉用户文件路径**，浏览器可打开看（DAG 图 + 选中节点详情 panel，drive-viz tokens 风格）。

➡️ 推荐：写入 workflow.yaml
➡️ 备份现有 workflow.yaml（如有）→ workflow.yaml.bak
```

## 关键约束（必须遵守）

- ❌ **不写 `stage: start`** —— start 由 drive 内部处理，不出现在 workflow.yaml
- ❌ **不创建 agent 文件** —— 只引用已存在的 `agents/<name>.md`
- ❌ **不破坏现有 workflow.yaml** —— 增量更新前先备份
- ✅ **不自动应用** —— 生成后必须用户确认才写入
- ✅ **每个 agent 必须有 `id` + `agent` + `depends_on`**
- ✅ **至少一个 `terminal: true` + `verdict_required: true`**
- ✅ **agent 用 4 种地址形式**：`drive:xxx` / 裸名 / `@-mention` / `plugin:xxx`
- ✅ **不输出 `background` 字段**（simplify-by-default）

## 自检清单（写入前必过）

- [ ] 没有 `mode: phase`（只生成 DAG）
- [ ] 没有 `background` 字段（simplify-by-default）
- [ ] 每个 agent 有 id、agent、depends_on
- [ ] 每个 agent 引用是 4 种地址之一
- [ ] 至少一个 `terminal: true` + `verdict_required: true`
- [ ] 所有 `depends_on` 引用解析得到目标 id
- [ ] DAG 无环（依赖拓扑排序）
- [ ] `validate_workflow.py` 返回 `ok: true`

## 边界

**不适用**：
- 改 `agents/<name>.md` 文件本身（用户应直接编辑 agent）
- 改 `read_workflow.py` 本身（drive 内部逻辑）
- 单纯阅读 workflow.yaml（用 Read 工具即可）
- 执行 workflow（用 drive skill）

**何时不激活**：
- 用户问"workflow 怎么用" → drive skill
- 用户问"某个阶段做什么" → 对应 agent 的 skill
- 用户问"为什么 workflow 失败" → 调试工具

## 详细文档（按需加载）

- **生成模板**：参考 `references/templates.md`（4 种常用 DAG 模板）
- **agent 目录**：参考 `references/agent-catalog.md`（drive 内置 agents + @-mention）
- **校验脚本**：参考 `references/validation.md`（read_workflow.py 用法）
- **常见陷阱**：参考 `references/gotchas.md`（DAG 专属 gotcha）
- **输出格式**：参考 `references/output-template.md`