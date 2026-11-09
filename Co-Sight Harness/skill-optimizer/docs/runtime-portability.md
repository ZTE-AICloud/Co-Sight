# Runtime 可移植性（Claude Code / Cosight / Codex / DSH）

> 本文件说明 skill-optimizer 如何在 **Claude Code**、**Cosight**、**Codex**、**DSH**
> 四个 runtime 下安装与运行，以及各 runtime 的能力差异与降级行为。改动背景与目标见
> 插件的 skill-optimizer 迁移记忆（移植自 skillx-alpha 插件）。
>
> **Cosight 是"原生宿主"**（`@zte/cosight-cli`），与 Claude Code 平行而非从其插件派生：
> 有独立的 `~/.cosight/plugins/` registry 与 `cosight -p`（参数面 ≈ `claude -p`）。

## TL;DR

- 一身代码，四处入口：**`install.sh` 的 `--runtime {claude,cosight,codex,dsh,all}`** 决定装到哪个平台。
- 核心调度已无头化：`scripts/orchestrator.py`（纯 Python）+ `scripts/agent_runner.py`
  （AgentRunner）在任意 runtime 下用 `python3 scripts/orchestrator.py --mode ...` 直接运行，
  **不被单个宿主的 Agent 工具绑架**。
- Claude Code 下 `/skill_optimize /skill_evolve /skill_create` 仍是交互式斜杠命令（默认路径，向后兼容）；
  Codex / DSH 下是**无头入口**——内容就是调用 orchestrator.py。
- Cosight 下经 `cosight -p` 驱动子 Agent（`SKILLX_AGENT_CLI=cosight`），命令面与 claude 同构，
  支持 stream-json 工具审计，并注入项目级 `.cosight/settings.json` env（项目模型 / 绕 router）。
- 同一份 `install.sh --from pkg.tar.gz --runtime <X>` 可将同一制品装到任意平台（pack.sh 产物含全部无头组件）。

## 1. 安装

```bash
cd skill-optimizer

# Claude Code（默认，等价于原来的 install.sh）
./scripts/install.sh --runtime claude

# Cosight（原生宿主：快照到 $COSIGHT_HOME/plugins/marketplaces/skillx/ + .cosight/ 生成）
./scripts/install.sh --runtime cosight

# Codex（快照到 $CODEX_HOME/skillx-optimizer/ + 斜杠命令 + AGENTS.md 托管块）
CODEX_HOME=$HOME/.codex ./scripts/install.sh --runtime codex

# DSH（快照到 $DSH_HOME/skillx-optimizer/ + dev/commands/skill_*.md）
DSH_HOME=$HOME/.dsh ./scripts/install.sh --runtime dsh

# 自动探测已装 CLI，逐个安装
./scripts/install.sh --runtime all

# 从 pack.sh 制品装到指定 runtime
./scripts/pack.sh && ./scripts/install.sh --from dist/skill-optimizer-*.tar.gz --runtime all
```

各 runtime 的扩展点/环境变量可在 install 时覆盖：

| runtime | 同步目标（可覆盖） | 命令/入口 |
|---|---|---|
| claude | `~/.claude/plugins/marketplaces/skillx/` | `/skill_*` 斜杠命令 |
| cosight | `$COSIGHT_HOME/plugins/marketplaces/skillx/` | `cosight -p` + 项目 `.cosight/settings.json` env |
| codex | `$CODEX_HOME/skillx-optimizer/` | `$CODEX_HOME/prompts/skill_*.md` + `AGENTS.md` 托管块 |
| dsh   | `$DSH_HOME/skillx-optimizer/` | `$DSH_HOME/skillx-optimizer/dev/commands/skill_*.md` |

> codex/dsh 下无需 Claude Code 的插件注册/打包；只要同目录的 `scripts/`（含 `orchestrator.py`）
> 可被 `python3` 运行即可。子 Agent 定义（`agents/*.md`）由 `tools._find_agents_dir`
> 沿 `scripts/` 向上定位到含顶层 `agents/` 的同步根，无需 `$CLAUDE_PLUGIN_ROOT`。

## 2. 运行入口

三处入口跑的是同一套**无头编排**，映射关系：

| 语义命令 | orchestrator 真实模式 | 关键参数 |
|---|---|---|
| `/skill_optimize --mode optimize` | `--mode static` | `--skill-path <SKILL.md> \| --agent-path <Agent根>` |
| `/skill_optimize --mode refactor` | `--mode refactor`（可加 `--auto-apply`） | `--skill-path <SKILL.md> --workspace <W>` |
| `/skill_create` | `--mode create` | `--create-skill-name` / `--create-requirement` / `--create-output-dir` |
| `/skill_evolve` | `--mode eval` | `--pipeline-base-dir` / `--pipeline-eval-cmd`（或 `--pipeline-eval-sh`） |

> 注意 orchestrator 的真实 `--mode` 取值不含字面量 `optimize`/`evolve`；
> 那是命令文档的语义名，实际调用时映射为上表（codex/dsh 的 prompt 文件已内嵌该映射）。

命令行直跑：

```bash
# 显式选 runtime（优先级: --agent-cli > 环境变量 SKILLX_AGENT_CLI > 默认 claude）
python3 scripts/orchestrator.py --mode create \
  --create-skill-name aws-cdk-deploy \
  --create-requirement "@docs/req.md" \
  --create-output-dir /tmp/skill_x \
  --non-interactive --agent-cli codex
```

## 3. 能力降级矩阵

AgentRunner 按 `get_runner()` 选择 CLI 并组装命令。唯一无法跨 runtime 复用的是
**子 Agent 工具审计**（claude / cosight 的 `stream-json`），codex/dsh 下该段自动跳过，不阻断主链路。

| 能力 | claude | cosight | codex | dsh |
|---|---|---|---|---|
| system 提示注入 | `--append-system-prompt` | `--append-system-prompt` | 临时 `AGENTS.md` | prompt 内联 `system\n\n# TASK\n<prompt>` |
| 工具白名单 | `--allowedTools <CSV>` | `--allowedTools <CSV>` | `--allow-tools <CSV>` | 尽量映射 / 降级 |
| 权限跳过 | `--dangerously-skip-permissions` | `--dangerously-skip-permissions` | `--sandbox danger-full-access` | 同（写盘需对应沙箱） |
| 项目 env 注入 | — | `.cosight/settings.json` env（绕 router / 项目模型） | — | — |
| 子 Agent 工具审计(`stream-json`) | ✅ | ✅ | ❌ 降级 text | ❌ 降级 text |
| 交互式审批(HITL) | 纯文本编号提问 | 同 | 同 | 同 |
| LLM judge 直连 | ✅（config+env 驱动，天然可移植） | ✅ | ✅ | ✅ |

> **cosight 与 claude 命令面同构**，`CosightRunner` 复用 `ClaudeRunner` 的命令构造；
> 唯一差异是 **binary 为 `cosight`** 与 **注入项目级 `.cosight/settings.json` env**
> （`_load_project_settings_env`，仅 cosight 走；claude/codex/dsh 不注入，保持现有后端兼容）。

- **流式 JSON 工具审计**：claude / cosight 产生 `raw_jsonl`；codex/dsh 返回 `None`，
  现有 `_summarize_tool_use_from_jsonl` 已容错跳过（不影响评分）。
- **HITL**：全插件统一**纯文本编号提问**（禁用 `AskUserQuestion`——上游非 Anthropic 模型无法调用），
  `--non-interactive` / `--decisions-file`（预留）提供无头通道（CI / dsh / dsh headless）。

## 4. 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `SKILLX_AGENT_CLI` | runtime 选择（`claude` / `cosight` / `codex` / `dsh`） | `claude` |
| `SKILLX_AGENT_ALLOWED_TOOLS` | claude/codex 工具白名单 CSV | `Read,Write,Edit,Bash(...),Glob,Grep` |
| `SKILLX_AGENT_ALLOWED_TOOLS_OFF` | 置任意值关闭工具白名单 | 空（开） |
| `SKILLX_AGENT_SKIP_PERMISSIONS_OFF` | 置任意值关闭权限跳过 | 空（开） |
| `SKILLX_AGENT_CODEX_TOOLS` | codex `--allow-tools` 覆盖 | fallback `SKILLX_AGENT_ALLOWED_TOOLS` |
| `SKILLX_AGENT_SANDBOX` | codex `--sandbox` 覆盖 | `danger-full-access` |
| `SKILLX_CURRENT_TASK_DIR` | 落盘约定目录（源插件兼容） | — |
| `COSIGHT_PLUGIN_ROOT` | 宿主注入的 Cosight 插件根（`_find_agents_dir` 优先，同 `CLAUDE_PLUGIN_ROOT`） | — |

优先级：显式 `--agent-cli` > 环境变量 `SKILLX_AGENT_CLI` > 默认 `claude`。

> **Cosight 注册表**（`install_cosight` 幂等写入）：`$COSIGHT_HOME/plugins/known_marketplaces.json`
> 登记 `skillx`；`installed_plugins.json` 的 `skill-optimizer@skillx` 指向 marketplaces 路径；
> `$COSIGHT_HOME/settings.json` 的 `enabledPlugins` 拉通该插件。顶层组件为唯一权威，
> `.cosight/` 快照与 `.cosight-plugin/` manifest 由 install 阶段生成，二次执行不重复叠加。

## 5. 无头流水线（create）阶段

`--mode create` 是无头五阶段流水线，子 Agent 经 AgentRunner 子进程调度：

| Phase | 产物 | 硬校验（已代码化，复用） |
|---|---|---|
| A 输入 | `01_<brief>.md`（`@file` 直拷 / 自然语言） | — |
| B 规格 | `02_skill_spec.md` | 16 项硬约束，失败回灌 ≤2 |
| C 单体 | `03_monolithic_impl.md` | `wc -l ≥50` |
| D 工程化 | `04_skill_dir/{skill}/` | 骨架 8 项 + 覆盖度 6 组，失败补全 ≤2 |
| E 报告 | `final_report.md` | 终检：规格/骨架强校验 + 覆盖度顾问 |

失败即中止并透出非零退出码（DSH / CI 可据此判断）；全成功返回 0。

## 6. 向后兼容

- **默认仍是 claude + 现有交互审批**，`--runtime` 未传时行为与旧 `install.sh` 完全一致。
- 新增 provider / `--mode create` / `--auto-apply` 全部 opt-in。
- `tools.Agent()` 的 6 元组返回契约未变，`_call_claude_pipe` 只是委托给 AgentRunner。
- 旧制品可继续用 `pack.sh` + `install.sh --from ...`（默认 claude）。