---
name: skill_create
description: 从原始需求代码化创建 cosight Skill — 4 阶段流水线(需求澄清→规格→单体实现→工程化),输出可直接被 CC 调用的 Plugin 形态 Skill。CC 主 Agent 编排,不调 orchestrator。当用户提"做个 skill"或"代码化"时触发。
argument-hint: "--requirement TEXT [--skill-name NAME]  [--expert-guidance TEXT]"
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


# `/skill_create` 代码化 Skill 制作

## 内置默认规范(必读)

> 本命令的所有产物**默认遵守** `framework_configs/skill-create-guidelines.md` 定义的规范(代码化优先、LLM 断点协议、异常处理、16 章节模板等)。**用户无需通过 `--expert-guidance` 重复传入这些规范**。
>
> `--expert-guidance` 仅用于补充**规范未覆盖的特殊约束**(如项目代码风格、性能约束、兼容性需求等),不会覆盖默认规范。

**3 个 subagent 默认加载规范**(注:插件 agent 的 Agent-tool `agentType` 一律带 `<插件名>:` 前缀,见 `skill-optimizer:` 开头的可用列表):
- `skill-optimizer:specification-writer-agent` → `Read framework_configs/skill-create-guidelines.md`
- `skill-optimizer:code-implementer-agent` → `Read framework_configs/skill-create-guidelines.md`
- `skill-optimizer:skill-scaffolder-agent` → `Read framework_configs/skill-create-guidelines.md`

## 核心模型

```
原始需求(自然语言,可能含"灵活/智能"等软化措辞)
  ↓ CC 主动反问 + 代码化引导
阶段1: 需求澄清(5W1H,代码化导向)
  ↓
阶段2: 规格说明书(16 章节,每步标 🟢/🟡/🔴)
  ↓
阶段3 (可选,默认开): 单体 Python 参考实现(标 🟢 用纯代码,标 🟡🔴 用 TODO 标记)
  ↓
阶段4: 工程化 Skill 目录(拆分阶段 3 主类为独立脚本 + run.py + LLM 断点)
  ↓
最终: 可被 CC 调用的 cosight Plugin 形态的 Skill
```

## 与现有 skill_\* 命令的关系(四元闭环)

```
/skill_create ──→ 产出 Skill v1
       ↓
/skill_optimize --mode optimize ──→ 静态评分+hill-climb
       ↓
/skill_optimize --mode refactor ──→ 结构层重构
       ↓
/skill_evolve ──→ 评测驱动拉满
       ↓ (用户使用,产生反馈)
       └→ 再次 /skill_create 增量扩展
```

- **`/skill_create`** 处理**从 0 到 1**(本命令)
- 其他 3 个命令均作用于**已存在**的 Skill

## 代码化设计哲学(贯穿 4 阶段)

> **核心信号**:从 step1 → step2 开始,用户刻意引导 CC 尽量使用代码化方式来制作 skill。

| 决策点 | 代码化方案 | LLM 方案 |
|--------|----------|----------|
| 阶段1 需求澄清 | 纯文本编号提问 5W1H(禁用 AskUserQuestion) | ❌ 不允许 LLM 自由发挥 |
| 阶段2 规格说明书 | 16 章节模板 + 字段强类型(表格/JSON schema) | 仅用于"语义填充"(异常处理描述、术语定义) |
| 阶段3 单体实现 | Python dataclass + 主类(确定性逻辑) | 仅标记"无法代码化"的语义推理点 |
| 阶段4 工程化 | scripts/*.py(确定性) + run.py 编排 | LLM 断点位置在 spec 中显式标注(🧠) |

**关键约束**:
- 阶段 2 spec 每个步骤必须标 🟢/🟡/🔴(🟢 ≥ 50%)
- 阶段 3 单体 Python 是 stage4 工程化的**骨架来源**——主类方法 = 独立脚本拆分单位
- 阶段 4 必须保留 LLM 断点的 `--resume` 协议(对标 step4 V2)

## 用法

```bash
# 最简:从原始自然语言需求开始
/skill_create --requirement "做一个读取 Excel 生成 Markdown 表格的 skill"

# 从文件读取原始需求(step1 风格)
/skill_create --requirement @/path/to/requirement.md

# 指定 Skill 名称
/skill_create --requirement "..." --skill-name excel-to-markdown

# 从中间阶段恢复(已有 spec,只跑阶段 3+4)
/skill_create \
  --requirement @/path/to/requirement.md \
  --skill-name excel-to-markdown \
  --start-stage 3 \
  --spec-path /path/to/02_skill_spec.md

# 跳过阶段 3(快速通道,失去骨架来源)
/skill_create --requirement "..." --skill-name foo --skip-stage-3

# 注入专家指引
/skill_create --requirement "..." \
  --expert-guidance "所有 Python 脚本必须用 type hints + 4 空格缩进"
```

## 参数说明

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--requirement TEXT` | ✅ | — | 原始需求描述;支持 `--requirement @file.md` 引用文件 |
| `--skill-name NAME` | ❌ | 自动推断 | Skill 名(**接受任意字符**:中文/英文/含空格),直接作为目录名使用,不需要规范化 |
| `--output-dir DIR` | ❌ | `${paths.root}/${paths.evolution_subdir}/skill_create_<ts>/`(由 config 派生,**严禁相对 cwd**) | 工作区根目录;未传则由 `config/create-user-config.yaml` 的 `paths.root` 派生(未配置则报错);不读环境变量 |
| `--start-stage {1\|2\|3\|4}` | ❌ | 1 | 从哪个阶段开始(支持从中间阶段恢复) |
| `--end-stage {1\|2\|3\|4}` | ❌ | 4 | 跑到哪个阶段停止 |
| `--spec-path PATH` | ❌ | 自动生成 | 阶段2 规格说明书路径(`--start-stage=3` 时必传) |
| `--consume-lib-path DIR` | ❌ | `${CONSUME_LIB_PATH}` | 知识库根目录(供阶段4 references/ 使用) |
| `--expert-guidance "TEXT"` | ❌ | 空 | 专家经验/规范/约束,注入所有子 Agent |
| `--skip-stage-3` | ❌ | false | 跳过单体 Python 实现阶段(默认开启) |
| `--no-interactive` | ❌ | false | 非交互模式(默认走 2 题二次确认) |

**互斥参数**:
- `--skip-stage-3` 不能与 `--start-stage=3` 同用(阶段 3 都不跑了,不可能从 3 开始)
- `--end-stage=1` + `--start-stage>1` 是逻辑矛盾,会报错

## 执行流程

### Step 0:解析 CLI 参数

提取所有参数,校验互斥。若用户输入 `--requirement @file.md`,立即 Read 加载。

### Step 1:必走 2 题二次确认(纯文本编号提问)

> 按上方"🧾 交互方式"规则:Q1/Q2 以纯文本编号列出,让用户回复编号/文本,不使用 AskUserQuestion。

> **设计原则**(根治 v2):Q1 让用户确认"要跑什么流程",Q2 让用户确认"填入什么参数"。**流程根据 `--start-stage` / `--end-stage` / `--skip-stage-3` 等参数动态推导**,而不是让用户在固定选项里被引导选"代码化 Skill"或"跳过阶段 3"等已经通过参数决定的事情。这样:
> - 用户原文已明确(如"只输出 spec")时,Q1 选项直接给出对应流程,不强行问"代码化 Skill / 仅 spec / 独立 CLI"三选一
> - 已通过 `--expert-guidance` 传入的指引不重复问"沿用 / 修改 / 不使用"
> - 避免旧版本里"Q1 选代码化 Skill + Q2 选跳过阶段 3"等逻辑耦合的误导组合
>
> **关于 Skill 名**:`--skill-name` **接受任意字符**(中文、英文、含空格、含特殊字符),直接作为目录名使用,不需要规范化。Python 3 Linux UTF-8 路径下中文目录正常工作。**不要**再问"是否规范化"。

#### Q1 · 确认执行流程

CC 根据当前 CLI 参数**动态推导**出实际要跑的阶段范围,展示给用户确认。推导规则:

| CLI 参数组合 | 推导的流程 | Q1 选项文案 |
|------------|----------|------------|
| 默认(无 `--start-stage` / `--end-stage` / `--skip-stage-3`) | 阶段 1→2→3→4 全跑 | "阶段 1→2→3→4(默认全跑,推荐)" |
| `--end-stage=2` | 阶段 1→2 | "阶段 1→2(只输出 spec,适用于用户已说'无需实现')" |
| `--end-stage=3` | 阶段 1→2→3 | "阶段 1→2→3(跳过工程化阶段 4)" |
| `--skip-stage-3` | 阶段 1→2→4 | "阶段 1→2→4(跳过阶段 3 单体实现,节省 30% 时间,但阶段 4 需从 spec 自行拆分)" |
| `--start-stage=2`(假设已有 brief) | 阶段 2→3→4 | "阶段 2→3→4(从已有 brief 开始,跳过阶段 1 澄清)" |
| `--start-stage=3` + `--spec-path` | 阶段 3→4 | "阶段 3→4(从已有 spec 恢复,只跑实现+工程化)" |

如果用户希望调整范围,可选"调整为其他范围"并填入新范围(如 `1→2` 或 `2→3`)。

#### Q2 · 确认填入参数

展示关键参数(`--requirement`、`--skill-name`、`--expert-guidance`、`--output-dir` 等)的当前值,让用户做最后一次确认或微调:
- 全部沿用 CLI 传入值(默认推荐)
- 我要修改某项(选 Other 填新文本,标注要改哪个参数)

**特别注意**:
- `--requirement` 若以 `@` 开头(如 `@/path/to/file.md`),展示**解析后的文件路径**和**文件首行**,便于用户确认是否加载了正确的文件
- `--skill-name` 直接展示用户传入的原值(不修改、不规范化),即使包含中文/空格
- `--expert-guidance` 展示完整文本(用于用户核对约束是否准确)

### Step 2:用户 1 句最终确认

把 Q1(流程)+ Q2(参数)的答案用一段文字展示给用户,**Skill 名直接展示用户传入的原值**(不修改),等用户说"确认"/"开始"等关键字。

### Step 3:创建工作区(调薄壳 Python)

**3.0 前置检查(必走,根治 v5)** — 调用 init 前先确认 `--output-dir` 来源:

`--output-dir` 的解析**只有两个来源,不读任何环境变量**:
1. **用户显式传入** `--output-dir <绝对路径>`(最高优先级)
2. **config 派生**:未传时由 `config/create-user-config.yaml` 的
   `paths.root` + `paths.evolution_subdir` 派生,落到
   `${paths.root}/${paths.evolution_subdir}/skill_create_<ts>/`

两者皆未配置时 init 直接报错退出(严禁硬编码 fallback 路径)。

**2 种合规调用方式**(选其一):

```bash
# 方案 A(最简,推荐):什么都不传,init 从 config 自动派生
#   适用:config/create-user-config.yaml 已配置 paths.root
python3 scripts/commands/skill_create.py init \
  --skill-name "${SKILL_NAME}" \
  --start-stage ${START_STAGE} \
  --end-stage ${END_STAGE}

# 方案 B:显式 --output-dir 到 evolution_workspace 根,不传 --taskid
#   适用:临时指定其它根,不依赖 config
#   行为:init 检测到 output-dir == workspace 根,自动派生 taskid 子目录
#         (根治 v4:不再污染 evolution_workspace 根)
python3 scripts/commands/skill_create.py init \
  --output-dir "/path/to/your/evolution_workspace" \
  --skill-name "${SKILL_NAME}" \
  --start-stage ${START_STAGE} \
  --end-stage ${END_STAGE}
```

如需复用已有 workspace(同一 taskid 继续跑),`--output-dir` 直接指向完整 taskid 路径即可,init 会复用 state.json 继续。

**禁止的调用方式**(会污染 evolution_workspace 根或漂出范围):

| 反例 | 症状 | 正确做法 |
|------|------|----------|
| `--output-dir evolution_workspace` + `--taskid skill_create_<ts>` | 拼成 `evolution_workspace.parent / skill_create_<ts>`(漂出 evolution_workspace,报错) | 改用方案 A 或方案 B |
| `--output-dir evolution_workspace`(不传 taskid,**v4 之前会污染根**) | v3 之前会在 evolution_workspace 根散落 state.json + 占位文件 | v4 已修复,init 自动派生子目录 |
| `--output-dir /任意目录/xxx`(不在默认根下) | init 报"漂出 workspace root" | 先改 config `paths.root`,或确保路径落在该根下 |

**路径派生优先级链**(根治 v5,严禁相对 cwd):
1. `--output-dir`(用户显式输入,绝对路径)
2. `config/create-user-config.yaml` 的 `paths.root` → `${paths.root}/${paths.evolution_subdir}`
3. 两者皆未配置 → 报错,严禁硬编码 fallback

薄壳 Python 创建:
- `${paths.root}/${paths.evolution_subdir}/skill_create_YYYYMMDD_HHMMSS/`(**绝对路径**,由 config 决定根)
- `state.json`(记录已完成的阶段)
- 阶段产物文件的占位文件(0 字节)

**重要**:`mkdir -p evolution_workspace/...` 相对路径写法已废止,严禁再用(导致落点漂移污染)。

### Step 4:阶段 1 — 输入处理 + 需求澄清

**输入形式检测**(基于 `--requirement` 参数):

- **若 `--requirement @<file>.md`** → **直接复制原文件**为 `01_<原文件名>.md`(保留原文件名/扩展名),**跳过 brief 生成,不做任何重写/整理/格式化**。原文件已自带完整需求。
- **若 `--requirement "自然语言..."`** → 走原 5W1H 澄清流程,生成 `01_requirement_brief.md`:
  - CC 主 Agent 直接处理(不调子 Agent,交互式对话)
  - 用**纯文本编号提问**反向 5W1H(按上方"🧾 交互方式"规则列 5 个编号问题,不用 AskUserQuestion),**主动引导用户往代码化方向**
  - 输出 `01_requirement_brief.md`(5W1H 结构化)
  - 展示后问"是否进入阶段 2"

**关键反问**(仅自然语言输入时):
- 若用户提"灵活/智能/根据情况"等软化措辞 → **主动反问**:"能否用明确规则表达?是否可拆成确定性子步骤 + LLM 断点?"
- 默认推荐"**代码化 Skill (Plugin 形态)**"作为产物形式

更新 `state.json`: `{"completed_stages": [1], "current_stage": 1}`

### Step 5:阶段 2 — 规格说明书生成

调 `skill-optimizer:specification-writer-agent`(传入 `01_xxx.md`(用户原文件或 brief)+ `--expert-guidance`)。

agent 输出 `02_skill_spec.md`(16 章节 + 每个步骤标 🟢/🟡/🔴)。

**CC 自检 16 项硬约束清单**(不通过触发 LLM 自我修正,最多 2 次,失败则提示用户手动补全):
```
☐ 含 16 个章节标题(1.~17.)
☐ §1.1 输入项表 ≥1 行
☐ §1.2 读取的文件表 ≥1 行
☐ §1.3 输出产物表 ≥1 行
☐ §2 核心概念 ≥3 类
☐ §3 执行流程图非空
☐ §4~§N 步骤详述每个含 5 字段(操作/前置/输出/校验/异常)
☐ 每个步骤标注代码化属性(🟢/🟡/🔴)
☐ 🟢 步骤占比 ≥ 50%
☐ 附录 A 输出格式规范非空
☐ 附录 B 异常处理矩阵 ≥3 行,优先用代码化方式
☐ 附录 C 术语速查 ≥5 项
☐ 全文无"建议灵活"/"根据情况"等软化措辞
☐ 全文无绝对路径硬编码
☐ 至少 1 个 LLM 断点标记(🧠),且 references/ 中对应 prompt 模板
☐ 步骤数 N ≥ 3 且无循环引用
```

通过后更新 `state.json`。

### Step 6:阶段 3 — 单体实现(可选,默认开启)

**仅当 `--skip-stage-3=false` 且 `start_stage <= 3` 时执行**。

调 `skill-optimizer:code-implementer-agent`(传入 `02_skill_spec.md`)。

agent 输出 `03_monolithic_impl.md`(单 .md 文件,内含 Python 代码块,约 1000 行,含 4~5 个 dataclass + 1 个主类)。

**强制规则**:
- 标 🟢 的步骤用纯 Python 代码块实现(确定性逻辑)
- 标 🟡 的步骤用 prompt 模板占位 + 注释
- 标 🔴 的步骤用 `# TODO: LLM 断点` 标记

CC 简单检查文件存在且非空(用 `wc -l` 验证 ≥ 50 行),更新 `state.json`。

### Step 7:阶段 4 — 工程化 Skill 生成

调 `skill-optimizer:skill-scaffolder-agent`(传入 `02_skill_spec.md` + `03_monolithic_impl.md` + `--consume-lib-path`)。

**核心原则**:**阶段 4 = 阶段 3 单体的分布式重构**——把单体类的方法拆成独立脚本 + run.py 主控 + LLM 断点。

agent 内部执行 6 个子步骤(4a~4f),产出:
```
04_skill_dir/{skill-name}/
├── SKILL.md                    # CC 调用的入口
├── scripts/
│   ├── run.py                  # 主控(阶段化调度 + LLM 断点 + --resume)
│   ├── step1_*.py              # 每个 spec 步骤一个独立脚本
│   ├── step2_*.py
│   └── ...
├── references/
│   ├── output-schema.md        # 输出格式规范
│   ├── step1-rules.md          # LLM 断点 prompt 模板(含 JSON schema)
│   └── ...
└── templates/
    └── output-template.md      # 最终产物模板
```

**LLM 断点协议**(对标 step4 V2):
- run.py 检测到需要 LLM 推理时,写入 `llm_task_X.json` 后退出(返回码 0 + 提示)
- CC 读任务文件,推理后写 `llm_response_X.json`,调 `run.py --resume` 继续
- 每个 references/stepN-rules.md 顶部强制含**响应格式契约(JSON schema)**

**CC 自检 8 项目录骨架清单**:
```
☐ SKILL.md 含 frontmatter(name + description 三要素)
☐ SKILL.md description 含"做什么 + 何时用 + 触发词"
☐ scripts/ 含 run.py(可执行 python3 scripts/run.py --help)
☐ references/ 至少含 output-schema.md
☐ templates/ 含 output-template.md
☐ 至少 1 个 LLM 断点有对应的 references/stepN-rules.md
☐ scripts/ 数量 ≥ spec 步骤数
☐ 目录结构与 step4 V2 一致(SKILL.md + scripts/ + references/ + templates/)
```

不通过则让 `skill-optimizer:skill-scaffolder-agent` 自动补全,最多 2 次。

### Step 8:出最终报告 + 下一步建议

写 `final_report.md`,含:
- 各阶段产物路径
- 16 项硬约束清单结果
- 8 项目录骨架自检结果
- 下一步建议(4 个选项)

```markdown
## 下一步建议(任选)

### A. 静态打磨(推荐)
/skill_optimize --mode optimize --skill-path {workspace}/04_skill_dir/{skill-name}/SKILL.md \
  --expert-guidance "<本 Skill 的领域约束>"

### B. 结构层重构
/skill_optimize --mode refactor --skill-path {workspace}/04_skill_dir/{skill-name}/SKILL.md

### C. 评测驱动拉满
/skill_evolve --skill-path {workspace}/04_skill_dir/{skill-name}/SKILL.md \
  '<你的 eval-cmd>'

### D. 直接试跑
cd {workspace}/04_skill_dir/{skill-name} && python3 scripts/run.py --help
```

## subagent 列表

| Subagent | 步骤 | 输入 | 输出 |
|----------|------|------|------|
| `skill-optimizer:specification-writer-agent` | 5 | brief + expert-guidance | spec.md |
| `skill-optimizer:code-implementer-agent` | 6 | spec.md | monolithic_impl.md |
| `skill-optimizer:skill-scaffolder-agent` | 7 | spec.md + impl.md + consume-lib | 完整 Skill 目录 |

## 产物

```
{output_dir}/
├── state.json                          # 状态文件(支持 resume)
├── 01_<用户原文件名>.md                # 阶段1(@file.md 直接复制) 或 01_requirement_brief.md(自然语言澄清产物)
├── 02_skill_spec.md                    # 阶段2(16 章节 + 代码化属性)
├── 03_monolithic_impl.md               # 阶段3(单 .md 文件,内含 Python 代码块)
├── 04_skill_dir/                       # 阶段4
│   └── {skill-name}/
│       ├── SKILL.md
│       ├── scripts/
│       ├── references/
│       └── templates/
└── final_report.md                     # 最终报告
```

## 硬约束(用户视角)

1. **必走 2 题二次确认**(Step 1,Q1 流程 + Q2 参数)
2. **必等用户 1 句最终确认**(Step 2)
3. **阶段 2 必须通过 16 项硬约束清单**(Step 5 自检)
4. **阶段 4 必须通过 8 项目录骨架自检**(Step 7 自检)
5. **`--start-stage N` 支持从中间阶段恢复**(state.json 自动追踪)
6. **工作区路径必须落在 `evolution_workspace/skill_create_*/`**
7. **禁止修改 live skill_root**(产物只在工作区)
8. **禁止全量重写 spec**(LLM 子 Agent 只能补全缺失章节)
9. **代码化优先**:阶段 2 subagent prompt 显式"代码化优先"指令
10. **代码化属性标注**:阶段 2 spec 每个步骤必须标 🟢🟡🔴
11. **LLM 断点协议**:阶段 4 必须保留 `--resume` + 任务/响应 JSON 文件协议
12. **中间产物可见性**(framework §1.6):**每个阶段产物生成后,CC 必须用 `cat` / `head` / `wc -l` / `find` 打印到控制台**,禁止静默写文件

## 相关文件

- 本文件:命令契约(行为约束,不参与执行)
- `scripts/commands/skill_create.py`:薄壳 Python(工作区初始化 + state.json 读写 + 产物校验)
- `agents/specification-writer-agent.md`:阶段 2 subagent
- `agents/code-implementer-agent.md`:阶段 3 subagent
- `agents/skill-scaffolder-agent.md`:阶段 4 subagent

## 实战案例

完整实战案例见 `docs/skill-create-用例-组件间流程设计.md`,演示用本命令从 step1 自然语言思路 → 完整工程化 Skill 的完整流程。
