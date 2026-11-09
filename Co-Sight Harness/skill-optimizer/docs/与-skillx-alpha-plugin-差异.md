# 对比：skill-optimizer vs skillx-alpha-plugin

> 记录于 2026-10-12。对比对象：
> - **A** = `cosight-harness/skill-optimizer`（本目录，移植版）
> - **B** = `cosight-code/plugins/skillx-alpha-plugin`（Cosight 原版）
> 方向：B → A 单向移植（非双向同步；A 是 B 的超集/演进版）。

## 0. 结论

A 与 B 是**同一套编排引擎**的两种形态：公共 99 个文件逐字节完全一致（含 `scripts/scorer/*`、`state_engine/*`、`optimizers/*`、`metrics/*`、`evaluators/*`、`hooks/*`、`framework_configs/{anti_patterns,knowledge,norms}/*`、`scripts/commands/skill_create.py` 等）。差异集中在四层：**① 运行宿主**、**② 新增功能**、**③ 目录布局平铺**、**④ 一处反向语义变化**。

## 1. 运行宿主（唯一根本差异）

| 维度 | B 原版 | A 移植版 |
|---|---|---|
| 目标宿主 | 仅 Cosight | Claude Code + Cosight + Codex + DSH（多 runtime） |
| 安装 | 根 `install.sh` → 只写 `~/.cosight` | `scripts/install.sh --runtime {claude,cosight,codex,dsh,all}` |
| 打包 | 无 | `scripts/pack.sh` → `dist/*.tar.gz` |
| 布局 | `.cosight/` + `.cosight-plugin/` | 顶层 `agents/ commands/ skills/ references/ rules/` + `.claude-plugin/` |
| 主文档 / 标识 | `COSIGHT.md` + `.cosight-plugin/{README,SKILLX}.md` | `CLAUDE.md` + `docs/{SKILLX,plugin-handbook,runtime-portability}.md` |
| 依赖清单 | 根 `requirement.txt` | `scripts/requirements.txt` |

## 2. A 新增功能（B 无对应物）

| 文件 | 作用 |
|---|---|
| `scripts/agent_runner.py` | 多 runtime 子 Agent 调度：`get_runner()` 按 `SKILLX_AGENT_CLI` 选 `ClaudeRunner` / `CodexRunner` / `DshRunner` / `CosightRunner` |
| `scripts/orchestrators/create_pipeline.py` | 无头 /skill_create 五阶段流水线（Phase A brief → B spec → C impl → D scaffold → E report） |
| `scripts/install.sh` | 多 runtime 安装 + `--scope project` + `DEST=` 离线 cp |
| `scripts/pack.sh` | tar.gz 打包发布 |
| `scripts/requirements.txt` | Python 依赖 |
| `agents/refactor-applier-agent.md` | `--mode refactor --auto-apply` 无头应用子 Agent（新增 agent） |
| `.claude-plugin/{plugin,marketplace}.json` | Claude 插件 manifest |
| `dist/*.tar.gz`（×2） | 打包产物 |
| `tests/*`（×5） | 契约 / agent_runner / cosight_install / create_pipeline / tools_agents_dir |
| `pytest.ini`、`.gitignore` | 工程化 |
| `docs/{plugin-handbook,runtime-portability,SKILLX}.md` | 移植配套文档 |

## 3. 目录平铺（机械重写，逻辑不变）

B 的 `.cosight/` 计作 A 顶层同名目录；同时做两组机械改写：
1. 路径前缀 `.cosight/skills/`、`.cosight/agents/`、`.cosight/rules/` → 顶层 `skills/`、`agents/`、`rules/`。
2. 占位符 `__COSIGHT_PLUGIN_ROOT__` → `$CLAUDE_PLUGIN_ROOT`；settings 文件名 `.cosight/settings.local.json` → `.claude/settings.local.json`。
3. 给原无 frontmatter 的 agent / `debug-pro` / `编码原则` 补写 frontmatter（`name` / `description` / `tools` / `model`）。

涉及文件（22 个）：`config/{create,evolve}-user-config.yaml`、`README.md`、`docs/*.md`(8)、`framework_configs/*.yaml/.md`(4)、`scripts/optimizers/static_agents.py`、`static_relations.py`、`static_evaluator_subprocess.py`、`scripts/orchestrators/{cleanup_hook,context_extractor,eval_pipeline,reports,workspace}.py`。

## 4. 实质逻辑差异（A 增强）

### 4.1 `scripts/tools.py`（差异约 194 行）

- **子 Agent 调用去 Cosight 特化**：`_call_cosight_pipe` 重命名为 `_call_claude_pipe`，整个 cosight 专属子进程体（`--allowedTools` 白名单、`--settings`、stream-json `/ --verbose`、自带超时与 jsonl 解析、中文观测打印）**折叠为一行委托** `_get_agent_runner().run(...)`，返回值 `(stdout, stderr, returncode, duration_sec, exception_str, raw_jsonl)` 6 元组契约不变。
- **插件根定位**：`_find_project_root` 优先读宿主注入的 `$CLAUDE_PLUGIN_ROOT` / `$COSIGHT_PLUGIN_ROOT`；无则向上找含顶层 `agents/` **或** `.cosight/agents/` 的根。
- **新增 `_plugins_agents_dir(root)`**：顶层 `agents/` 优先，回退 `.cosight/agents/`。
- **模型配置**：`_load_project_settings_env` 由"读项目 `.cosight/settings.json/.local.json` env 覆盖子进程"改为**返回空 dict**（Claude 子进程 `claude -p` 继承父会话 env，`$CLAUDE_PLUGIN_ROOT` 自动传递，无需再注入；保留函数仅维持签名稳定）。

### 4.2 `scripts/orchestrator.py`（差异约 160 行，全为新增）

- **`--mode` 新增 `create`**：委托 `create_pipeline.run_create_pipeline`（见 `_run_create_mode`），映射 `--create-*` / `--expert-guidance` / `--agent-cli`；流水线失败用 `sys.exit(rc)` 透出给 DSH/CI/脚本。
- **新增 `--agent-cli {claude,codex,dsh}`**：子 Agent runtime（`显式 --agent-cli > env SKILLX_AGENT_CLI > 默认 claude`）；create 模式下作 3 个子 Agent 的调度后端。
- **新增 `--auto-apply`**：refactor 模式 plan 草稿生成后，经 AgentRunner 调度 `refactor-applier-agent` 在 `after_skill/` 副本上应用剩余 ~20% 编辑（无 CC HITL）；含 `_refactor_auto_apply()`（读 5 份诊断文档 → 调度 applier → 重跑 automator → 跑 self-check），不传则保持原交互审批路径，向后兼容。

## 5. 反向语义变化（需留意）

### 5.1 `scripts/evaluators/workflow_pipeline.py`（差异 4 行）

- **B 原版**：`cmd = ["cosight", "-p", ...]`；校验 `if first != "cosight"`（只认 cosight）。
- **A 移植版**：`cmd = ["claude", "-p", ...]`；校验放宽为 `if first not in ("cosight", "claude")`（cosight / claude 都接受）。

> 校正说明：此节曾误写为反方向。逐行核验 `diff B A`（`<`=B 原版 / `>`=A 移植）确认：B 用 `cosight -p`，A 改用 `claude -p` 并把校验**放宽**。这也与 `tools.py` 中 `_call_cosight_pipe` → `_call_claude_pipe` 的重命名方向一致——A 以 Claude 为默认/原生执行宿主，同时保留对 cosight 的兼容（校验接受两者）。

## 6. B 独有（46 个，A 中已由顶层目录替代）

全部为 `.cosight/` 旧布局 + `COSIGHT.md` + 根 `install.sh` / `requirement.txt` + `.cosight-plugin/` manifest，以及**废弃快照** `scripts/evaluators/workflow_pipeline.py.snapshot_20260721_224335`（A 已删除这份过期备份）。

## 7. 文件级汇总

| 类别 | 数量 |
|---|---|
| A 文件总数 | 184 |
| B 文件总数 | 171 |
| 公共且完全相同 | 99 |
| 公共但内容有差异 | 27（其中实质逻辑 3：tools.py / orchestrator.py / workflow_pipeline.py） |
| A 独有 | 52（真新增 ~14 + 搬迁至顶层 ~38） |
| B 独有 | 46（旧 `.cosight` 布局 + 1 个废弃快照） |

## 8. 逐文件修改明细（27 个公共差异文件的改了什么）

> diff 方向：`diff B A`，即每行 `<`=B 原版，`>`=A 移植版。

### 8.1 实质逻辑改动（3 个）

**`scripts/tools.py`** — 子 Agent 调度去 Cosight 特化 + 多 runtime 委托：
```diff
- def _call_cosight_pipe(system, prompt, timeout, settings_path, output_format):
-     # ~130 行 cosight 专属子进程体：--allowedTools 白名单(剔 python3)/--settings/
-     #  stream-json 配--verbose/自带 timeout/jsonl 解析/中文观测打印
-     cmd = ["cosight", "-p", "--dangerously-skip-permissions", ...]
-     result = subprocess.run(cmd, ...); return (final_text, stderr, rc, dur, exc, raw_jsonl)
+ def _call_claude_pipe(system, prompt, timeout, settings_path, output_format):
+     """委托 agent_runner.get_runner() 选定的 provider（默认 claude）。"""
+     res = _get_agent_runner().run(system, prompt, timeout=..., settings_path=..., output_format=...)
+     return res.stdout, res.stderr, res.returncode, res.duration_sec, res.exception_str, res.raw_jsonl
```
- 函数重命名 `_call_cosight_pipe` → `_call_claude_pipe`（B 用 cosight，A 用 claude）。
- 导入新增 `from agent_runner import get_runner as _get_agent_runner`（A）。
- `_find_project_root`：B 只向上找 `.cosight/agents/`（5 次）；A 优先读 `$CLAUDE_PLUGIN_ROOT`/`$COSIGHT_PLUGIN_ROOT`，无则找顶层 `agents/` **或** `.cosight/agents/`（6 次）。
- 新增 `_plugins_agents_dir(root)`：顶层 `agents/` 优先，回退 `.cosight/agents/`（A）。
- `_load_project_settings_env`：B 读项目 `.cosight/settings.json/.local.json` env 覆盖子进程（含绕过 cosight router 的注释）；A 改为 `return {}`（claude 子进程继承父会话 env，保留签名）。
- `consume_lib` 别名：B `" ... ".cosight/methodology)` → A `references/methodology`。

**`scripts/orchestrator.py`** — 三种能力（全新增）：
- `--mode` choices 追加 `"create"`（B 无）+ 增加 `--create-skill-name` / `--create-requirement` / `--create-output-dir` / `--create-expert-guidance`（A）。
- 新增 `--agent-cli {claude,codex,dsh}`（A）：子 Agent runtime，`显式 > env SKILLX_AGENT_CLI > claude`。
- 新增 `--auto-apply` + `_refactor_auto_apply()`（A）：refactor 模式无头应用剩余 ~20% plan 编辑（读 4 份诊断文档 → 调度 `refactor-applier-agent` → 重跑 automator → self-check）。
- 新增 `_run_create_mode()`（A）：委托 `create_pipeline.run_create_pipeline`，失败 `sys.exit(rc)` 透出。
- `main` dispatch 新增 `if args.mode == "create"` 分支（A）。
- 大量路径字符串 `.cosight/` → 顶层（机械，见 8.2）。

**`scripts/evaluators/workflow_pipeline.py`** — 唯一"校验放宽"：
```diff
- if first != "cosight":                                      # B 只认 cosight
- cmd = ["cosight", "-p", command.strip(), "--dangerously-skip-permissions"]   # B 用 cosight
+ if first not in ("cosight", "claude"):                      # A 接受两者
+ cmd = ["claude", "-p", command.strip(), "--dangerously-skip-permissions"]    # A 默认 claude
```

### 8.2 机械改动（24 个，仅路径前缀/占位符/settings 文件名）

| 文件 | B 原版 | A 移植版 |
|---|---|---|
| `config/evolve-user-config.yaml` | 注释 `.cosight/settings.local.json` | `.claude/settings.local.json` |
| `config/create-user-config.yaml` | `~/.cosight/plugins/marketplaces/skillx-alpha/outputs` | `~/.claude/plugins/marketplaces/skillx/outputs` |
| `README.md` | 提及 `.cosight/` 自动发现、`.cosight/settings.local.json` | 改 `.claude/`；空占位 `` |
| `docs/架构澄清-外部依赖与解耦设计.md` | `Agent 的 .cosight/skills/` | `Agent 的 skills/` |
| `docs/重构案例-d7bcf0da-Skill组件间流程设计.md` | `.cosight/commands/skill_refactor.md` | `commands/skill_refactor.md` |
| `docs/重构后检查-等效性与回归测试.md` | `.cosight/rules/`、`.cosight/commands/`、`.cosight/agents/`、来源 `.cosight/knowledge/` | 顶层去 `.cosight` 前缀 |
| `docs/重构后检查-Skill完整性验证.md` | 来源 `.cosight/rules/shared/...`、grep `.cosight/commands/`、`.cosight/agents/` | 去 `.cosight` 前缀 |
| `docs/skill_create-第三章方案设计.md` | `.cosight/commands/skill_create.md`、`.cosight/agents/...`、`.cosight/ 目录树` | 顶层 |
| `docs/skill_create-方案设计.md` | 目录树 `.cosight/`、`.cosight/settings.local.json` | 顶层 + `.claude/` |
| `docs/skill_create-功能介绍.md` | `.cosight/commands/skill_create.md` | `commands/skill_create.md` |
| `docs/skill-create-用例-组件间流程设计.md` | `.cosight/commands/skill_create.md`、`.cosight/agents/...` | 顶层 |
| `framework_configs/eval-config.yaml` | 注释 `必须与 .cosight/agents/ 下的 agent 文件名一致` | `必须与 agents/ 下的` |
| `framework_configs/proposal-agent-config.yaml` | 注释 `.cosight/agents/proposal-agent.md`（3 处） | `agents/proposal-agent.md` |
| `framework_configs/skill-create-guidelines.md` | `.cosight/agents/skill-scaffolder-agent.md`、`.cosight/commands/skill_create.md`、`.cosight/agents/*` | 顶层 |
| `framework_configs/static-eval-config.yaml` | `secondary_files: [".cosight/agents/*.md"]`、`[".cosight/skills/*", ...]` | `["agents/*.md"]`、`["skills/*", ...]` |
| `scripts/optimizers/static_agents.py` | 读取 `.cosight/skills/编码原则/SKILL.md`、`.cosight/agents/skill-evaluator-agent.md`（4 处） | 顶层 |
| `scripts/optimizers/static_relations.py` | `.cosight/rules/skillx-alpha-generic.md` | `rules/skillx-alpha-generic.md` |
| `scripts/optimizers/static_evaluator_subprocess.py` | `agent_def_path = project_root / ".cosight" / "agents" / ...` | `project_root / "." / "agents" / ...` |
| `scripts/orchestrators/cleanup_hook.py` | `backup_roots: {"SkillName": ".../.cosight/skills/..."}` | `".../skills/..."` |
| `scripts/orchestrators/context_extractor.py` | `contract 见 .cosight/agents/proposal-agent.md` | `见 agents/proposal-agent.md` |
| `scripts/orchestrators/eval_pipeline.py` | 注释 `.cosight/skills/` | `skills/` |
| `scripts/orchestrators/reports.py` | `.cosight/agents/failure-analysis-agent.md`、`.cosight/agents/evolution-report-agent.md` | 顶层 |
| `scripts/orchestrators/workspace.py` | `.cosight/` 目录定位、`.cosight/skills/`（11 处） | 顶层 `skills/`、`.` |
| `scripts/orchestrators/context_extractor.py`（已列） | — | — |

> 说明：表内 `workspace.py` 的 A 改动用 `p / "." ` 与 top 层目录；`static_evaluator_subprocess.py` A 用 `/ "." / "agents"`（`.` 即顶层，等价于 `agents/`）。这些均为纯路径改写，不含行为变化。