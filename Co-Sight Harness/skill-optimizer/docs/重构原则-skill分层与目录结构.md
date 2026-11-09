# 重构原则 ① — Skill 分层架构与目录结构

> **来源**:Anthropic 官方 Skill 规范 + AgentGenesis 实战经验(`skill-design-guide.md`)
> **用途**:skillx-alpha-agents 在重构业务方 Skill 时,**判断内容该放哪一层、放哪个目录**的判定手册
> **适用**:所有被 `/skill_evolve` / `/skill_optimize` 处理的目标 Skill

---

## 1. 核心定位

Skill 是 Agent 的**按需加载能力模块**,不是 Agent 本身,也不是独立进程。它是被调用、被注入到上下文的**指令集**。

### 1.1 为什么必须分层

一个 800 行的 SKILL.md 在每次匹配时全部注入 Agent 上下文,会导致:
- 上下文窗口被不必要信息占满
- Agent 在核心指令和参考细节之间失焦
- 后续步骤可用空间减少,输出质量衰减

**分层目标:在正确的时间,以最小信息量,提供最大决策支持。**

### 1.2 重构时的第一性判问

> 拿到一段内容,问三个问题,答案决定它该去哪:
> 1. Agent 没有它就无法执行核心任务 → **必须留在 SKILL.md (L2)**
> 2. 执行特定步骤才需要,不是每步都要 → **references/ (L3),SKILL.md 加引用**
> 3. 这是确定性操作(校验/比对/计算/转换) → **scripts/ (L3),SKILL.md 用 Bash 调用**

---

## 2. 三层加载架构 (L1 / L2 / L3)

| 层级 | 内容 | Token 预算 | 加载时机 | 作用 |
|------|------|-----------|---------|------|
| **L1** | `name` + `description`(frontmatter) | ~100 / Skill | Agent 启动时全部加载 | 判定"这个 Skill 能处理当前请求吗" |
| **L2** | `SKILL.md` body | 2000~5000 (上限 ≤ 300 行) | 仅匹配用户意图时加载 | 提供核心执行指令 + L3 引用 |
| **L3** | `references/` + `scripts/` + `templates/` | 可变,按需 | 仅 SKILL.md 显式引用时通过 Read/Bash 加载 | 详细参考、确定性脚本、复用模板 |

### 2.1 分层决策启发式

| 问题 | 决策 |
|------|------|
| 没它 Agent 就无法执行核心任务? | → L1 (description 暗示) 或 L2 (body 内联) |
| 仅特定步骤需要参考? | → L3 `references/` |
| 仅某些变体场景需要? | → L3 `references/` 条件引用 |
| 需要确定性结果(非 LLM 推理)? | → L3 `scripts/` 独立脚本 |

### 2.2 重构时的 Token 预算校验

- SKILL.md body **超过 300 行 → 必须拆分**到 L3
- description **超过 1024 字符 → 压缩**(只保留「做什么 + 何时触发 + 输入 + 输出」)
- references/ 单文件 **超过 100 行 → 拆细**(按主题/类别切分,避免一个文件成新的"巨无霸")

---

## 3. 标准目录结构

```
my-skill/
├── SKILL.md             # 必须 — L1 metadata + L2 body(≤ 300 行)
├── references/          # 可选 — L3 详细参考文档
│   ├── guide.md
│   ├── checklist.md
│   └── domain-knowledge.md
├── scripts/             # 可选 — 确定性可执行脚本
│   ├── validate.py
│   └── transform.py
└── templates/           # 可选 — 可复用的输入/输出模板
    ├── input-template.md
    └── output-template.md
```

### 3.1 何时需要 references/

- ✅ SKILL.md body 超过 300 行
- ✅ 包含领域知识(规范、术语表、规则清单)
- ✅ 包含不同场景的变体指令
- ✅ 包含长篇示例或案例

### 3.2 何时需要 scripts/

- ✅ 需要精确比对(文件内容、数据校验)
- ✅ 需要格式转换(JSON↔YAML、Markdown 提取)
- ✅ 需要数学计算或正则匹配
- ✅ 需要调用外部工具或 API

> **核心原则**:LLM 擅长推理、生成、判断;**脚本擅长精确、重复、可验证**。不要把 LLM 当脚本引擎使用。

### 3.3 何时需要 templates/

- ✅ 输入格式复杂,需要结构化模板
- ✅ 输出有固定格式要求(报告、契约)
- ✅ 用户每次需要从头构造输入

---

## 4. SKILL.md body 内容分类(强制)

### 4.1 保留在 body 的(L2)

- 核心执行流程(步骤顺序、关键决策点)
- 角色定义(Skill 执行时 Agent 扮演什么角色)
- I/O 契约(接收什么、产出什么、输出到哪里)
- **对 L3 资源的引用**(用 "详见 references/xxx.md" 形式),而非内容本身
- 工具调用指令(Read、Write、Bash、Agent)
- 关键约束和安全注意事项

### 4.2 提取到 references/ 的(L3)

- 超过 100 行的参考文档
- 领域知识(规范、标准、术语定义)
- 详细检查清单
- 长篇示例和案例
- 不同场景的变体指令
- 背景信息和上下文说明

### 4.3 提取到 scripts/ 的(L3)

- LLM 频繁出错的确定性操作
- 需要精确结果的比对和校验
- 格式转换(YAML↔JSON、Markdown 解析)
- 数学计算、统计、数据聚合
- 文件内容的结构化提取

### 4.4 提取判断流程图

```
这段内容是...
├── 核心执行指令?          → 保留在 SKILL.md (L2)
├── 领域参考/规范/长篇说明? → references/ (L3),加 "详见" 引用
├── 确定性操作?            → scripts/ (L3),Bash 调用
├── 可复用输入/输出格式?    → templates/ (L3),引用模板路径
└── 背景信息/上下文说明?    → references/ (L3) 或删除
```

---

## 5. Description 公式(强制)

### 5.1 标准结构

```
「做什么」+「何时触发」+「接收什么输入」+「产出什么输出」
```

### 5.2 反例 vs 正例

| 反例 | 问题 | 正例 |
|------|------|------|
| `帮助处理事情` | 太宽泛,无法判定何时触发 | (见下方) |
| `代码审查` | 缺输入/输出说明 | (见下方) |

**正例模板**:
```
代码安全审查:检查 Python/JS 代码中的安全漏洞(SQL 注入、XSS、硬编码密钥)。
当用户请求代码安全检查、安全审查或提交前审查时触发。
输入为文件路径或代码 diff,输出包含严重级别(CRITICAL/HIGH/MEDIUM/LOW)的 Markdown 审查报告。
```

### 5.3 重构时 description 校验

- [ ] 包含「做什么」(动词开头,如检查/提取/转换/生成)
- [ ] 包含「何时触发」(具体场景关键词,便于 Agent 匹配)
- [ ] 包含「输入」(文件路径/参数/上下文)
- [ ] 包含「输出」(报告/产物路径/格式)
- [ ] 总长 30~1024 字符

---

## 6. 命名约定

### 6.1 目录命名

- **kebab-case**:`python-pep8-checker` 而非 `PythonPep8Checker`
- 含领域关键词:`security-` / `python-` / `code-review-`
- 具象化:`python-pep8-checker` 优于 `code-checker`
- 不超过 4 个词

### 6.2 references/ 文件命名

- 描述性:`pep8-rules.md` 优于 `rules.md`
- 与 SKILL.md 中的引用一致(避免引用断链)

### 6.3 scripts/ 文件命名

- **动词开头**:`validate_syntax.py`、`extract_imports.py`
- 反映具体操作,而非泛化名称

---

## 7. 常见设计反模式(重构必查)

| 反模式 | 问题 | 重构方向 |
|--------|------|---------|
| **内联一切** | SKILL.md 800+ 行,参考/脚本/模板全在一个文件 | 按 §4 分类提取 |
| **LLM 做脚本的事** | 用 LLM 做 JSON 校验、代码风格检查 | 写成独立脚本,LLM 调用 |
| **过早拆分** | 3 步的简单 Skill 拆成 5 个 SubAgent | 单体先做到 ≤ 300 行 + 分层清晰,再考虑拆分 |
| **描述模糊** | "帮助处理代码" | 用 §5 公式重写 |
| **幽灵引用** | references/ 下文件未被 SKILL.md 引用 | 删除文件或加引用 |
| **引用断链** | SKILL.md 引用了不存在的 references/xxx.md | 创建文件或删除引用 |
| **脚本依赖上下文** | 脚本假设 LLM 会提供某些变量 | 脚本通过命令行参数/stdin 接收所有输入 |
| **模板不可用** | 模板含 "请填入..." 但无结构指导 | 模板可直接复制,含占位符 + 填写说明 |
| **脚本 source 链断裂** | 重构把 `config.sh` / `common.sh` 合并到 `lib.sh`,但仍有多处 `if [ -f config.sh ]; then source config.sh; fi` 残留 | 删除旧文件前,先 grep 所有脚本的 `source` 调用,统一改为 `source lib.sh` |
| **中间层被 Agent 跳过** | 详细流程图外移到 references/router.md 后,Agent 在自主决策时跳过中间组件(SMC、FCS) | router.md 中关键链路标"必须包含中间层",或在 SKILL.md 主体保留强制路径 |

---

## 8. 重构审查清单(逐项确认)

> skillx-alpha-agents 在重构阶段对每个目标 Skill 应用此清单。

- [ ] SKILL.md body **≤ 300 行**(超过即触发拆分)
- [ ] description 含「做什么 + 何时触发 + 输入 + 输出」,长度 30~1024 字符
- [ ] 超过 100 行的参考内容已提取到 references/
- [ ] 确定性操作(校验/比对/计算/转换)通过 scripts/ 脚本执行
- [ ] 每个 references/ 文件在 SKILL.md 中被明确引用
- [ ] 每个 scripts/ 脚本可独立运行(`python script.py input`)
- [ ] templates/ 中的模板可直接复制使用
- [ ] 目录名 kebab-case + 领域关键词
- [ ] 无 LLM 执行确定性操作的步骤
- [ ] 分层后的引用链完整(无断链、无幽灵引用)

---

## 9. 与 skillx-alpha-agents 工作的衔接

skillx-alpha-agents 在以下场景应用本原则:

| 场景 | 本原则的应用 |
|------|------------|
| `/skill_optimize` 静态评估 | 用 §8 清单打分,扣分项即重构方向 |
| `/skill_evolve` 优化提案生成 | 提案应包含「提取到 references/scripts」的具体 H2 章节级修改 |
| OptimizerGateway 生成 mod | 修改时优先 move-to-L3,而非重写 body |
| RefactorAgent(若有) | 把"body 超 300 行"作为自动触发拆分信号 |

> **关键原则**:**重构应优先 move 到 L3,而非全量重写 SKILL.md**(参见 COSIGHT.md §10.9)。一次重构只改需要改的 H2 章节,把"参考"和"确定性操作"从 body 剥离出去。

---

## 10. 实战教训:两类典型退化(2026-07 组件间流程设计 Skill 重构)

> **来源**:在重构「组件间流程设计 Skill」(从 243 行 → 108 行)过程中,6 需求测试暴露的两类 F1 退化根因。本节作为后续重构的「反面教材」,对应模式 A/B/C 的补充反例。

### 10.1 退化类型 A:脚本链接错位(config.sh → lib.sh)

**症状**:重构后 F1 = 0,Agent 跑某 Procedure 时第一步就拿到空输入。

**根因链路**:

| 步骤 | 改动 | 影响 |
| --- | --- | --- |
| 1 | `scripts/config.sh` 被删除(功能合并到 `scripts/lib.sh`) | — |
| 2 | `extract_design_input.sh` 第 53 行 `source config.sh` → 改为 `source lib.sh` | OK,显式修改 |
| 3 | **其他 5 个脚本**(validate_*.sh / fetch_*.sh / query_*.sh)中的 `if [ -f config.sh ]; then source lib.sh; else echo 错误; exit 1; fi` 块没改 | **BUG**:`config.sh` 已不存在,`if` 永远 false,直接 exit 1 |
| 4 | Agent 跑这些脚本时,以为「找不到 config.sh」是错误,直接跳过整步 | 子表格 0 条 |
| 5 | 后续 Procedure 1 步骤 1 的 `md_table_to_json.sh` 转出 `[]` | 输入丢失 |

**检查清单**(新增到 §8 清单后):

- [ ] **脚本 source 链一致性**:删除 `config.sh` 等被合并文件前,先 `grep -rn "source.*config.sh" scripts/` 列出所有引用点,逐个改为 `source lib.sh`
- [ ] **删旧文件前先验证**:`bash scripts/*.sh --help` 每个脚本能正常 source 且不报错
- [ ] **重构后跑一遍**:`for f in scripts/*.sh; do bash -n "$f" || echo "FAIL: $f"; done` 全部通过

### 10.2 退化类型 B:SKILL 瘦身让 Agent 跳过中间组件

**症状**:重构后 F1 = 0,C 表格有数据但**比 R 少一半行**。

**根因链路**:

| 步骤 | 改动 | 影响 |
| --- | --- | --- |
| 1 | SKILL.md §4 的 39 行 ASCII 流程图整段外移到 `references/router.md` | SKILL.md 主体失去详细路径信息 |
| 2 | 重构后 SKILL.md §4 只剩 5 行单行流程,Router 路径需要 Agent 多次 Read 才能拼出 | Agent 自主决策权增大 |
| 3 | Agent 在 Procedure 1 看到 R 链路包含中间组件(SMC、FCS),但判断"中间层不是必须",跳到"更直接"的路径(MCC → RKC → UPA) | 丢失 5-6 条交互 |
| 4 | 强匹配三元组(源,目标,接口)只匹配 1-2 个 | F1 = 0 |

**检查清单**(新增到 §8 清单后):

- [ ] **强制路径保护**:在 router.md 中关键链路标 ⚠️ 「**必须包含中间组件**」,SKILL.md §4 主体也保留一句话强制路径
- [ ] **不要追求「最直接」**:即使是 R 中的"经过中间层的复杂路径",Agent 也要按 R 实际描述生成,不能"简化"
- [ ] **回归测试用中间层需求**:R-N 场景应包含「MCC → SMC → RKC → FCS → UPA」类多跳链路

### 10.3 两类退化的共性

| 共性 | 解释 |
| --- | --- |
| **结构层通过,行为层失败** | SK-S1~S11 静态检查全 PASS(文件存在、引用闭合、无占位符),但实际跑出 F1=0 |
| **一句话总结** | 「重构不破坏文件 ≠ 重构不破坏行为」,**必须用 R-N 场景验证能力不退化** |
| **修复方向** | 加 SK-S12 脚本链接一致性检查 + R-N 中加入「中间层」+「完整链路」类回归场景 |

**对应到本文档章节**:§10 是 §7 设计反模式的实战化补充,§8 审查清单应增加上述两类检查项。---

## 7. d7bcf0da 风格 plan 模板(EnterPlanMode#1 必读)

> 当 CC 主 Agent 进入 EnterPlanMode 合成 refactor 计划时,**必须**按此模板写,否则 plan 会被用户打回。

### 7.1 现状段(详细 — 对标 d7bcf0da "Step 0 探索完成")

**禁止写成 "现状(简要)" 或 "略"**。必须含:

- **目标 Skill 概况**:路径、SKILL.md 体积(行/字节)、H2 章节数、references/scripts/templates 文件数
- **基础数据**:关系树(files count / edges count / orphans / long_unoptimized 列表)
- **findings 分类**:表格列出每条 FD-XXX 编号 / 主题 / 严重度,按主题分组
- **before_skill/ 快照**:路径(回滚源)
- **与 d7bcf0da 风格对齐说明**:1 段说"本计划采用 X 步 + Y 字段"

### 7.2 每步 4 字段格式(操作/不改/验收/回归)

```markdown
### Step N:<一句话操作标题>
**覆盖**:FD-XXX / FD-XXX

| 字段 | 内容 |
|------|------|
| **操作** | 用 Read + Edit 改什么文件(具体行/段) |
| **不改** | 明确列出本步骤不动哪些字段/章节(避免误伤) |
| **before** | 原文片段(便于验收对比) |
| **after** | 改后片段(便于验收对比) |
| **验收** | 具体命令 + 期望数字(如 `wc -l`、`grep -c`、`bash -n`) |
| **回归** | 跑什么命令确保没破坏现有结构 |
```

**禁止**:每步只写"操作 + 完成"两段。**必须**有"不改 / 验收 / 回归"三个字段。

### 7.3 7 步结构模板(对标 d7bcf0da)

| 步骤 | 主题 | 覆盖 findings 类别 |
|------|------|---------------------|
| Step 1 | frontmatter description 4 要素公式 | FD-001/003/011 |
| Step 2 | 内联内容合并到 references/(§3/§7 → execution-rules.md) | FD-002/008/013 |
| Step 3 | 精简内联代码(§1 / §5 冗余段) | FD-005/006/010/012 |
| Step 4 | 引用闭合性验证(越级路径修正) | FD-004/007 |
| Step 5 | 脚本化确定性操作(check_procedure_complete.sh) | FD-009 |
| Step 6 | 新增文件(execution-rules.md / check_procedure_complete.sh / work/task-state.json) | (支撑 Step 2/5) |
| Step 7 | 回归测试 + 出最终报告 | (对标 d7bcf0da "完成报告" 格式) |

### 7.4 最终报告格式(对标 d7bcf0da "组件间流程设计 Skill 重构 — 完成报告")

- **一、收益汇总**:SKILL.md 行数/字节数 before → after(表格)
- **二、7 步执行回顾表**:Step / 操作 / 验收结果(表格)
- **三、关键设计资产保留**:上下文预算感知 / Procedure 完成校验 / 5 个 Procedure 概念 / 13 个子步骤结构
- **四、新增/删除文件清单**:表格
- **五、与原 Plan 的差异**:实事求是(目标 vs 实际,接受未达预期)

### 7.5 验证命令(Step 7 必跑)

```bash
wc -l SKILL.md                # 应 < 250
wc -c SKILL.md                # 应 < 原始字节数
grep -c "\.\./" SKILL.md      # 越级引用应为 0
grep -c "Procedure" SKILL.md # 应 ≥ 5
bash -n scripts/check_procedure_complete.sh   # 语法 OK
python3 -c "import json; json.load(open('work/task-state.json'))"  # JSON 合法
```
