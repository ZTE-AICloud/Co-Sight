---
description: "Agent 工厂入口：创建或优化 Agent。参数（目标目录、--input-dir、--knowledge-workflow-id）随后书写。"
argument-hint: "[需求描述] [--input-dir <目录>] [--knowledge-workflow-id <id>]"
allowed-tools: Skill, Read, Bash
---

# /harness-create — 带参入口

本命令只做一件事：**把参数原样带到 `harness-create` 技能**，并保证在参数不丢失的前提下启动流程。

执行步骤：

1. 调用 Skill 工具加载 `harness-create`（插件内名称为 `agent-genesis:harness-create`）。
2. 加载后，把下面「本次输入」整段作为该技能的第一步输入，然后严格按技能正文的 Step 序列执行。
3. 若「本次输入」为空：先问用户要做创建的 Agent 是什么、目标目录放哪里，再继续；不要凭空补参数。

## 本次输入

$ARGUMENTS

## 宿主差异（重要）

- **Claude Code**：上面的 `$ARGUMENTS` 已由命令展开，直接使用。
- **DSH**：技能与命令共用一个注册表，同名技能 `harness-create` 先占位，因此本命令在
  DSH 中被挂载为 **`/genesis-harness-create`**（偏好裸名时可直接用同名技能 `/harness-create`）。
  兼容层**不做 `$ARGUMENTS` 语法替换**——原始参数就在用户本次消息里
  `/genesis-harness-create` 之后的同一行文本中，以上面段落为空为准，回去读用户消息。
  若用户消息里也没有参数，向用户确认，不要假定默认目录。
- 技能内部禁止依赖 `Skill({name}, args=...)` 传递参数——DSH 的 `skill` 工具只接受
  `name`。参数只能来自本命令正文、用户消息或已落盘的 `.agent-genesis/` 文件。

## 参数含义

| 参数 | 含义 |
|---|---|
| 自然语言需求 | 要创建的 Agent 描述；越具体澄清轮次越少 |
| `--input-dir <目录>` | 输入资产目录，识别 `<目录>/knowledge.json` |
| `--knowledge-workflow-id <id>` | 直接指定 RAG 工作流 id，优先于 `knowledge.json` |
| `--platform <claude-code\|dsh\|both>` | 产物平台；缺省 `claude-code`，详见技能「平台适配」节 |
