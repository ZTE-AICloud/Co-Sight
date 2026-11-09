---
name: skill_evolve
description: 围绕业务方评测命令做迭代进化 — 评测 → 缺口分析 → 优化 → 循环直到达标
argument-hint: "[--pipeline-base-dir DIR] [--pipeline-eval-cmd <cmd> | --pipeline-eval-sh <cmd>] [--rounds N] [--candidates N] [--runs N] [--skill-paths PATH1,PATH2,PATH3] [--agent-name NAME] [--consume-lib-path DIR] [--expert-guidance TEXT]"
---
> **插件根目录**: 解析顺序——① `$CLAUDE_PLUGIN_ROOT`(Claude Code 宿主注入) ② `$COSIGHT_PLUGIN_ROOT`(Cosight 宿主注入) ③ 兜底：从当前工作目录逐级向上，找到同时含 `agents/` 与 `framework_configs/` 的目录。本文件统一记为 `$PLUGIN_ROOT`。
>
> 本文件及本插件其它组件中出现的相对路径（如 `agents/…`、`skills/…`、`scripts/…`、`framework_configs/…`、`config/…`、`docs/…`、`references/…`）均相对于该插件根目录解析，而不是当前工作目录。需要读取或引用这些资源时，请使用完整绝对路径：`$PLUGIN_ROOT/<相对路径>`。


## 🧾 交互方式:纯文本编号提问(全插件统一,禁用 AskUserQuestion)

上游非 Anthropic 模型无法正确调用 AskUserQuestion(严格 schema 校验必失败,
UI 报 "Invalid tool parameters",实测 2026-08-20 连把 `questions` 数组序列化成
字符串都发生过)。**本插件禁止使用 AskUserQuestion**,一切用户交互一律
用纯文本编号提问:

- 在回复正文输出编号问题列表(1. / 2. / 3. …),每条含问题 + 选项列表(若适用);
- 请用户直接回复编号或文本(可一次回复全部编号,如 "1、2、3 全确认");
- 用户回复后按答案继续后续流程;流程**绝不因交互中断或报错**。

本节之后各处的 Q1/Q2/Q3 及其选项内容全部不变,只是改为文本呈现,
**不使用任何交互工具弹出**。


# skill_evolve 迭代进化

## 核心模型

```
业务方 eval-cmd（一次性命令） → orchestrator 包裹它做循环迭代
评测 → 提取分数和缺口 → 生成优化提案 → 应用 → 再评测 → 直到达标
```

**你不需要理解 orchestrator 的内部参数，只需要提供你的评测命令。**

> **推荐写法（简化入参）**：把 `cd X && python3 ...` 拆成两个独立参数 —— `--pipeline-base-dir X` 提供 cwd、`--pipeline-eval-cmd "..."` 提供命令本体。语义和旧式完全等价，但更便于复用、调试、二次确认。
>
> **等价关系**：
> - 旧式 `cd <DIR> && <CMD>` ≡ 新式 `--pipeline-base-dir <DIR> --pipeline-eval-cmd "<CMD>"`
> - 当 `<CMD>` 是 cosight slash command（以 `/` 开头,如 `/sdd-eval ...`）时，orchestrator 自动包成 `cd <DIR> && cosight -p "<CMD>" --dangerously-skip-permissions`（cwd 来自 base_dir）

## 用法

> 下面按推荐度排序；旧式 `cd ... && ...` 写法作为"兼容性备选"保留在最末。

```bash
# ★ 推荐 1:单 Skill 模式 + 简化入参(Python 评测命令)
/skill_evolve \
  --skill-paths /path/to/SKILL.md \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'

# ★ 推荐 2:多 Skill 模式(Agent 联合优化)+ 简化入参
/skill_evolve \
  --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md,/path/to/Skill3/SKILL.md" \
  --agent-name 需求分析Agent \
  --rounds 3 --candidates 2 --runs 2 \
  --pipeline-base-dir /path/to/SDD评测Agent \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'

# ★ 推荐 3:简化入参 + cosight slash command(自动 wrap 为 cosight -p)
/skill_evolve \
  --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md" \
  --pipeline-base-dir /path/to/SDD评测Agent \
  --pipeline-eval-cmd '/sdd-eval --req-id RAN-3404224,RAN-3532502 --activity 需求分析 --sub-activity 用户需求分析'

# ★ 推荐 4:纯 Python/shell 评测脚本(明确"非 slash command",跳过所有 wrap/extract/warn)
/skill_evolve \
  --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md" \
  --pipeline-base-dir /path/to/SDD评测Agent \
  --pipeline-eval-sh 'python3 run_pipeline.py --req-id RAN-3404224,RAN-3532502,RAN-3774273 --activity 需求分析 --sub-activity 用户需求分析'

# 兼容:旧式 cd ... && ... 写法(语义等价于简化入参,保留作位置参数兼容入口)
/skill_evolve --skill-paths /path/to/SKILL.md \
  'cd /path/to/SDD评测 && python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--pipeline-base-dir` | **推荐**：评测命令的工作目录（cwd）。等价于旧式 `cd X &&` 前缀的 `X` | 自动从 base_dir 派生 |
| `--pipeline-eval-cmd` | **推荐**：评测命令本体（去掉 `cd` 前缀）。slash command（以 `/` 开头）会自动包成 `cosight -p` | 与 `--pipeline-eval-sh` 互斥 |
| `--pipeline-eval-sh` | **推荐**：明确"纯 shell 命令"，**不触发**任何 slash-command 自动 wrap/extract/warn 处理。不接受 `cd X &&` 前缀；cwd 用 `--pipeline-base-dir` 注入 | 与 `--pipeline-eval-cmd` 互斥 |
| **eval-cmd（位置参数）** | 业务方评测命令（可为 `cd X && CMD` 旧式或 `/slash-cmd` 新式） | — |
| `--skill-paths` | SKILL.md 路径列表，逗号分隔（单路径=单 Skill 模式，多路径=Agent 模式） | 从 eval-cmd 推断 |
| `--agent-name` | Agent 名称（可指定，多 Skill 模式自动从 Skill 路径推断） | 自动推断 |
| `--rounds` | 最大迭代轮次 | 5 |
| `--candidates` | 每轮生成候选数 | 1 |
| `--runs` | 每个候选的评测次数（取平均） | 3 |
| `--workspace` | 工作目录 | 自动推断 |
| `--consume-lib-path` | 全局视角知识库根目录（consume_lib）。注入到 ProposalAgent prompt 顶部，让 LLM 跳出 case 局部修补、用领域方法论/反模式/最佳实践从更高维度优化 | 不传则不注入 |
| `--expert-guidance` | 专家指引（自然语言）。**写入 config.json 的 `expert_guidance` 字段**，注入 ProposalAgent prompt 顶部"🧑‍💼 专家指引"块，作为本轮优化方向的首要参考。**任务中可编辑**：用户发现问题后直接改 `{taskid}/config.json` 的 `expert_guidance`，下一轮 ProposalAgent 读到新值引导优化 | 不传则不注入 |

**互斥关系**：
- `--pipeline-base-dir` + `--pipeline-eval-cmd`（推荐）vs 位置参数 eval-cmd（兼容）—— 二选一；后传入者生效并覆盖前者
- `--pipeline-eval-cmd` vs `--pipeline-eval-sh` —— 二选一（argparse 互斥组，同时传则 fail-fast）。前者承担 slash command 自动 wrap，后者明确表达"纯 shell 不 wrap"
- `--skill-paths` 单路径 = 单 Skill 模式，多路径（≥2）= Agent 模式（不再有 `--skill-path` 单数参数）

**`--consume-lib-path` 用法**：
- 路径：consume_lib 知识库根目录（业务方维护的领域知识/方法论/反模式库）
- 注入位置：`run_optimize_agent` 的 ProposalAgent prompt 顶部（"## 🌍 全局视角知识库"段）
- 作用语义：**全局知识**，不是修补当前 case 的工具。LLM 应在开工前用 Read/Grep 探查，提炼领域方法论/反模式清单/跨场景共性原则，带着这些**全局视角**再看 phase3-eval 的 differences——如果发现某 case 的问题其实是全局原则没贯彻，改一次就能修一族
- 落盘：写入 `workspace/config.json` 的 `consume_lib_path` 字段，子进程续跑可恢复
- 留空（默认）：不注入，零副作用

## 执行流程

### 单 Skill 模式（`--skill-paths` 单路径）

1. 封装 eval-cmd → 通过 `--pipeline-eval-cmd` 传入 orchestrator
2. 每轮沙箱隔离执行 eval-cmd → 提取分数 → 未达标则优化 Skill → 下一轮
3. 产物输出：before/after 快照 + 分数报告 + 优化提案

### 多 Skill 模式（`--skill-paths` 多路径）

1. 封装 eval-cmd → 通过 `--optimization-mode agent --skill-paths` 传入 orchestrator
2. 每轮沙箱隔离执行 eval-cmd（所有 Skill 一起参与） → 提取聚合分数
3. 对各 Skill 分别生成优化提案 → 应用 → 下一轮
4. 产物输出：Agent 级 config + skills/ 目录 + 联合审查报告

## 二次确认流程（CC 必走）

> **目的**：命令行参数已含全部信息，但 `case_ids` / `need_cleaned_dir` / 迭代强度是易错点，CC 在拼 orchestrator 命令前**必须**用纯文本编号提问二次确认（禁用 AskUserQuestion），避免误跑。`/skill_evolve` 启动后第一件事就是进入此流程。

### 流程

**Step 1：解析 CLI 参数**

从 `$ARGUMENTS` 中提取：
- `--skill-paths`（逗号分隔的 SKILL.md 路径列表；单路径即单 Skill 模式）
- `--rounds` / `--candidates` / `--runs`
- `--pipeline-base-dir` / `--pipeline-eval-cmd`
- 位置参数（评测命令）
- 是否多 Skill：`--skill-paths` 是否含 2 个及以上

**Step 2：读取配置文件参考值**

- 从 `config/evolve-user-config.yaml` 读 `paths.need_cleaned_dir`（清理目录列表，YAML list）
- 不读取 `filter.case_ids`（应从 `--pipeline-eval-cmd` 解析，避免重复源）

**Step 3：纯文本编号提问 3 题**（按上方"🧾 交互方式"规则列出 Q1/Q2/Q3,不使用 AskUserQuestion）

**Q1 · 评测范围**（header: "评测范围"，必问）
- 用命令行传入的 N 个 CASE（推荐）
- 调整子集（让用户选 Other 填新列表）
- 跑全量（覆盖 `evolve-user-config.yaml` 的 case_ids 过滤）

**Q2 · 清理目录**（header: "清理目录"，必问；**不提供"跳过清理"**）
- 用配置文件中的 M 个目录（推荐）
- 我手动指定（让用户选 Other 填逗号分隔路径）
- ⚠️ 禁止提供"跳过清理"选项 —— 会读到上次产物造成误判

**Q3 · 产物结构配置确认**（header: "产物结构配置"，必问）
- 确认 `execution_traces` 和 `score_extraction` 无误，沿用 `evolve-user-config.yaml`（推荐）
- 我要修改（让用户选 Other，写清改哪个字段 + 改成什么内容）

**Step 4：拼最终命令并等 1 句确认**

**🛑 拼命令前先校验 `--pipeline-base-dir` 路径（防评测目录写错/加空格）**：
- 用 `ls -d {pipeline-base-dir}` 确认评测目录**真实存在**——不存在则评测命令找不到脚本，baseline 直接 0 分、评测不执行。
- **⚠️ 目录名不能误加空格**：实测偶发错误——`SDD评测Agent`（无空格，正确）被写成 `SDD 评测 Agent`（有空格，目录不存在）。`ls -d` 会暴露此问题。
- 若 `ls` 失败，检查是否空格问题，向用户确认正确路径后再拼命令（**不要**带空格发起）。

CC 输出拼出的最终 orchestrator 命令（`--optimization-mode` / `--max-rounds` / `--candidates-per-round` / `--eval-runs-per-candidate` / `--skill-paths` / `--pipeline-base-dir` / `--pipeline-eval-cmd` / `--non-interactive`），并等待用户 1 句确认（"确认" / "启动" / 回车均视为通过；要改则说 "修改 xxx"）。

**workspace 路径规则（重要）**：
- **不要在命令里显式传 `--workspace`**——orchestrator 会按以下派生链自动生成 taskid 目录:
  1. 读 `config/evolve-user-config.yaml` 的 `paths.root`(YAML 配置,**不要硬编码**)
  2. 拼上 `evolution_workspace/` 子目录名(framework 约定)
  3. 自动创建 `taskid_YYYYMMDD_HHMMSS/` 子目录
- **只有以下两种情况**才传 `--workspace`:
  1. 用户明确要求"用临时目录"/"在 /tmp 下"等
  2. 业务方提供了具体的 workspace 路径(如 `--workspace /path/to/existing/workspace` 复用已存在 taskid)
- 派生规则由 `scripts/orchestrators/workspace.py:_load_eval_env_from_dotenv()` + `state_engine` 共同实现,改路径改 YAML 即可,**不要在命令契约里写死路径**

**Step 5：后台启动**

- 用 `Bash` 工具 `run_in_background: true` 启动 orchestrator
- **禁止设 `timeout`**（长跑任务可能跑几十分钟）
- 启动后告知用户 taskid 和后台任务 ID，让用户能继续等系统通知

### 硬约束

- **始终全问 3 题**（用户决策），不因命令行已传而跳过任何问题
- **不在 Q2 提供"跳过清理"选项**（避免误判）
- **选项描述只描述含义不预填具体值**（保持简洁 + 不污染上下文）
- **必须等用户 1 句最终确认**后再启动
- **启动后必须用 `run_in_background: true` + 禁止 `timeout`**

---

## 约束

- eval-cmd 必须在执行完成后返回分数信息（stdout/文件均可）
- 未指定 `--skill-paths` 时从当前工作目录自动推断
- 多 Skill 模式可指定 `--agent-name`，不传时自动从 Skill 路径推断
- 默认非交互模式（自动批准优化提案）
- **参数映射**：调用 orchestrator.py 时必须做以下映射：
  - `--rounds N` → `--max-rounds N`
  - `--candidates N` → `--candidates-per-round N`
  - `--runs N` → `--eval-runs-per-candidate N`
  - `--pipeline-base-dir DIR` → 原值透传（orchestrator 内部存为 `pipeline_base_dir`）
  - `--pipeline-eval-cmd CMD` → 原值透传（orchestrator 内部存为 `pipeline_eval_cmd`）；若为旧式位置参数 `cd X && CMD`，CC 须自行拆出 base_dir 后转成简化入参
  - 兜底（旧式）：位置 eval-cmd → `--pipeline-eval-cmd`（含完整 `cd ... && ...`），由 `_auto_wrap_slash_command` 提取 cd 与 slash command
  - `--consume-lib-path DIR` → 原值透传（orchestrator 内部存为 `consume_lib_path`，落 `config.json` 顶层）

**目标分数**：硬编码为 100（`DEFAULT_TARGET_SCORE`），不再提供 `--score` 参数。如需自定义目标分数，请直接修改 `scripts/state_engine/__init__.py` 中的 `DEFAULT_TARGET_SCORE` 常量。
