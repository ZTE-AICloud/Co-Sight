# Agent 目录参考

读取当前项目可用的 agents（每次构建时动态扫描，必须读 frontmatter 的 `name:` 字段，不能用文件名推名字）：

```bash
# 项目本地 agent（递归扫描 .claude/agents/ 下所有 .md）
find <work_dir>/.claude/agents -name "*.md" -exec grep -l "^name:" {} \; | xargs grep "^name:"

# Drive 内置 agent
ls <plugin_root>/agents/*.md
```

agent 身份以 `name:` frontmatter 为准（不是文件名）。`name:` 不含 `:`，这是 scoped 地址规则的设计依据。

## Scoped 地址规则

workflow.yaml 的 `agent` 字段必须用以下三种写法之一：

| 写法 | 含义 | 例子 |
|------|------|------|
| `drive:<name>` | drive 插件内置 agent | `drive:analyzer`, `drive:planner` |
| 裸名 | 项目本地 agent（匹配 `name:` frontmatter）| `ProtocolAnalyzer` |
| 内置 subagent 类型（白名单） | Claude Code 内置 | `general-purpose`, `Explore`, `Plan`, `claude` |

写错格式或引用不存在的 agent 都会被 `read_workflow.py` 拦截并报错。

## Drive 插件内置 agents

drive 插件自带这些 agents（在 `03-drive-core/agents/`，以 `name:` frontmatter 为准）：

| agent 名称 | 用途 | 典型用于 | workflow.yaml 写法 |
|-----------|------|---------|-------------------|
| analyzer | 分析需求、生成 manifest | analyze 阶段 | `agent: drive:analyzer` |
| planner | 拆分任务、生成 plan | plan 阶段 | `agent: drive:planner` |
| executor | 执行 task、生成产物 | execute 阶段 | `agent: drive:executor` |
| evaluator | 质量评估、生成 verdict | evaluate 阶段 | `agent: drive:evaluator` |
| code-reviewer | 代码审查 | 自定义 review 阶段 | `agent: drive:code-reviewer` |
| security-reviewer | 安全审查 | 自定义 security 阶段 | `agent: drive:security-reviewer` |

> **Wave 拓扑计算是确定性 helper，不是 agent**——见 `skills/wave-scheduling/scripts/topo_sort.py schedule-waves`，由 planner 经 `wave-scheduling` skill 直接调 CLI。

## 常见组合

| workflow 用途 | 推荐 agents |
|--------------|-------------|
| 代码开发 | drive:analyzer → drive:planner → drive:executor → drive:evaluator |
| 代码审查 | drive:code-reviewer → drive:security-reviewer |
| 安全审计 | drive:security-reviewer → drive:code-reviewer |
| 数据分析 | drive:analyzer → drive:executor(analysis mode) → drive:evaluator |
| 测试驱动 | drive:planner → drive:executor → drive:evaluator |

## 用户自定义 agents

项目本地 agent 放在 `<work_dir>/.claude/agents/<name>.md`，文件里的 `name:` frontmatter 字段是 agent 标识。workflow.yaml 中写裸名（不带 `drive:` 前缀）引用：

```yaml
- stage: custom
  agent: ProtocolAnalyzer    # 匹配 .claude/agents/.../...md 的 name: ProtocolAnalyzer
```

**不会**与 drive 内置 agent 冲突（前者裸名、后者带 `drive:` 前缀）。同名也不会互相劫持。