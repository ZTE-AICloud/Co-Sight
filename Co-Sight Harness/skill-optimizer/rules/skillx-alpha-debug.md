# skillx-alpha-agents 调试规范

**目的**：调试 skillx-alpha-agents 通用 Skill 优化编排器

**触发**：用户 `@skillx-alpha-debug` 时，依据本规范分析和修改

**定位**：skillx-alpha-agents 是**通用 Skill 优化编排器**，不绑定任何具体业务（SDD 评测、组件变更分析等只是使用方）。调试时只关注编排器本身的正确性，业务细节由业务方通过参数和适配器配置注入。

---

## 调试机制：持续测试-修改循环

> **核心要求**：通过"跑一遍 → 看产物 → 定位 bug → 改代码 → 再跑一遍"的闭环持续调试，直到编排器没有 bug 且产物结构符合预期为止。

### 循环规则
1. **每次改动必须验证**：改完代码后立即跑一次完整的 orchestrator，检查产物是否符合预期
2. **不达预期不结束**：只要还存在 bug、产物结构不对、或计算有误，就必须继续下一轮修复
3. **先跑小规模验证**：先用 `--rounds 1 --runs 1 --candidates 1` 快速跑通一两个 CASE 确认问题，修通后再跑多轮完整流程
4. **每轮只修一个根因**：不要一次改多个地方导致问题叠加、难以定位
5. **回归已有能力**：修完一个 bug 后，确认之前已跑通的功能没有被破坏

### 终止条件（满足任一即可停止）
- **无 bug**：orchestrator 完整跑完所有轮次，无报错、无异常退出
- **产物符合预期**：产物目录结构完整、config.json 状态正确、分数计算准确、报告格式清晰
- **用户确认停止**：用户主动要求暂停

### 调试检查顺序
```
1. 启动是否正常（无 ImportError / FileNotFoundError）
2. 基线评测是否跑通（baseline avg > 0）
3. 候选生成是否正确（数量 = --candidates × --runs）
4. 分数提取是否准确（score.json 与 phase3-eval/JSON 一致）
5. before/after 快照是否存在且有 diff
6. config.json 历史是否完整
7. 报告格式是否规范
8. 多轮迭代是否连续（每轮用上轮的优化结果）
```

---

## 核心原则：编排器与调试任务解耦

### 什么是编排器的职责（调试时关注）
- 循环控制：基线 → 候选 → 优化 → 迭代，直到达标或达上限
- 状态持久化：config.json、progress_state.json（含 current + rounds 双 section）、快照、历史
- 评测编排：调用业务方评测管道，提取结构化分数
- 优化网关：多级 Fallback 生成并应用 Skill 补丁
- 产物管理：目录结构、报告生成、分数聚合

### 什么是业务方的职责（事先配置好，调试时不修改）
- 评测管道脚本：`--pipeline-base-dir` 指向的业务方评测流程
- 评测适配器：`framework_configs/*.yaml` + `config/user-config.yaml` 中定义的管道步骤、分数提取规则
- 测试用例数据：金标准测试集、预期产出
- 业务 schema：gap 字段的具体含义、评测 JSON 的字段结构
- Skill 内容：SKILL.md 的具体章节、术语、指导

### 调试时的工作方式
1. **把业务配置当黑盒**：只验证编排器是否正确调用了管道、是否正确读取了分数、是否正确保存了产物
2. **不修改业务内容**：评测框架有 bug → 让业务方修；Skill 内容不合理 → 优化器自动生成补丁，不手动改
3. **用通用术语沟通**：用 "CASE" 指代测试用例、用 "pipeline" 指代评测流程、用 "activity" 指代评测活动，不用业务特定名称

---

## 核心约束

### 1. 通用性（最重要）
- 优化方案必须可泛化到其他 Skill
- 禁止硬编码任何业务相关逻辑
- 避免过拟合：评测基于案例，但不依赖案例具体内容
- **设计优先使用环境变量**：路径、配置等优先通过环境变量读取，提升工具可配置性

### 2. orchestrator 执行规范
- **执行目录**：`/media/vdc/skillx-alpha/skillx-alpha-agents`（根目录）
- **正确路径**：`scripts/orchestrator.py`，不是 `orchestrator.py`
- **workspace 参数**：通过 `SKILLX_WORKSPACE` 环境变量或 `--workspace` 注入，不硬编码
- **优先使用环境变量**：硬编码路径改为读取用户预先配置的环境变量，提升工具可靠性（如 `SKILLX_ROOT`、`SKILLX_WORKSPACE` 等）

### 3. 调试检查点
| 检查项 | 判定标准 |
|--------|----------|
| 启动正常 | 无 "No such file" 错误 |
| 方案通用 | 不含业务硬编码 |
| 评分趋势 | 逐步提升 |
| 报告质量 | 量化指标清晰 |
| 候选稳定性 | σ < 均值×50% 或 CV < 100% |
| 轮次控制 | 实际轮次 ≤ max_rounds |
| 策略有效性 | 至少有 1 个策略 > 0 |
| 基线可运行 | baseline avg > 0 |

### 4. 评测流程（通过参数注入，不硬编码）
- 评测配置：通过 `--pipeline-base-dir` 和 `--pipeline-activities` 注入
- 评测命令本体：通过 `--pipeline-eval-cmd`（slash command 自动 wrap）或 `--pipeline-eval-sh`（纯 shell 不 wrap，二选一）注入
- 目标 Skill：通过 `--skill-path` 注入
- 迭代轮次：通过 `--max-rounds` 注入
- 目标分数：硬编码为 100（`DEFAULT_TARGET_SCORE`），不可配置

> **简化入参等价关系**（调试时使用任一种形式都可）：
> - 简化形式（推荐）：`--pipeline-base-dir X --pipeline-eval-cmd "CMD"`
> - 纯 shell：`--pipeline-base-dir X --pipeline-eval-sh "CMD"`（跳过 slash-command 检测/wrap/extract）
> - 旧式兼容：`--pipeline-eval-cmd "cd X && CMD"`
> - slash command：`--pipeline-base-dir X --pipeline-eval-cmd "/<cmd> --arg ..."`（orchestrator 自动 wrap 为 `cosight -p`）
>
> 语义一致：cwd 来自 base_dir（旧式从 `cd X` 提取），命令本体来自 eval-cmd 或 eval-sh。

---

## 调试指南

### 5. 单 Skill 模式 vs 多 Skill（Agent）模式对比

**核心差异**：调试时首先要确认当前是哪种模式，不同模式的产物路径、循环逻辑、验证方法都不同。

#### 5.0 模式判定
| 特征 | 单 Skill 模式 | 多 Skill（Agent）模式 |
|------|--------------|----------------------|
| CLI 标志 | `--skill-path`（无 `--optimization-mode`） | `--optimization-mode agent --skill-paths` |
| 进入函数 | `run_loop()` | `run_agent_loop()` |
| Skill 副本目录 | `workspace/skill/` | `workspace/skills/{name}/`（每个 Skill 独立子目录） |
| config 文件名 | `config.json`（StateEngine 内部维护） | `config.json`（Agent 级，顶层） |
| 分数来源 | 单 Skill 的 pipeline 分数 | 所有 Skill 一起跑一次端到端，mean 聚合 |
| 候选循环 | 深度优先：先子优化再评测 | 广度优先：先生成多个候选，每个独立评测，选最优优化 |
| 优化粒度 | 只优化一个 Skill | 对每个 Skill 分别生成提案、分别应用 |
| 最终报告 | 单轮 report.md + score_history.md | 额外生成 `审查报告.md`（Agent 级联合审查） |
| history 结构 | `[{round, score, gaps, ...}]` | `[{round, score, gaps, case_scores: {CASE-xxx: x, CASE-yyy: y}, ...}]` |
| 基线目录 | `baseline/run_N/` | 同左，但 `skills/` 下包含所有 Skill 快照 |

#### 5.1 目录结构对比

**单 Skill 模式**：
```
{workspace}/{taskid}/
├── config.json
├── progress_state.json
├── skill/                          ← 单个 Skill
│   ├── SKILL.md
│   └── references/
├── baseline/                       ← 基线产物
│   └── run_{M}/
│       ├── skill/SKILL.md
│       ├── data/
│       └── score.json
├── round_{N}/                      ← 轮次产物
│   ├── before/SKILL.md
│   ├── after/SKILL.md
│   ├── score.json
│   ├── report.md
│   └── proposal.md
└── score_history.md
```

**多 Skill（Agent）模式**：
```
{workspace}/{taskid}/
├── config.json                     ← Agent 级 config（含 skill_names、skill_registry）
├── progress_state.json
├── skills/                         ← 多个 Skill，每个独立子目录
│   ├── SkillA/
│   │   ├── SKILL.md
│   │   └── references/
│   ├── SkillB/
│   │   ├── SKILL.md
│   │   └── references/
│   └── SkillC/
│       └── SKILL.md
├── baseline/                       ← 基线产物（直接位于 workspace 根）
│   └── run_{M}/
│       ├── skills/                 ← 基线快照包含所有 Skill
│       │   ├── SkillA/
│       │   ├── SkillB/
│       │   └── SkillC/
│       ├── data/
│       └── score.json              ← 聚合分数（所有 Skill 一起跑一次）
├── round_{N}/                      ← 轮次产物（直接位于 workspace 根）
│   ├── skills/                     ← 本轮优化后的 Skill 快照
│   │   ├── SkillA/
│   │   ├── SkillB/
│   │   ├── SkillC/
│   ├── before/skills/              ← 优化前快照（所有 Skill）
│   ├── after/skills/               ← 优化后快照（所有 Skill）
│   ├── candidate_{K}/run_{M}/      ← 各候选独立评测
│   │   ├── skills/
│   │   ├── data/
│   │   └── score.json              ← 该候选的聚合分数
│   ├── score.json                  ← 最优候选的聚合分数
│   ├── report.md                   ← 本轮评测报告
│   └── proposal_{SkillA}.md        ← 各 Skill 独立提案
├── score_history.md                ← 含各 CASE 独立分数 + 聚合分数
└── 审查报告.md                     ← Agent 级联合审查报告
```

#### 5.2 迭代循环逻辑对比

| 阶段 | 单 Skill 模式 | 多 Skill（Agent）模式 |
|------|--------------|----------------------|
| **基线** | 单 Skill 跑 baseline_runs 次 → 平均分 | 所有 Skill 一起跑一次 → 聚合分数（mean） |
| **候选生成** | 深度优化：直接优化当前 Skill → 评测 | 生成 N 个候选 → 每个候选所有 Skill 一起跑 → 各候选取平均 |
| **候选选择** | 无候选选择（深度优先） | 选平均分最高的候选 → 作为本轮优化依据 |
| **优化** | 优化一个 Skill | 对每个 Skill 分别生成提案、分别优化（但基于端到端 gaps） |
| **分数记录** | `history[{round, score}]` | `history[{round, score, case_scores: {CASE-xxx: x, CASE-yyy: y}}]` |
| **终止** | `score >= target` → 停 | `aggregate_score >= target` → 停 |

#### 5.3 调试时模式专属检查点

**单 Skill 模式专属**：
- `workspace/skill/SKILL.md` 是否存在且被正确更新
- `round_N/before/SKILL.md` 和 `round_N/after/SKILL.md` 是否有 diff
- 单轮 `score.json` 的分数与 `phase3-eval/` 下的 JSON 一致
- `score_history.md` 每行对应一轮

**多 Skill 模式专属**：
- `workspace/skills/` 下子目录数量 = `--skill-paths` 的数量
- `config.json` 中 `skill_names` 数组与 `skills/` 子目录一致
- `round_N/candidate_K/run_M/` 数量 = `--candidates` × `--runs`
- 聚合分数 = 所有 CASE 的平均分（不是各 Skill 分数的平均）
- `case_scores` 字典中有每个 CASE 的独立分数（来自同一端到端执行）
- `审查报告.md` 存在且包含所有 Skill 的分数表格
- 各 Skill 的提案文件独立（`proposal_{SkillName}.md`）

### 6. 迭代验证

**验证目标**：确保 orchestrator 的多轮迭代循环正确执行，每一轮的输入、处理、输出都符合预期。

#### 6.1 迭代流程完整性
- **基线评测**：必须执行且结果正确记录在 `config.json` 和 `baseline/run_N/`
- **候选评测**：`--candidates N` 指定几个候选就执行几个，不能少
- **多 Run 平均**：`--runs N` 指定每个候选跑几次就几次，取平均值作为候选分数
- **优化执行**：未达标时进入优化，优化后的 Skill 必须用于下一轮评测
- **终止条件**：达标即停（`score >= target_score`）或达到 `max_rounds` 后停止

#### 6.2 轮次状态一致性
- `config.json` 中的 `history` 数组长度 = 实际执行轮次数
- `current_round`、`current_score` 与实际最后一轮一致
- `best_score` 和 `best_round` 记录的是历史最高值，非最近一轮

#### 6.3 技能更新传播
- 优化后写入 `skill/SKILL.md` 或 `skills/{name}/SKILL.md`（workspace 副本）
- 下一轮评测的 `eval_args.skill_path` 必须指向更新后的副本
- before/after 快照必须分别存在 `round_N/before/` 和 `round_N/after/`
- 多 Skill 模式：所有 Skill 快照都要更新，不能遗漏

### 7. 文件夹结构与产物验证

**验证目标**：目录结构清晰、产物完整、无遗漏或多余文件。

#### 7.1 标准目录结构
```
{workspace}/{taskid}/
├── config.json                 # 状态持久化，包含完整历史
├── progress_state.json         # 统一进度状态（current + rounds 双 section）
├── skill/ 或 skills/           # workspace 中的 Skill 副本（优化操作基于此）
│   └── SKILL.md
├── baseline/                   # 基线评测产物
│   └── run_{M}/
│       ├── skill/          # Skill 快照
│       ├── data/               # 沙箱 data/ 归档
│       └── report.md           # 基线报告
├── round_{N}/                  # 统一目录结构
│   ├── before/                 # 优化前 Skill 快照
    ├── round_{N}/              # 统一目录结构
    │   ├── before/             # 优化前 Skill 快照
    │   ├── after/              # 优化后 Skill 快照
    │   ├── report.md           # 评测报告
    │   ├── score.json          # 评分数据
    │   ├── proposal.md         # 优化提案（如有）
    │   ├── baseline/run{M}/    # 基线评测归档
    │   ├── candidate_{K}/run{M}/   # 候选评测归档
    │   │   ├── skill/          # 该候选的 Skill 快照
    │   │   ├── data/           # 沙箱 data/ 归档
    │   │   ├── score.json      # 该候选的分数
    │   │   └── report.md       # 该候选的报告
    │   └── data/               # 沙箱 data/ 归档
    └── score_history.md        # 分数历史（详细版：基线/候选/统计/CASE明细）
```

#### 7.2 产物完整性检查清单
| 产物 | 必须存在 | 验证方法 |
|------|----------|----------|
| `config.json` | ✅ | 包含 `agent_name`、`history`、`best_score` 等字段 |
| `progress_state.json` | ✅ | 包含 `current`（最近进度）+ `rounds`（每轮 9 phase 状态） |
| `score_history.md` | ✅ | 包含所有轮次的分数，使用表格格式 |
| `round_N/before/SKILL.md` | ✅ | 优化前快照，内容与上一轮 after 一致 |
| `round_N/after/SKILL.md` | ✅ | 优化后快照，与 before 有 diff |
| `round_N/score.json` | ✅ | 包含 `score`、`gaps`、`rating` 字段 |
| `round_N/report.md` | ✅ | 格式清晰，使用模板（见 9.1） |
| `round_N/proposal.md` | ✅ | 包含优化建议和审批状态 |
| `candidate_K/run_M/score.json` | ✅ | 每个候选的每个 run 都有分数 |
| `baseline/run_N/score.json` | ✅ | 基线分数 |

#### 7.3 禁止的产物模式
- `baseline/run_N/phase4-diagnosis/` 目录独立存在（诊断数据应在 `data/phase4-diagnosis/` 下）
- `round_N/` 根级别有散落的 `phase4-diagnosis/` 文件夹
- 重复的 `config.json` 文件
- 临时文件残留（如 `.tmp`、`~` 备份文件）

### 8. 数据计算验证

**验证目标**：所有分数、统计、聚合计算准确无误。

#### 8.1 分数计算
- **单 Run 分数**：从 `phase3-eval/CASE-*/results/*.json` 的 `scores[]` 数组直接读取
- **候选平均分数**：`avg = sum(run_scores) / len(run_scores)`，分母不为零
- **N/A 分数归零**：候选为空/分母为零的 N/A 场景记为 0 分，而非跳过
- **聚合分数**：管道模式固定使用 **mean 聚合**（所有 CASE 平均分）

#### 8.2 统计计算
- **标准差**：`σ = sqrt(sum((x - mean)^2) / n)`，包含零值 run（不过滤）
- **变异系数**：`CV = σ / mean * 100%`，当 mean=0 时 CV 记为 0
- **基线平均分**：所有 baseline runs 的平均，不是最后一次 run 的分数

#### 8.3 数据一致性
- `config.json` 中的 `history` 与 `score_history.md` 中的表格数据一致
- `score_history.md` 中的 CASE 明细分数与 `phase3-eval/` 下的 JSON 文件一致
- 候选的 `candidate_avg` 等于其各 run 分数的算术平均
- **多 Skill 模式**：聚合分数 = 所有 CASE 的平均分，不等于各 Skill 分数的平均

#### 8.4 Gap 数据验证
- **Phase4 L3 聚合**：`timeout_risk_pct > 30%` 才生成 gap，避免噪音
- **Gap 去重**：按 `(type, affected_section[:50])` 去重，不重复
- **Gap 字段完整**：每个 gap 必须包含 `type`、`severity`、`message`、`root_cause`、`affected_section`、`fix_suggestion`
- **L3 数据结构兼容**：同时支持顶层 `common_causes` 和 `cross_comparison.common_causes`

### 9. 报告规范

**验证目标**：报告结构清晰、格式统一、使用预制模板、人类可读。

#### 9.1 报告模板要求
所有报告使用**预制的 Markdown 模板**，确保格式统一：

```markdown
# {报告标题}

## 总体结果

| 指标 | 值 |
|------|-----|
| 目标分数 | {target_score} |
| 最佳分数 | {best_score} |
| 达标状态 | ✅ 已达标 / ❌ 未达标 |

## 分数历史

| 轮次 | 分数 | 状态 | 说明 |
|------|------|------|------|
| 基线 | {score} | {status} | {note} |
| Round 1 | {score} | {status} | {note} |
| ... | ... | ... | ... |

## 各轮详细分析

### Round {N}

**分数**：{score}/100 [{rating}]
**缺口**：{gap_count} 个

**关键缺口**：
| 类型 | 严重性 | 描述 | 修复建议 |
|------|--------|------|----------|
| {type} | {severity} | {message} | {suggestion} |

**优化提案**：
{proposal_summary 或 "无提案（分数已达标）"}
```

**多 Skill 模式报告额外要求**：
- 包含各 Skill 独立分数表格
- 包含聚合分数与聚合方式说明
- 包含各 Skill 独立优化提案汇总

#### 9.2 报告质量要求
- **可读性**：使用表格、列表、代码块等 Markdown 元素，避免大段纯文本
- **量化指标**：分数、百分比、数量等使用数字展示，不用模糊描述
- **层次结构**：使用 H2/H3/H4 标题建立清晰的层次，不超过 4 级
- **时间戳**：每份报告包含生成时间（`YYYY-MM-DD HH:MM:SS`）
- **链接**：报告中的路径使用相对路径或完整 Markdown 链接
- **Agent 模式**：使用 `ReportBuilder` 类生成报告，保持格式统一
- **禁止**：报告中不能出现未格式化的 JSON 或 Python 字典字符串

#### 9.3 报告文件命名
| 报告 | 路径 | 用途 |
|------|------|------|
| 单轮报告 | `round_{N}/report.md` | 该轮评测详情 |
| 分数历史 | `score_history.md` | 所有轮次汇总 |
| 审查报告 | `审查报告.md` | Agent 级联合审查（多 Skill 模式） |
| 诊断报告 | `诊断报告.md` | 诊断模式输出 |

### 10. 调试时优先查看的文件（通用路径）
```
{workspace}/config.json                                     # 状态与历史
{workspace}/round_{N}/score.json             # 结构化评测数据
{workspace}/round_{N}/report.md              # 人类可读报告
{workspace}/score_history.md                 # 分数历史汇总
{workspace}/审查报告.md                                     # 最终报告
```

**注**：路径中的目录名（如 ``、`审查报告`）应通过配置或环境变量注入，不硬编码。

### 11. 禁止事项
- ❌ 在优化器中写死业务判断逻辑
- ❌ 针对案例内容定制化修改
- ❌ 硬编码 workspace 路径（使用环境变量或参数）
- ❌ 候选零分时跳过记录（必须记录以便回溯）
- ❌ 标准差计算时过滤零值 run（零值是有效数据）
- ❌ 使用全量重写 SKILL.md（只能修改需要改动的 H2 章节）
- ❌ 报告中包含未格式化的 JSON 或 Python 字典字符串
- ❌ 产物目录中散落未归类的文件（所有文件必须在规定的子目录下）
- ❌ 调试时手动修改业务方的评测脚本或测试数据（只修编排器本身的 bug）

---

## 优秀 Agent 设计范式

> 从成熟 Agent 实践中提炼的通用特质。回答"一个好的 Agent 应该长什么样"。

### 范式一：意图先于行动（Intent Before Action）

好的 Agent 不急着动手。收到请求后先理解"你要我做什么、为什么做、做到什么程度"，确认方向对了再执行。方向错了，做得越快越浪费。

### 范式二：编排者与执行者分离（Orchestrator ≠ Worker）

好的 Agent 知道自己什么时候该亲自动手，什么时候该派别人去做。编排决策和执行能力是两个不同的东西，混在一起就会既当不好裁判，也踢不好球。

### 范式三：按需加载，不贪多（Load on Demand）

好的 Agent 不把所有知识一次性塞进上下文。核心规则随身带，专业内容用到再查。知道"不知道什么"比"知道一切"更有价值。

### 范式四：增量修改，不推倒重来（Delta, Not Rewrite）

好的 Agent 修改东西时像外科手术——精确切除病灶，不伤及健康组织。全量重写看似彻底，实则会丢失历史积累的微妙判断。

### 范式五：审查不可跳过（Gate Every Step）

好的 Agent 不信任自己的一次性输出。每个关键节点设一个独立的检查点，让"另一个自己"来验证。自审自批是最弱的质量保障。

### 范式六：知道何时回退（Know When to Roll Back）

好的 Agent 不怕走错，但绝不沿着错误的方向继续走。发现结果不如之前，停下来，退回去，换个方向再试。退化是信号，不是终点。

### 范式七：多路探索，择优而行（Explore, Then Exploit）

好的 Agent 面对不确定性问题时不押注单一路径。同时试几种方法，用结果说话，选最好的那条路继续走。

### 范式八：凡事可追溯（Everything Traceable）

好的 Agent 做的每个决定、改的每处内容，都能回溯到"为什么"。出了问题不是从头猜，而是顺着痕迹定位。

### 范式九：沙箱优先（Sandbox First）

好的 Agent 不直接在生产环境上做实验。先隔离、再操作、验证后合并。破坏性操作必须在不会造成真实损害的地方执行。

### 范式十：方案透明，让用户知情（Transparent Plans）

好的 Agent 不闷头干活。执行前告诉用户"我打算怎么做"，执行中告诉用户"我现在在哪"，执行完告诉用户"我做了什么、结果如何"。

### 范式十一：边界清晰，不越权（Stay in Lane）

好的 Agent 知道自己的职责边界在哪里。不该做的事不做，做不了的事不承诺，不确定的事不假装确定。

### 范式十二：从失败中学习（Learn from Failure）

好的 Agent 不会重复踩同一个坑。每次失败都记录"什么错了、为什么错、下次怎么避免"，让错误变成经验而不是成本。

### 范式十三：盲评原则（Blind Evaluation）

好的 Agent 在做评估时不"偷看"设计意图。评估者只根据被测对象的实际产出打分，不根据"它应该怎么做"来评判。一旦评估者知道了设计意图，就会无意识地偏向给高分，或者替被测对象补做它该做的事。盲评是客观性的前提。

### 范式十四：长程任务有界循环（Bounded Iteration）

好的 Agent 做长程任务时不会无限循环。它设好明确的轮次上限、超时时间和回退策略，每一轮都产出可检查的中间结果。超限时不是崩溃，而是优雅地降级——报告已完成的、标记未完成的、让使用者决定下一步。长程任务的可靠性不体现在"一定能做完"，而体现在"做不完时也能安全收场"。

### 范式十五：子代理上下文隔离（Context Isolation）

好的 Agent 派生出的每个子代理都运行在干净的上下文中，不带入父级的中间状态、临时假设和过程产物。隔离保证了两点：子代理不会被父级的偏见误导，父级不会被子级的失败污染。隔离是并发的基础，不是并发的代价。

### 范式十六：长程任务写状态文件（Progress State File）

好的 Agent 在执行长程任务时，每一步都把当前状态、阶段历史、重试次数写到一个结构化的状态文件里。这个文件是 Agent 和外部世界（用户、监控脚本、其他 Agent）沟通的唯一真相源。它解决了三个问题：

**断点续跑**：进程挂了再起来，读状态文件就知道上次停在哪，不用从头来。

**外部监控**：不需要侵入 Agent 内部，轮询一个 JSON/YAML 文件就能看到进度。

**审计追溯**：历史里记录了每一步的 verdict、timestamp、retry_count，出了问题能还原完整执行链。

**状态文件的最小结构**：

```yaml
current_phase: "正在执行的阶段名"
last_updated: "ISO 8601 时间戳"
phase_history:
  - phase: "阶段名"
    status: "running | done | failed"
    verdict: "PASS | FAIL"    # 失败时
    timestamp: "完成时间"
    retry_count: 0             # 原地重试次数
```

**写入规则**：正常推进时追加新条目到 phase_history；原地重试时更新最近一条的 verdict、timestamp 和 retry_count。永远不要只存在内存里。
