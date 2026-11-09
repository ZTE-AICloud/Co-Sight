---
name: skill_optimize
description: Skill 内容优化(LLM 多维评分闭环) + 结构重构(plan-mode 人机协同) 二合一入口 — 用 --mode {optimize|refactor} 切换。当 Skill 内容质量不达标时用 optimize；当 Skill 文件结构乱/超长/引用断裂时用 refactor。
argument-hint: "--mode {optimize|refactor} (--skill-path PATH | --agent-path DIR) [--expert-guidance TEXT] [--workspace DIR] [--rounds N] [--max-files N] [--protected-assets a,b,c] [--break-threshold N] [--per-skill-rounds N] [--no-revert] [--score-mode {llm_direct|subagent}]"
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


# `/skill_optimize` 统一入口

> **本文件合并了原 `/skill_optimize`（静态优化闭环）与 `/skill_refactor`（结构重构人机协同）**。
> 调用时必须显式传 `--mode {optimize|refactor}`，未传或非法值会立即报错退出。
> 详细迁移说明见 `docs/command-merge-2026-07.md`（待补）。

---

## 快速路由

| 场景 | mode | 触发关键词 |
|------|------|-----------|
| Skill 内容质量不达标（描述模糊、缺失败模式、缺检查点） | `--mode optimize` | 内容、评分、维度、优化质量 |
| Skill 文件结构乱、章节超长、引用断裂、文件超 500 行 | `--mode refactor` | 结构、引用、外置、拆分、合并 |
| 不确定 | 先 `/skill_optimize --mode optimize`（更自动化） | — |

---

## 前置 4 步（optimize + refactor 共享）

> 这 4 步在两个 mode 下行为一致，集中放在文件顶部维护，避免后续更新时漏改其中一份。

### Step 0.1 — 解析 CLI 参数

提取以下参数：

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--mode {optimize\|refactor}` | ✅ | — | **必填**，未传立即报错 |
| `--skill-path PATH` | ✅* | — | 单 Skill 模式：目标 SKILL.md 路径 |
| `--agent-path DIR` | ✅* | — | 多 Skill 模式：Agent 根目录（仅 `--mode optimize` 支持），与 `--skill-path` 互斥 |
| `--expert-guidance "TEXT"` | ❌ | 空 | 自然语言专家指引，注入子 Agent prompt 顶部 |
| `--workspace DIR` | ❌* | 自动推断 | **仅 `--mode refactor` 必填或显式传**；optimize 默认用 `evolution_workspace/` |
| `--rounds N` | ❌ | 3（optimize）/ 5（refactor） | 最大迭代轮数 |
| `--max-files N` | ❌ | 10 | 仅 `--mode optimize` 生效：一次优化最多改的文件数 |
| `--protected-assets "a,b,c"` | ❌ | 见下 | 仅 `--mode optimize` 生效：强制保护的附属资产清单 |
| `--break-threshold N` | ❌ | 2 | 仅 `--mode optimize` 生效：触顶 break 阈值 |
| `--per-skill-rounds N` | ❌ | 3 | 仅 `--mode optimize` 多 Skill 模式生效：每个 Skill 的最大轮次 |
| `--no-revert` | ❌ | false | 仅 `--mode optimize` 生效：关闭 snapshot 恢复自动回退 |
| `--score-mode {llm_direct\|subagent}` | ❌ | llm_direct | 仅 `--mode optimize` 生效：评分执行路径 |

### Step 0.2 — mode 校验

执行以下检查，任何一条不满足立即**文本报错**并退出，**不**进入后续流程（禁用 AskUserQuestion）：

1. `--mode` 必须在 `{optimize, refactor}` 中（区分大小写）
2. `--mode optimize` 时：`--skill-path` 或 `--agent-path` 至少传一个，二者互斥
3. `--mode optimize` 时：`--mode refactor` 专属参数（`--workspace` 之外）不接受
4. `--mode refactor` 时：必须传 `--skill-path`，**不接受** `--agent-path` / `--max-files` / `--protected-assets` / `--break-threshold` / `--per-skill-rounds` / `--no-revert` / `--score-mode`

### Step 0.3 — 路径校验

- 单 Skill 模式：SKILL.md 存在 + 含 frontmatter（`---` 开头）
- 多 Skill 模式（仅 `--mode optimize`）：`{agent_path}/skills/` 存在，扫描所有含 SKILL.md 的子目录

### Step 0.4 — 后台启动准备

- 拼出最终 orchestrator 命令（两个 mode 分别拼，见下方对应段）
- 用户 1 句最终确认 → 用 `run_in_background: true` 启动 orchestrator
- 启动后必须等 `task-notification`，**禁止** `timeout` 参数

---

## mode == optimize

### 核心模型

```
业务方 Skill 资产（SKILL.md + scripts + references）
        ↓
LLM judge 多维评分（不依赖外部 eval-cmd）
        ↓
md 文件 → SkillOptimizerAgent（直接 Edit）
代码文件 → CodeOptimizerAgent（强制加载"编码 skill"4 原则）
        ↓
应用 → 评分 → 若回退则从 before snapshot 文件系统恢复
        ↓
连续 2 轮 Δ < break-threshold → 触顶停止
```

**适用场景**：无业务方评测管道，但希望用 LLM 多维评分 + 反例黑名单 + 文件系统 snapshot 保护来自动化优化 Skill 资产。

**与 `/skill_evolve` 的关系**：并列命令，可串联（先 `/skill_optimize --mode optimize` 打底，再 `/skill_evolve` 跑评测拉满）。

### Step O.1 — 二次确认（3 题,纯文本编号提问）

> 按上方"🧾 交互方式"规则:Q1/Q2/Q3 以纯文本编号列出,让用户回复编号/文本,不使用 AskUserQuestion。

#### 模式 A：单 Skill 模式（传入 `--skill-path`）

**Q1 · 优化范围确认**（header: "优化范围"）
- SKILL.md + scripts + references 全放开（推荐，4 层保护兜底）
- 仅 SKILL.md（最保守，1 层保护足够）
- SKILL.md + references/*.md（折中，跳过代码）

**Q2 · 触顶策略**（header: "触顶策略"）
- Δ < 2 连续 2 轮即停（推荐，darwin HL-4）
- Δ < 5 连续 2 轮即停（宽松）
- 跑满 N 轮不停（仅当用户明确要求时）

**Q3 · 自然语言指引确认**（header: "专家指引"）
- 沿用 CLI 传入的 `--expert-guidance` 内容（推荐）
- 我要补充/修改（选 Other 填新文本）
- 不使用指引

#### 模式 B：多 Skill 模式（传入 `--agent-path`）

**Q1 · 优化 Skill 范围确认**（header: "Skill 范围"，multiSelect）

按互斥分组列出（共 4 组，分组互不重叠；选 Other 输入通配符）：
- **全部 N 个 Skill**（推荐，无遗漏）
- **接口设计族**：组件间流程设计 + 组件间接口设计 + 6 个接口子项（分析/检查/删除/通信配置/新增/修改）
- **SDD/工具族**：产物上传下载 + 初始化 + 结果校验 + SDD 任务生成文字记录 + SDD 任务时间记录
- **仅核心设计 Skill（不带子项）**：组件间流程设计 + 组件间接口设计

> **设计原则**：分组按"业务归属"切分，不按"大小/复杂度"切分，确保任意一组都不与其他组重叠，避免用户多选时漏算或重复算。

> **说明**：每个 Skill 独立优化、互不影响；产物在 `{workspace}/skill_{idx:02d}_{skill_name}/` 下；总耗时 = N × `--per-skill-rounds` 轮（默认 3）。

**Q2 · 自然语言指引确认**（header: "专家指引"）
- 沿用 CLI 传入的 `--expert-guidance` 内容（推荐）
- 我要补充/修改（选 Other 填新文本）
- 不使用指引

### Step O.2 — 拼 orchestrator 命令

```bash
python3 scripts/orchestrator.py \
  --mode static \
  --skill-path "<skill_path>" \
  --max-rounds <rounds> \
  --max-files <max_files> \
  --protected-assets "<comma_separated>" \
  --break-threshold <break_threshold> \
  --expert-guidance "<expert_guidance_or_empty>" \
  --score-mode "<score_mode:llm_direct|subagent>" \
  --non-interactive
```

### Step O.3 — 等 task-notification

- 用户 1 句确认 → `Bash run_in_background: true` 启动（**禁止** `timeout`）
- 等 `task-notification` 触发
- `TaskOutput` 轮询进度

### Step O.4 — 读产物

- 读 `{workspace}/score_history.html`（核心可视化产物）
- 读 `best_skill/best_skill_info.json` 获取最佳 Skill 来源（baseline / 候选）
- 必要时读 `score_history.md` 看分数趋势

### Step O.5 — 出最终报告

按以下结构向用户汇报：

```markdown
## Skill 优化完成报告

**模式**：optimize | **目标 Skill**：<path> | **总轮次**：N
**基线分**：X.XX | **最终分**：Y.YY | **Δ**：+Z.ZZ

### 分数趋势
[粘贴 score_history.html 关键节点]

### 关键改动章节（按 Δ 排序）
1. <H2 章节名>: <改动简述>
2. ...

### 残留风险
- <未触顶风险 / 反例黑名单命中数 / 评分不确定项>

### 后续建议
- 是否串联 `/skill_evolve` 做评测驱动拉满
- 是否需要人工复核 best_skill/ 副本
```

### optimize 模式硬约束

- **必走 3 题纯文本编号确认**（用户决策），不因命令行已传而跳过
- 必等用户 1 句最终确认后再启动
- 启动后必须用 `run_in_background: true` + 禁止 `timeout`
- **禁止全量重写 SKILL.md**：优化器只能修改需要改动的 H2 章节
- **默认非交互模式**（自动批准优化提案）
- 默认评分模式为 `llm_direct`；传 `--score-mode subagent` 时切换到 cc `tools.Agent` 真子 Agent 路径

### 多维评分 rubric（optimize 专用）

> **权威定义**：`framework_configs/static-eval-config.yaml` 的 `rubric` 段。下表为摘要。

| # | 维度 | 权重 | 评分要点 |
|---|------|------|---------|
| 1 | Frontmatter 完整度 | 1.0 | 必有 name+description；description 含"做什么 + 何时用 + 触发词"三要素 |
| 2 | 工作流可执行性 | 1.2 | 步骤无歧义、命令含 `--flag value`、流程闭环 |
| 3 | 失败模式覆盖 | 1.5 | ≥3 类失败 + 三段式（触发条件 / 一线修复 / 仍失败兜底） |
| 4 | 检查点设计 | 1.0 | 🔴 STOP/CHECKPOINT 视觉标记 |
| 5 | 可执行具体性 | 1.5 | 禁"建议/灵活/根据情况"软化措辞 |
| 6 | 章节一致性 | 1.0 | 跨章节引用闭合；术语全文一致 |
| 7 | 反例与黑名单 | 1.0 | SKILL 含"不要做什么"反例清单 |
| 8 | Skill/Agent 全局一致性 | 1.0 | Role 不越权、Tool 白名单、Safety 约束 |
| 9 | Anthropic Skill 规范合规 | 1.2 | SF-1 目录结构 / SF-3 行数 ≤500 / SF-5 命名 |

### 4 层安全网（optimize 全开放的代价）

1. **优化前 snapshot**：每轮首步备份工作副本到 `round_N_before_skill/`
2. **附属资产白名单**：从 frontmatter 读 + CLI 覆盖 + 默认值三层合并
3. **评分回退保护**：每轮结束对比基线，回退则从 before snapshot 还原
4. **触顶 break（HL-4）**：连续 2 轮 Δ < break-threshold → 自动停止

### 反例黑名单（optimize 专用）

1. 描述模糊：`"处理相关任务"` → 必须 `处理 X 类任务`
2. 触发词缺失：description 缺少动词（创建/分析/评审/优化）
3. 示例无 flag：所有命令必须 `--flag value` 而非裸命令
4. 步骤无检查点：连续步骤间无验证节点
5. 失败处理空泛：仅说"重试"而不说重试几次/什么条件下重试
6. 资源路径硬编码：绝对路径必须相对化
7. 章节冲突：A 章节说"先 X 再 Y"，B 章节说"先 Y 再 X"
8. LLM 自评幻觉：不能仅凭自评"应该 ≥80"，必须 snapshot 恢复实测验证

### 文件类型 dispatch（optimize 专用）

| 后缀 | Agent | 工具 |
|------|-------|------|
| `.md` | SkillOptimizerAgent | Edit 直接改 |
| `.py / .sh / .json / .yaml / .toml` | CodeOptimizerAgent | 强制加载"编码 skill"4 原则 |
| 其他 / 二进制 | — | 跳过（不优化） |

### 与 `/skill_evolve` 串联使用

```bash
# Step 1: 静态优化打底（5~10 分钟）
/skill_optimize --mode optimize --skill-path /path/to/SKILL.md \
  --expert-guidance "<业务约束>" \
  --rounds 3

# Step 2: 评测驱动拉满（30 分钟+,推荐简化入参）
/skill_evolve --skill-path /path/to/SKILL.md \
  --rounds 5 --candidates 3 --runs 3 \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'
```

---

## mode == refactor

> ⚠️ **本段必走 EnterPlanMode #1 + #2 两次**（与 optimize 模式的根本差异）。
> orchestrator 只做数据收集，CC 承担 plan / apply / verify 全流程。

### 核心原则

> **主要依靠 CC 的 plan 能力，而不是代码设计。**

orchestrator **只做数据收集**，不参与 plan / apply / verify。CC 主 Agent:
- 读 orchestrator 产出的 2 个文件
- 自己进 plan mode 合成 refactor 计划
- 用户批准后用 Edit 工具直接改文件
- 出最终报告

### Agent 行为约束

执行 `--mode refactor` 时，CC **必须按以下顺序**：

```
0. Step 0.1-0.4（参数解析 + 校验 + 后台启动）
1. 必走 3 题纯文本编号确认（见下方 R.1）
2. 等用户 1 句最终确认
3. Bash run_in_background 启动 orchestrator: --mode refactor --skill-path <X> --workspace <W> --non-interactive
4. 等 task-notification
5. Read {W}/refactor_diagnosis.md 与 {W}/skill_file_relations.json
6. 读 5 份重构/检查文档（在 docs/ 下）与 SKILL.md 全文
7. EnterPlanMode：基于以上输入，合成"具体可操作步骤"
8. ExitPlanMode 等用户批准
9. **在 after_skill/ 副本上**用 Read + Edit 工具逐步应用 plan
   - 所有 Read + Edit 操作目标：`{W}/after_skill/{SkillName}/...`
   - 源文件 `{X}`（live skill_root）**永不改**；before_skill/ 是 source 的快照（回滚源），after_skill/ 是修改副本
   - 每步可独立 revert 到 before_skill/（用 `cp -r before_skill/{SkillName}/* after_skill/{SkillName}/`）
9b. (after_skill/ 副本由 orchestrator 在 step 1 后自动从 source 拷贝，**无需 CC 手工建**)
10. 出最终报告（改动前 → 改动后 体积/Token 节省等指标）
10a. **生成 diff HTML 报告**：
    - 调 `Bash python3 scripts/orchestrator.py --mode refactor-diff-report --skill-path <X> --workspace <W> --non-interactive`
    - 读 `{W}/refactor_diff_report.html`（gerrit 风格 before vs after）
    - 关键差异摘要嵌入最终报告
10b. **🔍 独立自我检查**：
    - 调 `Bash python3 scripts/orchestrator.py --mode refactor-self-check --skill-path <X> --workspace <W> --non-interactive`
    - orchestrator 会自动跑 7 项 SK-S 静态验证 + 4 个 R-N 行为层场景
    - 写 `{W}/自我检查报告.md` + `{W}/自我检查结果.json`
11. EnterPlanMode#2 展示报告，等用户确认完成
```

**⛔ 严禁**：
- 在阶段 0/1 中间调 EnterPlanMode（此时还没有 refactor_diagnosis.md 可读）
- 写代码做 apply / verify（用 Read + Edit 就够）
- 写代码做 auto-fix（让 CC 自己用 Edit 即可）
- 调用 SK-S 检查脚本（CC 读文件即可判断）

### Step R.1 — 二次确认（3 题,纯文本编号提问）

> 按上方"🧾 交互方式"规则:Q1/Q2/Q3 以纯文本编号列出,让用户回复编号/文本,不使用 AskUserQuestion。

**Q1 · 重构力度**（header: "重构力度"）
- 轻量：仅 description 优化 + 引用闭合性验证
- 中等（推荐）：覆盖 4 大主题（description / 内联外置 / 状态机 / 引用闭合）
- 激进：除上述外，推荐 1-2 个新文件/新结构（如 work/task-state.json）

**Q2 · 风险偏好**（header: "风险偏好"）
- 保守：每步前 Read + 等用户口头确认
- 平衡（推荐）：plan 阶段等用户批准，执行阶段连续完成
- 激进：plan 批准后一次性完成全部步骤

**Q3 · 专家指引**（header: "专家指引"）
- 沿用 CLI `--expert-guidance`（推荐，如有）
- 不使用指引（默认）

### Step R.2 — 拼 orchestrator 命令

```bash
python3 scripts/orchestrator.py \
  --mode refactor \
  --skill-path "<skill_path>" \
  --workspace "<workspace>" \
  --expert-guidance "<expert_guidance_or_empty>" \
  --non-interactive
```

### Step R.3 — 等 task-notification + 读诊断

- `Bash run_in_background: true` 启动（**禁止** `timeout`）
- 等 `task-notification` 触发
- Read `{W}/skill_file_relations.json`（关系树）
- Read `{W}/refactor_diagnosis.md`（LLM 诊断：findings + cluster_observations）
- Read 5 份重构/检查文档（在 `docs/` 下）：
  - `重构原则-skill分层与目录结构.md`
  - `重构原则-skill重构模式库.md`
  - `重构原则-skill性能与token优化.md`
  - `重构原则-skill极致代码化.md`
  - `重构后检查-Skill完整性验证.md`
  - `重构后检查-等效性与回归测试.md`
- Read SKILL.md 全文

### Step R.4 — EnterPlanMode#1 合成 plan（对标 d7bcf0da 风格）

CC 写 EnterPlanMode#1 plan 时，**必须按"d7bcf0da 风格 + 4 字段格式"** 写，否则 plan 会被用户打回。

**现状段**：
- 目标 Skill 概况（路径 / SKILL.md 体积 / 章节数 / references/scripts/templates 文件数）
- 基础数据（关系树：files count / edges count / orphans / long_unoptimized）
- findings 分类表（每条 FD-XXX 编号 / 主题 / 严重度）
- before_skill/ 快照路径（回滚源）
- 与 d7bcf0da 风格对齐说明

**每步 4 字段**：

```markdown
### Step N：<一句话操作标题>
**覆盖**：FD-XXX / FD-XXX

| 字段 | 内容 |
|------|------|
| **操作** | 用 Read + Edit 改什么文件（具体行/段） |
| **不改** | 明确列出本步骤不动哪些字段/章节 |
| **before** | 原文片段（便于验收对比） |
| **after** | 改后片段（便于验收对比） |
| **验收** | 具体命令 + 期望结果（数字级，如 `wc -l` / `grep -c` / `bash -n`） |
| **回归** | 跑什么命令确保没破坏现有结构 |
```

**8 步 plan 模板**（对标 d7bcf0da 7 大类）：

| 步骤 | 主题 | 覆盖 findings 类别 |
|------|------|---------------------|
| **Step 0** | 实战案例参考 | Read `docs/重构案例-d7bcf0da-Skill组件间流程设计.md` §2 7 大类对照 |
| Step 1 | frontmatter description 4 要素公式 | FD-001 |
| **Step 1.5** | 脚本 source 链一致性预检 | FD-012 |
| Step 2 | 内联内容合并到 references/ | FD-002/003 |
| Step 3 | 精简内联代码 | FD-005/006/007/008/009/010/011 |
| Step 4 | 引用闭合性验证（越级路径修正） | FD-011 |
| **Step 4.5** | 关键路径/中间层保留验证 | FD-013 |
| Step 5 | 脚本化确定性操作 | FD-005/006/009 |
| Step 6 | 新增文件（execution-rules.md / lib.sh / router.md / 等） | FD-004/005/006/007/008/009/010 |
| Step 7 | 回归 + 出最终报告 | 全部 FD |

> **plan 草稿自动生成**：orchestrator 在 `_run_refactor_mode` 末尾会自动生成 `refactor_plan_draft.md`，CC 在 plan mode 仍需根据实际微调每个 Step 的 before/after 段。

### Step R.5 — 在 after_skill/ 副本上应用 plan

- 所有 Edit 操作目标：`{W}/after_skill/{SkillName}/...`
- 源文件 `{X}`（live skill_root）**永不改**
- 每步可独立 revert 到 before_skill/

### Step R.6 — 出最终报告 + diff HTML + 自我检查

```bash
# 生成 diff HTML 报告
python3 scripts/orchestrator.py --mode refactor-diff-report \
  --skill-path <X> --workspace <W> --non-interactive

# 跑独立自我检查
python3 scripts/orchestrator.py --mode refactor-self-check \
  --skill-path <X> --workspace <W> --non-interactive
```

最终报告必须包含（对标 d7bcf0da 完成报告 5 节）：
- **一、收益汇总**：SKILL.md 行数/字节数 before → after
- **二、8 步执行回顾表**：Step / 操作 / 验收结果
- **三、关键设计资产保留**：上下文预算感知 / Procedure 完成校验等
- **四、新增/删除文件清单**：列出 work/
- **五、与原 Plan 的差异**：实事求是（目标 vs 实际）

### Step R.7 — EnterPlanMode#2 展示报告，等用户确认完成

### refactor 模式硬约束

- 必走 3 题二次确认
- 必等用户 1 句最终确认
- 阶段 R.4 必调 EnterPlanMode/ExitPlanMode
- 阶段 R.7 必调 EnterPlanMode#2
- 必后台启动 orchestrator + 禁止 timeout
- **禁止全量重写 SKILL.md** — 只做单点 Edit
- **禁止改源文件（live skill_root `{X}`）** — 所有 Edit 必须在 `{W}/after_skill/{SkillName}/` 副本上进行
- 必用 before_skill/ 快照作为 revert 源

### orchestrator 产出（写到 `{workspace}/`）

| 文件 | 内容 |
|------|------|
| `skill_file_relations.json` | 关系树：files[] / edges[] / orphans[] / clusters[] / stats |
| `refactor_diagnosis.md` | LLM 诊断：findings[]（FD-XXX）+ cluster_observations[] |
| `before_skill/{SkillName}/` | source Skill 初始快照（**回滚源**，CC 不修改） |
| `after_skill/{SkillName}/` | source Skill 修改副本（CC 的所有 Read + Edit 都在此副本） |
| `refactor_diff_report.html` | gerrit 风格 before vs after diff 报告 |
| `refactor_plan_draft.md` | orchestrator 自动生成的 plan 草稿（CC 微调基础） |

### 实战教训（refactor 模式必读）

> 来源：2026-07 组件间流程设计 Skill 重构实战踩坑。

#### 7 步 plan 强制项

| 步骤 | 主题 | 必做事项 |
|------|------|---------|
| **Step 1.5** | 脚本 source 链一致性预检 | 在合并/删除 scripts/ 中的源文件前，先 `grep -rn "source\|if.* -f" scripts/`，列出所有引用点 |
| **Step 4.5** | 关键路径/中间层保留验证 | 在把详细流程图外移到 references/router.md 前，先对比 R 链路，确保 router.md 含完整中间层 |

#### 阶段 9 之前的强制校验

CC 在 before_skill/ → after_skill/ 之前，必须先跑：

```bash
# SK-S12 脚本 source 链一致性
grep -rn "^source\|if.* -f.*\.sh" after_skill/ 组件间流程设计/scripts/ \
  | awk '{print $NF}' | sort -u | while read f; do
    [ -f "after_skill/组件间流程设计/scripts/$f" ] || echo "MISSING: $f"
done

# SK-S13 router.md 中间层保留
grep -E "MCC|SMC|RKC|FCS|UPA" after_skill/组件间流程设计/references/router.md \
  || echo "WARNING: router.md 可能缺少中间层"
```

**不通过 → 阻断，不进入 Step R.5 的 Edit 应用**。

---

## 关联文件

- 本文件：合并后统一入口契约
- `scripts/orchestrator.py` `_run_static_mode()`：optimize 模式数据收集 + 评分闭环
- `scripts/orchestrator.py` `_run_refactor_mode()`：refactor 模式数据收集 + 副本准备
- `scripts/optimizers/static_optimizer.py`：optimize 模式主循环 + 4 层安全网
- `scripts/optimizers/static_refactor.py`：refactor 模式 LLM prompt + 写 refactor_diagnosis.md
- `scripts/optimizers/static_relations.py`：复用 build_relation_tree
- `scripts/optimizers/static_llm.py`：复用 call_llm_json

---

## 约束总览

| 项 | optimize | refactor |
|----|----------|----------|
| EnterPlanMode | ❌ 不触发 | ✅ 必触发 2 次（R.4 + R.7） |
| 交互方式 | 3 题纯文本编号（单 Skill）/ 2 题（多 Skill） | 3 题纯文本编号 |
| 评分机制 | LLM 9 维 rubric | ❌ 无评分 |
| 产物目录 | `evolution_workspace/taskid_*/` | `{workspace}/before_skill/ + after_skill/ + *.md/json` |
| 回退机制 | snapshot 自动恢复 | 手动 `cp -r before_skill/{Name}/* after_skill/{Name}/*` |
| 退出条件 | 分数达标 / 触顶 / 达 max-rounds | 用户在 EnterPlanMode#2 确认完成 |
| 默认评分模式 | `llm_direct`（可切 `subagent`） | N/A |
| 子 Agent | skill-optimizer-agent + code-optimizer-agent | skill-refactor-agent（仅诊断） |