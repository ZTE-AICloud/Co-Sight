# skillx-alpha-agents 使用指南（workflow 段）

> 本文档承接 `COSIGHT.md` 的硬规则段，**所有具体 workflow 在这里**。
> 硬规则（11 条不可违反）见 [COSIGHT.md](../COSIGHT.md)。

---

## 1. 驱动入口

业务方通过 `/skill_evolve` 或 `/skill_optimize` 子命令驱动整个流程，不需要直接调用 orchestrator.py。

### 1.1 `/skill_evolve` — 评测驱动

```bash
# 推荐(简化入参):把 cd ... && ... 拆成 --pipeline-base-dir + --pipeline-eval-cmd
/skill_evolve \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'

# 多 Skill 联合优化(Agent 模式)
/skill_evolve --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md" \
  --agent-name MyAgent \
  --rounds 1 --candidates 2 --runs 2 \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'

# 纯 Python/shell 评测脚本(明确"非 slash command",跳过所有 wrap/extract/warn)
/skill_evolve --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md" \
  --agent-name MyAgent \
  --rounds 1 --candidates 2 --runs 2 \
  --pipeline-base-dir /path/to/SDD评测Agent \
  --pipeline-eval-sh 'python3 run_pipeline.py --req-id RAN-3404224,RAN-3532502 --activity 需求分析 --sub-activity 用户需求分析'

# 兼容:旧式 cd ... && ... 仍可用
/skill_evolve 'cd /path/to/SDD评测 && python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'
```

**`/skill_evolve` → `orchestrator.py` 的参数映射**：

| skill_evolve 参数 | orchestrator 参数 |
|------------------|------------------|
| `--rounds N` | `--max-rounds N` |
| `--candidates N` | `--candidates-per-round N` |
| `--runs N` | `--eval-runs-per-candidate N` |
| `--pipeline-base-dir DIR`（推荐） | 原值透传 |
| `--pipeline-eval-cmd "<cmd>"`（推荐） | 原值透传（含 slash command 自动 wrap）；与 `--pipeline-eval-sh` 互斥 |
| `--pipeline-eval-sh "<cmd>"`（推荐） | 原值透传（明确"纯 shell 不 wrap"）；与 `--pipeline-eval-cmd` 互斥 |
| 评测命令（位置参数,旧式兼容） | `--pipeline-eval-cmd "<cmd>"` |

### 1.2 `/skill_optimize` — 静态优化（无 eval-cmd）

```bash
# 最简：只传 Skill 路径
/skill_optimize --skill-path /path/to/SKILL.md

# 带专家经验指引（自然语言）
/skill_optimize --skill-path /path/to/SKILL.md \
  --expert-guidance "评审文档必须按 [背景/方案/风险/验证] 四段式输出"

# 完整参数
/skill_optimize --skill-path /path/to/SKILL.md \
  --rounds 3 --max-files 5 \
  --protected-assets "references/standard-extraction-report.md" \
  --break-threshold 3
```

**`/skill_optimize` → `orchestrator.py` 的参数映射**：

| skill_optimize 参数 | orchestrator 参数 |
|------------------|------------------|
| `--skill-path PATH` | `--skill-path PATH` |
| `--agent-path DIR` | `--agent-path DIR` |
| `--rounds N` | `--max-rounds N` |
| `--per-skill-rounds N` | `--per-skill-rounds N` |
| `--max-files N` | `--max-files N` |
| `--protected-assets "a,b,c"` | `--protected-assets "a,b,c"` |
| `--break-threshold N` | `--break-threshold N` |
| `--expert-guidance "TEXT"` | `--expert-guidance "TEXT"` |
| `--no-revert` | `--no-revert` 标志 |
| `--restore-best` | `--restore-best` 标志（默认关闭） |
| `--score-mode {llm_direct\|subagent}` | `--score-mode {llm_direct\|subagent}` |

---

## 2. 工作流状态机

```
/skill_evolve 或 /skill_optimize 请求
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

## 3. 调试用启动命令模板

业务方日常使用通过 `/skill_evolve` 或 `/skill_optimize`。以下命令仅在调试 orchestrator 时使用：

```bash
# /skill_evolve 单 Skill 模式（pipeline 模式）
SKILLX_WORKSPACE="/path/to/evolution_workspace" \
  python3 scripts/orchestrator.py \
  --skill-path "/path/to/SKILL.md" \
  --pipeline-base-dir "/path/to/eval/" \
  --pipeline-eval-cmd "python3 <your_eval_script>.py --arg value" \
  --max-rounds 5 --non-interactive

# /skill_evolve 多 Skill 模式（Agent 联合优化）
SKILLX_WORKSPACE="/path/to/evolution_workspace" \
  python3 scripts/orchestrator.py \
  --optimization-mode agent \
  --skill-paths "/path/to/Skill1/SKILL.md,/path/to/Skill2/SKILL.md" \
  --agent-name "MyAgent" \
  --pipeline-base-dir "/path/to/eval/" \
  --pipeline-eval-cmd "python3 <your_eval_script>.py --arg value" \
  --max-rounds 5 --non-interactive
```

**默认行为**：每次运行创建新 taskid 目录。如需复用已存在的 taskid 目录，需显式将完整路径作为 `--workspace` 传入。

---

## 4. 环境配置

### 4.1 路径派生规则

`SKILLX_ROOT` 在 `_load_eval_env_from_dotenv()` 中自动拼接以下 3 个子路径：

| 子路径 | 拼接规则 | 默认值 |
|--------|---------|--------|
| `SDD_EVAL_DIR` | `SKILLX_ROOT/ran_sdd` | `/media/vdb/skillx-alpha/ran_sdd` |
| `SKILLX_WORKSPACE` | `SKILLX_ROOT/evolution_workspace` | `/media/vdb/skillx-alpha/evolution_workspace` |
| `SKILLX_SANDBOX_ROOT` | `SKILLX_ROOT/sandbox` | `/media/vdb/skillx-alpha/sandbox` |

`SDD_DIR_NAME=SDD评测` 是路径段，**不通过根目录派生**。

**优先级链**（不破不立）：
1. CLI 参数（最高）
2. 系统环境变量
3. 配置默认值

切换部署位置时，通过环境变量 `SKILLX_ROOT` 注入根目录即可。

### 4.2 双模型架构

测试（Skill 执行）和优化（生成提案）两个阶段使用独立模型。

| 阶段 | 用途 | CLI 参数 | 环境变量 |
|------|------|----------|----------|
| **测试（评测执行）** | 跑业务方评测命令 | 不调 LLM | 不调 LLM |
| **评分提取** | 自主探查、填空式生成 score.json | 复用优化模型 | `ANTHROPIC_MODEL` |
| **优化/分析** | 生成优化提案、诊断分析 | `--model-reasoning` | `ANTHROPIC_MODEL` |

---

## 5. 项目目录结构

### 5.1 评测数据布局（沙箱内 `data/`）

```
data/
├── phase1-build/
│   ├── e2e-sets/                  # 金标准测试集（评测对比基准）
│   └── sub-activity-sets/         # Skill 产物（每轮清理）
├── phase2-exec/
│   ├── execution_log_*.json       # 执行日志
│   └── traces/{session_id}/       # Agent 工具调用轨迹
├── phase3-eval/
│   └── eval-{活动名}-{timestamp}.json   # 结构化评测结果
└── phase4-diagnosis/              # L3 聚合分析
```

### 5.2 workspace 输出目录

每次运行创建独立的 `taskid_YYYYMMDD_HHMMSS` 目录：

```
evolution_workspace/
└── taskid_YYYYMMDD_HHMMSS/
    ├── config.json                 # 状态（含 history）
    ├── task_state.json             # 进度状态
    ├── score_history.md            # 分数历史
    ├── best_skill/                 # 跨轮最佳 Skill 副本
    ├── baseline/                   # 基线产物
    │   ├── run_{M}/
    │   └── score.json
    └── round_{N}/                  # 轮次产物
        ├── before/skill/
        ├── after/skill/
        ├── candidate_{K}/run_{M}/
        └── score.json
```

**安全网**：
- 修改后默认**不覆盖**原 skill 路径（`--restore-best` 默认关闭）
- 业务方审查通过后**手动**复制 `best_skill/` 到原位置

---

## 6. 业务方适配器

业务方评测脚本接入 skillx-alpha-agents 的标准方式。配置分两层：

| 层级 | 位置 | 维护方 | 用途 |
|------|------|--------|------|
| **framework 内部** | `framework_configs/*.yaml` | framework 维护者 | 评分模板、提案 schema 等固定框架逻辑 |
| **业务方配置** | `config/user-config.yaml` | 业务方 | 唯一编辑入口，声明路径/产物结构/算分规则 |

**最小可用配置**：

```bash
# 方式 A：通过 --pipeline-base-dir + --pipeline-eval-cmd 快捷模式
python3 scripts/orchestrator.py \
  --pipeline-base-dir /path/to/eval/ \
  --pipeline-eval-cmd "python3 <your_eval_script>.py --arg value" \
  --skill-path /path/to/SKILL.md

# 方式 A 变体：纯 shell 命令用 --pipeline-eval-sh（与 --pipeline-eval-cmd 互斥）
python3 scripts/orchestrator.py \
  --pipeline-base-dir /path/to/eval/ \
  --pipeline-eval-sh "python3 <your_eval_script>.py --arg value" \
  --skill-path /path/to/SKILL.md

# 方式 B：通过 --pipeline-config 指定完整 YAML
python3 scripts/orchestrator.py \
  --pipeline-config /path/to/eval/adapter.yaml \
  --skill-path /path/to/SKILL.md
```

方式 A 由编排器自动生成 `pipeline-config.yaml`，适合快速跑通；方式 B 适合复杂场景。

---

## 7. 占位符

| 占位符 | 含义 |
|--------|------|
| `{workspace}` | 演化任务工作目录（通过 `--workspace` 或 `SKILLX_WORKSPACE` 环境变量） |
| `{taskid}` | 任务 ID 目录名（格式 `taskid_YYYYMMDD_HHMMSS`） |
| `{skill_path}` | 目标 Skill 路径（绝对路径、相对路径、裸名称） |
| `{target_score}` | 目标分数（默认 100） |
| `{max_rounds}` | 最大轮次（默认 5） |
| `{pipeline_base_dir}` | 业务方评测流程根目录 |
| `{pipeline_eval_cmd}` | 业务方评测命令 |

---

## 8. 异常处理

| 场景 | 处理方式 |
|------|---------|
| orchestrator 报错 | 读取 config.json 恢复状态，重新调用 orchestrator |
| 提案被拒绝 | 记录到 round_{N}/proposal.md（内容为拒绝原因），继续下一轮 |
| 达到最大轮次 | orchestrator 记录完成状态 |
| Skill 文件不存在 | 列出所有可用 Skill 让用户选择 |
| N/A 分数 | 归零处理，计入平均分 |
| 优化器所有 Tier 失败 | 保存 after 快照（等于 before），继续下一轮 |
| 分数为 0（BROKEN） | 必须定位根因（评测框架 bug / Skill 产出不匹配 / cosight agent 执行失败），修复后重跑 |

---

## 9. 自我验证工具

### 9.1 校验 SKILL.md frontmatter 极简

```bash
python3 scripts/validate_skills.py <skill_root>
```

校验项：
- `name` + `description` 非空
- `description` ≤ 100 字
- frontmatter 字段 ≤ 3 个（仅 `name` + `description` + `protected_assets`）
- 重复 name 检测

**业务方跑 `/skill_optimize` 前**建议先跑一次，确保 SKILL.md 合规。

### 9.2 借鉴自 steipete/agent-scripts 的最佳实践

skillx-alpha-agents 在"skill 瘦身"上参考了 [steipete/agent-scripts](https://github.com/steipete/agent-scripts)：
- AGENTS.MD 只放硬规则，workflow 在外（已采用）
- frontmatter 极简 2~3 字段（已采用）
- description 短触发短语（已采用）
- Skill body 极简 + references/ 承载深度（已采用）

---

## 10. 多 Skill 模式 vs 单 Skill 模式

| 模式 | `--optimization-mode` | 入口 | 产物 |
|------|----------------------|------|------|
| **single**（默认） | `single` | `--skill-path PATH` | `evolution_workspace/taskid_*/best_skill/SkillName/` |
| **agent** | `agent` | `--skill-paths PATH1,PATH2` | `evolution_workspace/taskid_*/best_skill/Skill1/, Skill2/` |

**Agent 模式**：所有 Skill 一起跑端到端评测，生成聚合分数，每个 Skill 独立优化。
