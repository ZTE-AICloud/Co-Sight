# skillx-alpha-agents（cosight 唤起入口）

通用评测-优化循环编排器（Harness）。把业务方的"评测命令"包成「评测 → 缺口分析 → 优化 → 再评测」的闭环迭代，自动循环直到达标或达到最大轮次。

> **定位**：本项目是通用 Harness，不绑定任何具体业务。业务方通过参数和适配器配置注入评测管道，编排器只负责循环、状态、产物。

---

## 1. 项目定位（必须理解）

```
skillx-alpha-agents = 通用评测-优化循环编排器（Harness）
目标领域             = 任意业务方的 Agent 和 Skill
设计原则             = 通用可复用，不绑定任何具体业务场景
```

**Agent（你）是通用 Harness，不是某个具体业务的子组件。** 它负责：
- 接收任意 Skill + 评测配置 → 启动闭环迭代
- 在每轮中：执行评测 → 提取分数和缺口 → 生成优化提案 → 审批后应用
- 直到达标或达到最大轮次

**所有流程逻辑通过 orchestrator.py 实现，禁止在 COSIGHT.md 里写循环/评测/优化代码。**

---

## 2. 驱动入口

**业务方通过 `/skill_evolve` 子命令驱动整个流程，不需要直接调用 orchestrator.py。**

```bash
# 推荐(简化入参):把 cd ... && ... 拆成 --pipeline-base-dir + --pipeline-eval-cmd
/skill_evolve \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'

# 多 Skill 联合优化(Agent 模式)
/skill_evolve --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md,/path/to/Skill3/SKILL.md" \
  --agent-name MyAgent \
  --rounds 1 --candidates 2 --runs 2 \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'

# 纯 Python/shell 评测脚本(明确"非 slash command",跳过所有 wrap/extract/warn)
/skill_evolve --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md,/path/to/Skill3/SKILL.md" \
  --agent-name MyAgent \
  --rounds 1 --candidates 2 --runs 2 \
  --pipeline-base-dir /path/to/SDD评测Agent \
  --pipeline-eval-sh 'python3 run_pipeline.py --req-id RAN-3404224,RAN-3532502,RAN-3774273 --activity 需求分析 --sub-activity 用户需求分析'

# 兼容:旧式 cd ... && ... 仍可用,语义等价于上面的简化入参
/skill_evolve 'cd /path/to/SDD评测 && python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'
```

Agent 解析 `/skill_evolve` 参数后调用 `orchestrator.py`，业务方不需要关心 orchestrator 的内部参数。

**`/skill_evolve` → `orchestrator.py` 的参数映射**（必读，避免重复踩坑）：

| skill_evolve 参数 | orchestrator 参数 |
|------------------|------------------|
| `--rounds N` | `--max-rounds N` |
| `--candidates N` | `--candidates-per-round N` |
| `--runs N` | `--eval-runs-per-candidate N` |
| `--pipeline-base-dir DIR`（推荐） | 原值透传 |
| `--pipeline-eval-cmd "<cmd>"`（推荐） | 原值透传（含 slash command 自动 wrap）；与 `--pipeline-eval-sh` 互斥 |
| `--pipeline-eval-sh "<cmd>"`（推荐） | 原值透传（明确"纯 shell 不 wrap"）；与 `--pipeline-eval-cmd` 互斥 |
| 评测命令（位置参数,旧式兼容） | `--pipeline-eval-cmd "<cmd>"`（含完整 `cd ... && ...`） |
| `--consume-lib-path DIR` | 原值透传（落 `config.json` 顶层 `consume_lib_path`，被 `run_optimize_agent` 读取，注入 ProposalAgent prompt 顶部"全局视角知识库"块） |

**orchestrator.py 直接调用仅在调试时使用**（见第 5 节启动命令模板）。

**完整 command 总览**（`commands/`）：

| Command | 用途 | 何时用 | cosight 唤起 |
|---------|------|--------|-------------|
| `/skill_evolve` | 评测驱动优化（依赖业务方 eval-cmd） | 业务方有完整评测管道 | `node openclaw.mjs skillx-cosight evolve <SKILL> "<eval-cmd>"` |
| `/skill_optimize --mode optimize` | LLM 多维评分 + 多轮 hill-climb | 无 eval-cmd，用 LLM judge 打分 | `node openclaw.mjs skillx-cosight optimize <SKILL>` |
| `/skill_optimize --mode refactor` | 结构层重构（plan-mode 人机协同） | Skill 文件结构乱/超长/引用断裂 | (内部命令,直接调 `/skill_optimize`) |
| `/skill_create` | 从规格说明书创建新 Skill | 0→1 创建 Skill | (内部命令) |

> **2026-07 变更**：原 `/skill_refactor` 已合并到 `/skill_optimize --mode refactor`（命令层统一入口；底层 `static_refactor*.py` 脚本与 `skill-refactor-agent.md` 命名保留）。

---

## 3. 架构边界（必须遵守）

```
Agent（你）    = 理解意图 + 解析参数 + 调用 orchestrator.py + 处理异常
orchestrator  = 循环控制 + 状态管理 + 评测编排 + 优化网关 + 产物写入
Skill         = 被优化的目标文件（任意业务方提供的 SKILL.md）
Evaluator     = 评测接口（pipeline 模式：执行 → 对比打分 → 提取 JSON 分数）
Optimizer     = 多级 Fallback 优化器（reference-优化 → LLM patch → 最小修复）
Adapter       = 业务方评测适配器（YAML 配置，定义管道步骤、分数提取、产物格式）
```

**通用性要求：**
- orchestrator 和 Agent 不感知任何业务细节
- 评测配置由业务方通过 `framework_configs/*.yaml` + `config/user-config.yaml` 适配器配置注入
- gap 字段补全在 OptimizerGateway 内做通用推导，不依赖具体业务 schema
- 路径、模型等配置优先通过环境变量或 `.env` 注入，不硬编码

### 3.1 优化模式

| 模式 | `--optimization-mode` | 说明 |
|------|----------------------|------|
| **single** | `single`（默认） | 单 Skill 级别优化 |
| **agent** | `agent` | Agent 级别联合优化，多个 Skill 一起参与同一轮端到端评测，独立优化 |

**Agent 模式流程**：
```
for each round:
  所有 Skill 一起跑一次端到端评测 → 得到聚合分数 + gaps
  if aggregate_score >= target_score: break
  for each skill:
    optimize(skill, gaps)           # 各 Skill 基于端到端 gaps 独立优化
  生成联合审查报告
```

**关键点**：Agent 模式不是各 Skill 独立评分再平均，而是所有 Skill 一起执行一次端到端评测，一次产生所有 CASE 的分数，通过 mean 聚合得到整体分数。

### 3.2 评测步骤类型

`pipeline-config.yaml` 中每个 step 都有一个 `type` 字段，决定编排器如何执行：

| `type` | 执行方式 | 适用场景 |
|--------|---------|---------|
| **`script`**（默认） | `subprocess.Popen` 真实执行命令，stdout/stderr/exit-code 全捕获 | 业务方评测脚本、Python/Shell 命令 |
| `cosight_command` | `cosight -p "<command>"` LLM 模拟执行（不真跑） | 仅用于离线测试编排器行为，不接真实业务 |

**切换方式**：
```bash
# 通过环境变量切换默认 step type（默认 script）
EVAL_TYPE=cosight_command python3 scripts/orchestrator.py ...

# 或在 pipeline-config.yaml 的 steps[].type 中显式指定
```

---

## 4. 工作流状态机

```
/skill_evolve 请求（评测命令 + Skill 路径 + 目标分数/轮次）
    ↓
[init]     → 验证 Skill/工作空间 → 初始化 config.json
    ↓
[baseline] → 基线评测（当前 Skill 跑 N 次取平均）
    ↓
[decide]   → 达标 → 终止 | 未达标 → 继续
    ↓
[candidate]→ 生成 K 个候选方案 → 各候选评测 → 选最优
    ↓
[optimize] → 基于最优候选生成优化提案 → 审批 → 应用
    ↓
[loop]     → 回到 baseline，直到达标或达到最大轮次
    ↓
[finish]   → 生成审查报告
```

---

## 5. 调试用启动命令模板

> 业务方日常使用通过 `/skill_evolve` 子命令。以下命令仅在调试 orchestrator 时使用。

```bash
# 单 Skill 模式（pipeline 模式）
SKILLX_WORKSPACE="/path/to/evolution_workspace" \
  python3 scripts/orchestrator.py \
  --skill-path "/path/to/SKILL.md" \
  --pipeline-base-dir "/path/to/eval/" \
  --pipeline-eval-cmd "python3 <your_eval_script>.py --arg value" \
  --max-rounds 5 --non-interactive

# 多 Skill 模式（Agent 联合优化）
SKILLX_WORKSPACE="/path/to/evolution_workspace" \
  python3 scripts/orchestrator.py \
  --optimization-mode agent \
  --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md,/path/to/Skill3/SKILL.md" \
  --agent-name "MyAgent" \
  --pipeline-base-dir "/path/to/eval/" \
  --pipeline-eval-cmd "python3 <your_eval_script>.py --arg value" \
  --max-rounds 5 --non-interactive
```

**默认行为**：每次运行创建新 taskid 目录（旧 taskid 保留在 evolution_workspace/ 下）。如需复用已存在的 taskid 目录，需显式将完整路径作为 `--workspace` 传入。

### 分数聚合

pipeline 模式固定使用 **mean 聚合**（所有 CASE 平均分作为整体分数），确保每个测试用例都纳入评估。

---

## 6. 环境配置

### 6.1 路径派生规则

`SKILLX_ROOT` 在 `_load_eval_env_from_dotenv()` 中自动拼接以下 3 个子路径（仅在子路径未通过其他方式设置时）：

| 子路径 | 拼接规则 | 默认值 |
|--------|---------|--------|
| `SDD_EVAL_DIR` | `SKILLX_ROOT/ran_sdd` | `/media/vdb/skillx-alpha/ran_sdd` |
| `SKILLX_WORKSPACE` | `SKILLX_ROOT/evolution_workspace` | `/media/vdb/skillx-alpha/evolution_workspace` |
| `SKILLX_SANDBOX_ROOT` | `SKILLX_ROOT/sandbox` | `/media/vdb/skillx-alpha/sandbox` |

`SDD_DIR_NAME=SDD评测` 是路径段，**不通过根目录派生**，因为它是 SDD 评测内部的固定子目录名。

**优先级链**（不破不立）：
1. CLI 参数（最高）
2. 系统环境变量
3. 配置默认值

切换部署位置时，通过环境变量 `SKILLX_ROOT` 注入根目录即可。

### 6.3 模型架构（双模型）

测试（Skill 执行）和优化（生成提案）两个阶段使用独立模型，避免互相干扰。

| 阶段 | 用途 | CLI 参数 | 环境变量 |
|------|------|----------|----------|
| **测试（评测执行）** | 跑业务方评测命令（Skill 真实执行） | 不调 LLM | 不调 LLM |
| **评分提取** | ExtractionAgent 自主探查 `data/`、填空式两阶段生成 `score_analysis.md` + `score.json` | 复用优化模型 | `ANTHROPIC_MODEL` |
| **优化/分析** | 生成优化提案、诊断分析 | `--model-reasoning` | `ANTHROPIC_MODEL` |

**评分提取实际行为**（`analyze_run`）：第一次 LLM 调填 md 模板 → 第二次 LLM 调填 json 模板（同一份 MD 作为输入，确保 per_case map 与 MD 一致）。**两次 LLM 调均用 `ANTHROPIC_MODEL`**，未单独配置。

**各阶段模型未配置时自动回退到全局默认值**。

---

## 7. 项目目录结构

### 7.1 评测数据布局（沙箱内 `data/`）

评测产物生成在 `data/` 目录下，分四个 phase（具体名称由业务方适配器配置定义）：

```
data/
├── phase1-build/
│   ├── e2e-sets/                  # 金标准测试集（评测对比基准，沙箱不清理）
│   └── sub-activity-sets/         # Skill 产物（每轮清理，避免"抄答案"）
├── phase2-exec/
│   ├── execution_log_*.json       # 执行日志
│   └── traces/{session_id}/       # Agent 工具调用轨迹
├── phase3-eval/
│   └── eval-{活动名}-{timestamp}.json   # 结构化评测结果（ExtractionAgent 探查的主要数据源）
└── phase4-diagnosis/              # L3 聚合分析（超时风险、行为聚类等）
```

**分数提取原则**：由 ExtractionAgent 自主用 Bash/Read/Grep 探查 `data/`，按 `config/user-config.yaml` 声明的规则计算 `result_score`。典型 phase3-eval JSON 含 f1、recall、precision、rule_path、differences 等字段（业务方约定形态,框架不强求）。

### 7.2 workspace 输出目录

每次运行创建独立的 `taskid_YYYYMMDD_HHMMSS` 目录，老任务数据默认保留不清理。

```
evolution_workspace/                    # 演化任务统一存放（不污染 Agent 自身目录）
└── taskid_20260604_123103/             # 每次运行的独立任务目录（实测参考）
    ├── config.json                     # Agent 级状态（多 Skill）/ Skill 级状态（单 Skill）
    ├── task_state.json                 # 进度状态（current + rounds 双 section）
    ├── score_history.md                # 分数历史（基线/候选/统计/CASE 明细）
    ├── skill_进化报告.md               # Agent 进化报告（仅多 Skill 模式）
    ├── skill/                          # workspace 副本（单数 skill/，按 SkillName 分子目录）
    │   └── {SkillName}/SKILL.md
    ├── best_skill/                     # 整体最佳 Skill 副本（跨 baseline + 所有候选的最高分）
    │   ├── best_skill_info.json        # 来源：source / source_round / source_candidate
    │   └── {SkillName}/SKILL.md
    ├── baseline/                       # 基线评测产物
    │   ├── proposal.md                 # baseline 优化提案
    │   ├── score_baseline.json         # baseline 聚合分（所有 run 合并）
    │   ├── score_baseline_analysis.md  # baseline 评分分析
    │   └── run_{M}/                    # 每个 run 独立
    │       ├── score.json
    │       ├── score_analysis.md
    │       └── data/                   # 沙箱 data/ 归档
    └── round_{N}/
        ├── round_{N}_score.json        # round 分数（所有候选聚合）
        ├── round_{N}_score_analysis.md # round 报告
        ├── round_{N}_before_skill/     # 优化前 Skill 快照
        │   └── skill/{SkillName}/SKILL.md
        ├── round_{N}_after_skill/      # 优化后 Skill 快照
        │   └── skill/{SkillName}/SKILL.md
        └── candidate_{K}/              # 每个候选独立子目录
            ├── candidate_{K}_score.json
            ├── candidate_{K}_score_analysis.md
            ├── skill/                  # 该候选的 Skill 副本
            │   └── {SkillName}/SKILL.md
            ├── run_1/
            │   ├── score.json
            │   ├── score_analysis.md
            │   └── data/
            └── run_2/
                └── ...
```

**关键命名约定**：
- **Skill 副本用单数 `skill/`**：里面按 SkillName 分目录；单 Skill 与多 Skill 模式统一
- **before/after 快照带 `round_N_` 前缀**：`round_1_before_skill/`、`round_1_after_skill/`
- **Round 分数/报告带 `round_N_` 前缀**：`round_1_score.json`、`round_1_score_analysis.md`
- **候选分数带 `candidate_K_` 前缀**：`candidate_1_score.json`、`candidate_1_score_analysis.md`
- **进化报告用中文文件名**：`skill_进化报告.md`
- **进度状态用**：`task_state.json`
- **`best_skill/` 整体最佳**：跨 baseline + 所有候选的最高分 Skill 副本，便于直接复制回原位置

**workspace 路径优先级：**
1. `--workspace` CLI 参数（最高）
2. `SKILLX_WORKSPACE` 环境变量（可配置，推荐设为基础目录，不含 taskid）
3. 自动推断：`{skill_path 的 Agent 父目录的祖父目录}/evolution_workspace/`

自动推断后会直接在 evolution_workspace 下创建 `taskid_YYYYMMDD_HHMMSS/` 子目录。**默认每次运行创建新 taskid**（旧 taskid 保留在 evolution_workspace/ 下）。如需复用已存在的 taskid 目录，需显式将完整路径作为 `--workspace` 传入。

---

## 8. 业务方适配器

业务方评测脚本接入 skillx-alpha-agents 的标准方式。配置分两层：

| 层级 | 位置 | 维护方 | 用途 |
|------|------|--------|------|
| **framework 内部** | `framework_configs/*.yaml` | framework 维护者 | 评分模板、提案 schema 等固定框架逻辑 |
| **业务方配置** | `config/user-config.yaml` | 业务方 | 唯一编辑入口,声明路径/产物结构/算分规则 |

**`config/user-config.yaml`** 用 `{{ user.xxx }}` 占位符注入到 framework YAML 的 `extraction.task` 段,框架加载时由 `scripts/config_layered.py` 渲染。

**最小可用配置**（注入到 orchestrator 的方式）：

```bash
# 方式 A：通过 --pipeline-base-dir + --pipeline-eval-cmd 快捷模式
python3 scripts/orchestrator.py \
  --pipeline-base-dir /path/to/eval/ \
  --pipeline-eval-cmd "python3 <your_eval_script>.py --arg value" \
  --skill-path /path/to/SKILL.md

# 方式 B：通过 --pipeline-config 指定完整 YAML
python3 scripts/orchestrator.py \
  --pipeline-config /path/to/eval/adapter.yaml \
  --skill-path /path/to/SKILL.md
```

方式 A 由编排器自动生成 `pipeline-config.yaml`,适合快速跑通;方式 B 适合复杂场景(自定义清理路径、归档、诊断等)。

---

## 9. 占位符

| 占位符 | 含义 |
|--------|------|
| `{workspace}` | 演化任务工作目录（通过 `--workspace` 或 `SKILLX_WORKSPACE` 环境变量配置） |
| `{taskid}` | 任务 ID 目录名（格式 `taskid_YYYYMMDD_HHMMSS`，每次运行自动创建） |
| `{skill_path}` | 目标 Skill 路径（绝对路径、相对路径、裸名称） |
| `{target_score}` | 目标分数（默认 100） |
| `{max_rounds}` | 最大轮次（默认 5） |
| `{pipeline_base_dir}` | 业务方评测流程根目录 |
| `{pipeline_eval_cmd}` | 业务方评测命令 |

---

## 10. 强制约束

1. **必须通过 orchestrator.py 执行循环**：不在 COSIGHT.md 里写 Python heredoc / Bash 循环
2. **通用性第一**：不写死业务字段、不假设特定 Skill 结构，gap 补全在 OptimizerGateway 通用处理
3. **路径优先走环境变量**：禁止硬编码绝对路径，使用 `SKILLX_ROOT` 等环境变量派生
4. **分数聚合固定 mean**：所有 CASE 平均分作为整体分数，不因某个高分提前终止
5. **N/A 分数归零**：候选为空/分母为零的 N/A 场景记为 0 分，而非跳过
6. **每轮必存 before/after 快照**：无论优化成功、失败、被拒绝，都要保存
7. **优化后 skill 用于下轮评测**：workspace skill 被更新后，下一轮沙箱 staging 自动使用更新后的版本
8. **Gold 不修改**：`r_result/` 目录下文件仅用于评测对比
9. **禁止全量重写 SKILL.md**：优化器只能修改需要改动的 H2 章节
10. **达标即终止**：达到目标分数后立即停止
11. **orchestrator.py 执行不设超时**：该命令通过 LLM 调用评测管道，单次评测可能耗时很长，Bash 工具调用时**禁止设置 timeout 参数**，使用 `run_in_background: true` 后台运行后轮询状态
12. **分数为零必须定位原因**：每次评测后检查分数是否为 0，如果为 0 必须定位根因并修复

---

## 11. 调试与测试约束（重要）

1. **禁止创建临时脚本文件**：调试 orchestrator 时不要创建 `.sh`、`.py` 等临时测试文件到项目目录中。直接在命令行执行 orchestrator 命令即可。如需多次测试参数，用 Bash 的 heredoc 或内联命令，不落地文件。
2. **评测产物不污染代码目录**：评测生成的中间文件、日志、配置文件应写入 `evolution_workspace/` 下的任务目录，不得留在 `scripts/` 或项目根目录。
3. **测试后清理**：调试过程中创建的临时 workspace 任务目录如无保留必要，应在测试结束后删除。

---

## 12. 异常处理

| 场景 | 处理方式 |
|------|---------|
| orchestrator 报错 | 读取 config.json 恢复状态，重新调用 orchestrator |
| 提案被拒绝 | 记录到 round_{N}/proposal.md（内容为拒绝原因），继续下一轮 |
| 达到最大轮次 | orchestrator 记录完成状态 |
| Skill 文件不存在 | 列出所有可用 Skill 让用户选择 |
| N/A 分数 | 归零处理，计入平均分 |
| 优化器所有 Tier 失败 | 保存 after 快照（等于 before），继续下一轮 |
| 分数为 0（BROKEN） | 必须定位根因（评测框架 bug / Skill 产出不匹配 / cosight agent 执行失败），修复后重跑 |
| **进程被 `kill -9` 强杀（SIGKILL）** | atexit / signal handler **不会触发**，无法自动恢复原路径。需手动 `rm -rf {SkillName}.bak/` + 从 git 恢复原始 SKILL.md；config.json 里的 `user_source_bak` 字段也会残留，下一次启动时 `_safe_restore_all` 会自动尝试恢复（若 `.bak` 仍在则恢复成功，否则 noop + warning） |

---

## 13. `/skill_optimize` 优化+重构二合一入口（v2 合并 refactor）

**定位**：与 `/skill_evolve` **并列**的命令。**无业务方 eval-cmd** 时使用。统一两个 mode：

| mode | 用途 | 何时用 |
|------|------|--------|
| `--mode optimize`（默认） | LLM judge 9 维评分 + 多轮 hill-climb | 内容质量不达标（描述模糊、缺失败模式、缺检查点） |
| `--mode refactor` | 结构层重构（plan-mode 人机协同） | 文件结构乱、章节超长、引用断裂 |

### 13.0 `--mode optimize`（静态优化闭环，v1 原功能）

```
业务方 Skill 资产（SKILL.md + scripts + references）
        ↓
LLM judge 9 维评分（不依赖外部 eval-cmd）
        ↓
md 文件 → SkillOptimizerAgent（直接 Edit）
代码文件 → CodeOptimizerAgent（强制加载"编码 skill"4 原则）
        ↓
应用 → 评分 → 若回退则从 before snapshot 文件系统恢复
        ↓
连续 2 轮 Δ < break-threshold → 触顶停止
```

#### 用法（optimize 模式）

```bash
# 最简：只传 Skill 路径（默认 mode=optimize）
/skill_optimize --mode optimize --skill-path /path/to/SKILL.md

# 带专家经验指引（自然语言）
/skill_optimize --mode optimize --skill-path /path/to/SKILL.md \
  --expert-guidance "评审文档必须按 [背景/方案/风险/验证] 四段式输出"

# 完整参数
/skill_optimize --mode optimize --skill-path /path/to/SKILL.md \
  --rounds 3 \
  --max-files 5 \
  --break-threshold 3 \
  --expert-guidance "<自然语言指引>"
```

### 参数映射（→ orchestrator.py）

| skill_optimize 参数 | orchestrator 参数 |
|---------------------|-------------------|
| `--skill-path PATH` | `--skill-path PATH` |
| `--rounds N` | `--max-rounds N` |
| `--max-files N` | `--max-files N` |
| `--protected-assets "a,b,c"` | `--protected-assets "a,b,c"` |
| `--break-threshold N` | `--break-threshold N` |
| `--expert-guidance "TEXT"` | `--expert-guidance "TEXT"` |
| `--no-revert` | `--no-revert` 标志 |

### 与 `/skill_evolve` 串联使用

```bash
# Step 1: 静态优化打底
/skill_optimize --mode optimize --skill-path /path/to/SKILL.md --rounds 3

# Step 2: 评测驱动拉满(推荐用简化入参)
/skill_evolve --skill-path /path/to/SKILL.md \
  --rounds 5 --candidates 3 --runs 3 \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'
```

### 关键文件清单

| 文件 | 作用 |
|------|------|
| `commands/skill_optimize.md` | **合并后**统一命令契约（optimize + refactor 二合一） |
| `agents/skill-evaluator-agent.md` | 9 维评分子 Agent |
| `agents/skill-optimizer-agent.md` | md 文件优化子 Agent |
| `agents/code-optimizer-agent.md` | 代码文件优化子 Agent（强制加载编码 skill） |
| `agents/skill-refactor-agent.md` | refactor 模式 LLM 诊断 Agent（仅产 findings JSON） |
| `skills/编码skill/` | 符号链接 → `~/skills/编码skill/` |
| `framework_configs/static-eval-config.yaml` | framework rubric + patterns + safety |
| `config/optimize-user-config.yaml` | 业务方 per-skill 配置（与 evolve-user-config.yaml 完全独立） |
| `scripts/optimizers/static_optimizer.py` | 主循环 + 4 层安全网 |
| `scripts/optimizers/static_html_history.py` | v13 P1-7：score_history.html 生成 |
| `scripts/orchestrator.py` 的 `_run_static_mode` | optimize 模式 dispatch |
| `scripts/orchestrator.py` 的 `_run_refactor_mode` | refactor 模式 dispatch（数据收集） |
| `scripts/optimizers/static_refactor.py` | refactor LLM prompt + 写 refactor_diagnosis.md |
| `scripts/optimizers/static_refactor_automator.py` | refactor 自动应用 80% 深度改动 |

### 13.1 `--mode refactor`（结构层重构，原 `/skill_refactor`，v2 合并）

**核心模型**：orchestrator 只做数据收集（关系树 + LLM 诊断），CC 承担 plan / apply / verify 全流程，必走 EnterPlanMode 两次。

```
orchestrator 数据收集:
  Step1   → build_relation_tree → skill_file_relations.json
  Step1b  → shutil.copytree source → before_skill/  (回滚源,永不改)
  Step1c  → shutil.copytree source → after_skill/   (CC 的 Edit 目标)
  Step2   → run_diagnose → refactor_diagnosis.md   (findings + cluster_observations)
  Step2.5 → run_plan_draft → refactor_plan_draft.md (8 步 plan 自动草稿)
  Step3   → run_automator → refactor_automator_report.md (自动应用 80% 深度改动)
        ↓
CC 接管:
  Step R.5 → Read 诊断 + 5 份重构/检查文档
  Step R.6 → Read SKILL.md 全文
  Step R.4 → EnterPlanMode#1: 合成 8 步 plan (对标 d7bcf0da 7 大类)
  Step R.5 → 在 after_skill/ 副本上 Read + Edit (源文件永不改)
  Step R.6 → 出最终报告 (5 节对标 d7bcf0da) + 调 --mode refactor-diff-report + --mode refactor-self-check
  Step R.7 → EnterPlanMode#2 展示报告,等用户确认完成
```

#### 用法（refactor 模式）

```bash
# 最简：只传 Skill 路径
/skill_optimize --mode refactor --skill-path /path/to/SKILL.md

# 带专家经验指引 + 显式 workspace
/skill_optimize --mode refactor --skill-path /path/to/SKILL.md \
  --workspace /path/to/refactor_workspace \
  --expert-guidance "评审文档必须按 [背景/方案/风险/验证] 四段式输出"
```

#### 关键约束（refactor 模式）

- **禁止改源文件**（live skill_root `{X}`） — 所有 Edit 必须在 `{W}/after_skill/{SkillName}/` 副本上进行
- **必走 EnterPlanMode 两次**（Step R.4 合成 plan + Step R.7 确认完成）
- **必用 before_skill/ 快照回退**：`cp -r before_skill/{SkillName}/* after_skill/{SkillName}/*`
- **不接收** `--agent-path` / `--max-files` / `--protected-assets` / `--break-threshold` / `--per-skill-rounds` / `--no-revert` / `--score-mode`

> 详细 SOP、AskUserQuestion 题目、8 步 plan 模板、实战教训（Step 1.5 source 链预检、Step 4.5 中间层保留）见 `commands/skill_optimize.md` 的 `## mode == refactor` 段。

### 13.2 v13 新增能力（HITL 三层守关 + 归因拆分 + 3 auto 维度 + HTML 报告）

**借鉴来源**：mangooai/skills-radar 仓库的 evaluation(16 框架)+ optimization(27 框架)分类，对应 Darwin-Skill / SkillAdaptor / SkillGrad / Skill Coverage / SkillSafetyBench / SkillReducer / agent-skills-eval 等开源/研究框架的设计思想。

| 能力 | 配置段 | 行为 |
|------|--------|------|
| **HITL 三层守关** (P0-1) | `hitl.{pass_threshold, revert_threshold, on_human_review}` | `delta ≥ pass_threshold` → auto_pass；`delta ≤ revert_threshold` → auto_revert；中间地带 → human_review（默认 `auto_accept`，可通过 CLI 改 `interactive`） |
| **LLM judge 多轨迹** (P0-2,已实现) | `eval_runs` | 默认 3 次取均值 + subprocess 子进程隔离（v11 B） |
| **归因-修改两步拆分** (P0-3) | prompt 内置 diagnosis + gradient_analysis 段 | 单次 LLM 调用先输出诊断再输出 modifications，降低 LLM 改动随机性（SkillAdaptor） |
| **dim10_coverage 维度** (P1-4) | `enabled_dimensions.dim10_coverage: true` | Python 自动算 rubric 高分覆盖率（Skill Coverage 借鉴） |
| **dim11_safety 维度** (P1-5) | `enabled_dimensions.dim11_safety: true` | Python 关键词扫描 prompt injection，命中 ≥2 条即 reject（SkillSafetyBench） |
| **dim12_efficiency 维度** (P1-6) | `enabled_dimensions.dim12_efficiency: true` | Python 算 token 相对 baseline 增量（SkillReducer） |
| **proposal 信号分解** (P1-8) | prompt 内置 gradient_analysis | learning_rate / momentum / signal_decomposition 四字段（SkillGrad 借鉴） |
| **HTML 可视化报告** (P1-7) | 产物 `{workspace}/score_history.html` | 单文件 echarts CDN + fallback 表格，与 PNG 雷达图并存（agent-skills-eval 借鉴） |

**配置优先级链**：CLI > `config/optimize-user-config.yaml` > framework YAML 默认值。

**3 个 auto 维度的设计原则**：`compute_mode: auto` 表示 Python 端直接算分，不交给 LLM judge（防 SAP8 自评幻觉）。维度名称、阈值、关键词、公式全部在 `framework_configs/static-eval-config.yaml` 的 `rubric.dim{N}_xxx` 段定义，业务方通过 `optimize-user-config.yaml.enabled_dimensions` 启用。Python 端不维护维度枚举硬编码，未来新增 auto 维度只需扩 YAML + 加一个 elif 分支。
