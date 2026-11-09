# /skill_create 代码化 Skill 制作

## 一、一句话定位

`/skill_create` 是 skillx-alpha-agents 框架的**从 0 到 1 代码化 Skill 创建命令**。业务方提供 1 条自然语言需求(可附知识库路径),框架用"4 阶段流水线(需求澄清 → 规格 → 单体实现 → 工程化)"方法论,自动产出**完整 cosight Plugin 形态的 Skill 目录**(`SKILL.md` + `scripts/run.py` + `references/` + `templates/`),可直接被 cosight 调用。

跟 `/skill_optimize --mode optimize`(内容质量 12 维评分) / `/skill_optimize --mode refactor`(结构重构) / `/skill_evolve`(评测驱动联合优化)的关键区别:**从 0 到 1 创建新 Skill**,不是优化已有 Skill。

---

## 二、3 步快速开始

### 形式 A:从原始自然语言需求开始

```bash
# Step 1: 准备需求(自然语言 / Markdown 文件均可)
/skill_create --requirement "做一个读取 Excel 生成 Markdown 表格的 skill"

# Step 2: 调用 CC,走 2 题二次确认(执行流程 / 填入参数)
# CC 会自动反问:
#   Q1: 阶段 1→2→3→4 全跑? / 阶段 1→2(只输出 spec)?
#   Q2: 参数全部沿用? / 我要修改某项?

# Step 3: CC 启动 4 阶段流水线,产物落盘
# 产物路径: ${SKILLX_WORKSPACE}/skill_create_YYYYMMDD_HHMMSS/
```

### 形式 B:从 Markdown 文件加载(本次实战)

```bash
# Step 1: 准备需求文件 + 知识库路径
ls /path/to/组件间流程设计-方案.md  # 7 步骤原始需求
ls /path/to/知识库/consume_lib        # 业务背景知识

# Step 2: 调用 CC,@file.md 形式跳过 5W1H 澄清(原文件已自带完整需求)
/skill_create \
  --requirement @/path/to/组件间流程设计-方案.md \
  --skill-name 组件间流程设计 \
  --expert-guidance "知识库 consume_lib + 子系统间消息处理组件规则 复用为 references/"

# Step 3: CC 自动完成 4 阶段流水线
# 产物落盘到 evolution_workspace/skill_create_YYYYMMDD_HHMMSS/
```

### 形式 C:从中间阶段恢复(已有 spec,只跑实现+工程化)

```bash
# 复用已有 spec,只跑阶段 3+4
/skill_create \
  --requirement @/path/to/requirement.md \
  --skill-name foo \
  --start-stage 3 \
  --spec-path /path/to/02_skill_spec.md
```

---

## 三、4 阶段流水线(对应方法论 4 大节点)

### 阶段 1:输入处理 + 需求澄清(🟢 代码化)

**输入形式检测**:
- `--requirement @<file>.md` → 直接复制原文件为 `01_<原文件名>.md`,**跳过 5W1H 澄清**(原文件已自带完整需求)
- `--requirement "<自然语言>"` → 走 5W1H 澄清(CC 主动反问 5 维度),生成 `01_requirement_brief.md`

**关键反问**(仅自然语言输入时):
- 若用户提"灵活/智能/根据情况"等软化措辞 → 主动反问"能否用明确规则表达?是否可拆成确定性子步骤 + LLM 断点?"
- 默认推荐"代码化 Skill (Plugin 形态)"作为产物形式

**产物**:`{workspace}/01_*.md`(`01_<原文件名>.md` 或 `01_requirement_brief.md`)

### 阶段 2:16 章节规格说明书

基于阶段 1 产物 + `--expert-guidance`,生成**16 章节规格说明书**,每个步骤标 🟢/🟡/🔴(代码化属性)。

**16 章节模板**:
1. 输入与输出
2. 核心概念(数据对象 ≥ 3 类)
3. 执行流程总览
4. 步骤详述(每个含 5 字段:操作/前置/输出/校验/异常)
5. 异常处理
6. 产物格式规范
7. 术语速查
8. 质量门槛自检
9. ...

**16 项硬约束清单**:
- 含 16 章节标题
- §1.1 输入项表 ≥ 1 行
- §1.2 读取的文件表 ≥ 1 行
- §1.3 输出产物表 ≥ 1 行
- §2 核心概念 ≥ 3 类
- §3 执行流程图非空
- §4~§N 步骤详述每个含 5 字段
- 每个步骤标注代码化属性(🟢/🟡/🔴)
- 🟢 步骤占比 ≥ 50%
- 附录 A 输出格式规范非空
- 附录 B 异常处理矩阵 ≥ 3 行
- 附录 C 术语速查 ≥ 5 项
- 全文无"建议灵活"/"根据情况"等软化措辞
- 全文无绝对路径硬编码
- 至少 1 个 LLM 断点标记(🧠),且 `references/` 中对应 prompt 模板
- 步骤数 N ≥ 3 且无循环引用

**产物**:`{workspace}/02_skill_spec.md`

### 阶段 3:单体 Python 参考实现(可选)

基于阶段 2 spec,生成**单 .md 文件**(`03_monolithic_impl.md`,内含 Python 代码块约 1000 行,含 4~5 个 dataclass + 1 个主类)。

**强制规则**:
- 标 🟢 的步骤用纯 Python 代码块实现(确定性逻辑)
- 标 🟡 的步骤用 prompt 模板占位 + 注释
- 标 🔴 的步骤用 `# TODO: LLM 断点` 标记

**7 段强制 markdown 章节**:
1. 文件元信息
2. 依赖声明
3. LLM 兜底声明
4. 步骤对照表(spec 步骤 ↔ 主类方法)
5. LLM 兜底说明
6. 限制/假设/边界
7. 测试/验证方式

**产物**:`{workspace}/03_monolithic_impl.md`

> **可跳过**:`--skip-stage-3` 跳过此阶段(节省约 30% 时间,但阶段 4 需从 spec 自行拆分,可能比有单体的版本略粗糙)

### 阶段 4:工程化 Skill 目录

**核心原则**:**阶段 4 = 阶段 3 单体的分布式重构**——把单体类的方法拆成独立脚本 + run.py 主控 + LLM 断点。

**产物**:
```
{workspace}/04_skill_dir/{skill-name}/
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
- 每个 `references/stepN-rules.md` 顶部强制含**响应格式契约(JSON schema)**

**8 项目录骨架清单**:
- SKILL.md 含 frontmatter(name + description 三要素)
- SKILL.md description 含"做什么 + 何时用 + 触发词"
- scripts/ 含 run.py(可执行 `python3 scripts/run.py --help`)
- references/ 至少含 output-schema.md
- templates/ 含 output-template.md
- 至少 1 个 LLM 断点有对应的 `references/stepN-rules.md`
- scripts/ 数量 ≥ spec 步骤数
- 目录结构与 step4 V2 一致(SKILL.md + scripts/ + references/ + templates/)

**8 + 13 项硬约束自检全部通过**才视为完成。

**产物**:`{workspace}/04_skill_dir/{skill-name}/`

### 阶段 5:最终报告

写 `final_report.md`,含:
- 各阶段产物路径
- 16 项硬约束清单结果
- 8 项目录骨架自检结果
- 4 大产物类别(Plugin 形态)
- 下一步 4 个建议

**产物**:`{workspace}/final_report.md`

---

## 四、参数说明

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--requirement TEXT` | ✅ | — | 原始需求描述;支持 `--requirement @file.md` 引用文件 |
| `--skill-name NAME` | ❌ | 自动推断 | Skill 名(**接受任意字符**:中文/英文/含空格),直接作为目录名使用 |
| `--output-dir DIR` | ❌ | `${SKILLX_WORKSPACE}/skill_create_<ts>/` | 工作区根目录;**严禁相对 cwd** |
| `--start-stage {1\|2\|3\|4}` | ❌ | 1 | 从哪个阶段开始(支持从中间阶段恢复) |
| `--end-stage {1\|2\|3\|4}` | ❌ | 4 | 跑到哪个阶段停止 |
| `--spec-path PATH` | ❌ | 自动生成 | 阶段 2 规格说明书路径(`--start-stage=3` 时必传) |
| `--consume-lib-path DIR` | ❌ | `${CONSUME_LIB_PATH}` | 知识库根目录(供阶段 4 references/ 使用) |
| `--expert-guidance "TEXT"` | ❌ | 空 | 专家经验/规范/约束,贯穿所有阶段 |
| `--skip-stage-3` | ❌ | false | 跳过单体 Python 实现阶段(默认开启) |
| `--no-interactive` | ❌ | false | 非交互模式(默认走 2 题二次确认) |

**互斥参数**:
- `--skip-stage-3` 不能与 `--start-stage=3` 同用
- `--end-stage=1` + `--start-stage>1` 是逻辑矛盾,会报错

**环境变量优先级链**:
1. `--output-dir`(显式传,绝对路径)
2. `SKILLX_WORKSPACE` 环境变量
3. `SKILLX_ROOT/evolution_workspace` 派生
4. 两者皆未设置 → 报错,严禁硬编码 fallback

---

## 五、与 skill_\* 命令族的关系(四元闭环)

```
   /skill_create ──→ 产出 Skill v1
          ↓
   /skill_optimize --mode optimize ──→ 静态 12 维评分 + 多轮 hill-climb
          ↓
   /skill_optimize --mode refactor ──→ 结构层重构(plan-mode 人机协同)
          ↓
   /skill_evolve ──→ 评测驱动多 Skill 联合优化
          ↓ (用户使用,产生反馈)
          └→ 再次 /skill_create 增量扩展
```

| Command | 用途 | 何时用 |
|---------|------|--------|
| `/skill_create` | 从 0 到 1 代码化创建 Skill | 业务方没有 Skill,需要首次创建 |
| `/skill_optimize --mode optimize` | 静态 12 维 LLM judge 评分 | 内容质量不达标(描述模糊/缺失败模式) |
| `/skill_optimize --mode refactor` | 结构层重构 | 文件结构乱/超长/引用断裂 |
| `/skill_evolve` | 评测驱动联合优化 | 有业务方 eval-cmd + CASE 数据 |

---

## 六、4 大产物类别(Plugin 形态)

`/skill_create` 最终产物是一个**完整 cosight Plugin 目录**,由 4 大类组成:

| 类别 | 作用 | 典型内容 |
|------|------|----------|
| **SKILL.md** | CC 调用的入口 | frontmatter(name + description 三要素)+ 13 个 CLI 参数说明 + LLM 断点续跑协议 |
| **scripts/** | 主控 + step 脚本 | `run.py`(主控 + LLM 断点)+ `step1~stepN.py`(每个 spec 步骤一个独立脚本)+ `validate_*.py` + `_state_machine.py` |
| **references/** | 契约 + 规则库 | `output-schema.md`(中间 JSON 契约)+ `llm_a_*.md` / `llm_b_*.md`(LLM 断点契约,含 JSON Schema)+ 业务规则文件(从 `consume_lib` 复用) |
| **templates/** | 最终产物模板 | `output-template.md`(用户最终看到的产物结构模板,如"组件间流程设计结果.md") |

**4 类协同关系**:
- `SKILL.md` 告诉 CC 怎么调用
- `scripts/run.py` 按 `references/output-schema.md` 契约读输入,逐步执行 `step1~stepN.py`
- 步骤中遇到 LLM 推理时,按 `references/llm_*.md` 契约写 `llm_task_X.json`,CC 推理后写 `llm_response_X.json` 续跑
- 全部完成后按 `templates/output-template.md` 渲染最终产物

> 阶段 1~3 产物(`01_*.md` / `02_skill_spec.md` / `03_monolithic_impl.md`)+ `final_report.md` 是**工作区中间产物**,4 大类才是**用户直接用的 Plugin 目录**。

---

## 七、设计哲学:好的骨架 = 后续维护和持续迭代的基础

`/skill_create` 强守 4 条核心设计原则,**这 4 条是让产物能被长期维护和持续迭代的关键**:

### 1. 高度代码化(能用代码绝不用 LLM)

- spec 阶段强制每个步骤标 🟢/🟡/🔴,**🟢 步骤占比 ≥ 50%**(本次实战 78.6%)
- 标 🟢 的步骤用纯 Python 实现(确定性逻辑);LLM 只介入真正的语义推理点
- 校验函数拆为独立 `check_*` 纯函数(本次 14 个),支持 `--check <item_name>` 单项 CLI
- 反模式零容忍:无"灵活处理"/"根据情况"/"可能需要"等软化措辞

**价值**:代码化高的产物行为可预测、错误可定位、回归可测试;LLM 调用少的产物成本低、可重复、不幻觉。

### 2. 合理设计(职责单一 + 接口清晰)

- 4 大产物类别边界清晰:`SKILL.md`(入口)/ `scripts/`(执行)/ `references/`(契约+规则)/ `templates/`(产物)
- `scripts/run.py` 极简调度(本次 247 行,vs 参考答案 940 行),业务逻辑下沉到 `step1~stepN.py`
- `_state_machine.py` 单独抽离状态机 + `validate_or_revert()`(状态机包裹的 revision loop)
- `references/output-schema.md` 统一所有中间 JSON 契约(19 个 JSON 文件的 schema 一处定义)

**价值**:职责清晰的骨架易于单步调试、单元测试、版本回滚;接口契约统一让"加新 step"成本最小化。

### 3. 渐进式披露(每层只看该看的信息)

- `SKILL.md` 只暴露**用户视角**(做什么、何时用、怎么调用),不暴露 subagent / state machine 等内部实现
- `scripts/stepN.py` 每个 step 一个独立文件,只关心自己输入输出 + 下一 step 的约定
- `references/llm_*.md` 是 LLM 推理的**唯一契约**,CC 不需要读 step 脚本源码就能完成推理
- 异常处理矩阵(28 行)按 FATAL/ERROR/WARNING 分级,exit code 12 个(0/1/2/3/4/10/11/15/18~21)便于 CI 区分

**价值**:渐进式披露的骨架降低新人上手成本;每层抽象独立可换(如换 run.py 不影响 step 脚本,换 LLM 契约不影响主控)。

### 4. 好的骨架 = 后续维护和持续迭代的杠杆

| 阶段 | 维护成本 | 迭代成本 | 杠杆 |
|------|----------|----------|------|
| 无骨架(裸 spec) | 高(每次重写) | 极高(改一处全要重测) | 1× |
| 烂骨架(职责混乱) | 中(找代码要翻半天) | 高(改了 N 个文件) | 2~3× |
| **好骨架(本次 4 大类)** | **低(单步独立 + 状态机)** | **低(只改 1 个 step)** | **5~10×** |

**实证**(`taskid_20260714_152750`):
- 加 1 个新 step:只需新增 `stepN.py` + 在 `STEP_TABLE` 加 1 行 + `references/output-schema.md` 加 1 段 schema,改 3 个文件
- 修 1 个 bug:进对应 `stepN.py`,看 `state_dir/NN_xxx.json` 找现场,改完用 `--check <item_name>` 单项验证
- 换 LLM 模型:只改 `references/llm_*.md` 契约,step 脚本不动
- 演进到下一个版本:跑 `/skill_optimize --mode optimize` 在原骨架上打分,7 类真实修复问题精准定位

**核心洞察**:**好骨架不是"代码写得多",而是"接口切得对"**。`/skill_create` 的 4 大类骨架让"加新功能"从"重写"降级为"填空",从"调试整库"降级为"调试单步",从"改一处全崩"降级为"改一处安全回退"——这是 Skill 能从 v1 演化到 vN 的根本基础。

---

## 八、实战案例:组件间流程设计 Skill 创建

**输入**:`/media/vdb/skillx-alpha/代码化skill制作-输入/组件间流程设计-方案.md`(7 步骤原始需求,含 3 个输入)
**专家指引**:知识库 `consume_lib` + `子系统间消息处理组件规则` 复用为 `references/`

| 阶段 | 产物 | 实测指标 | 阈值 |
|------|------|---------|------|
| 1. 输入处理 | `01_组件间流程设计-方案.md` | 25 行 / 4 KB | @file.md 直接复制 |
| 2. 16 章节 spec | `02_skill_spec.md` | 845 行 / 48 KB | 16 项硬约束 ✅,🟢 占比 78.6% |
| 3. 单体 Python | `03_monolithic_impl.md` | 1872 行 / 80 KB | Python 1753 行,py_compile PASS |
| 4. 工程化 Skill | `04_skill_dir/组件间流程设计/` | 3413 行 / 216 KB | 18 脚本 + 9 references + 1 template |
| 5. 最终报告 | `final_report.md` | 12 KB | 8 + 13 项自检全 PASS |

**4 阶段流水线实战体现**:
- 阶段 1:`@file.md` 跳过 5W1H,直接复制原文件
- 阶段 2:4 处 LLM 断点标记(LLM-A 规则匹配 + LLM-B 综合流程变更)
- 阶段 3:14 个主类方法 1:1 对应 spec 步骤,8 个 dataclass,14 个 check_* 校验函数
- 阶段 4:13 个 step 脚本独立(1:1 对应 impl),run.py 极简调度(247 行 vs 参考答案 940 行),状态机抽离 + validate_or_revert(本次独有)

**深度对比参考答案**(`step4:组件间流程设计V2`):
- ✅ 功能完整度:本次 ≈ 参考答案(本次多 revision loop + 14 项 check_* + 12 退出码)
- ⚠️ 代码化程度:参考答案 > 本次(参考答案 step4 是 415 行纯 Python,本次靠 LLM-A 推理)
- ✅ 工程化:本次 > 参考答案(本次 DDD 风格,run.py 247 vs 940 行)
- ✅ 规范合规:双方都 0 反模式命中

---

## 九、一句话总结

**`/skill_create` = 4 阶段流水线(需求澄清 → 16 章节 spec → 单体 Python → 工程化 Skill 目录) + 16 + 8 + 13 项硬约束自检**,业务方提供 1 条需求 + 知识库路径,框架自动产出**完整 cosight Plugin 形态的 Skill**,可直接被 CC 调用。`taskid_20260714_152750` 实证 4 阶段全跑产出 3413 行 Skill 目录(18 脚本 + 9 references + 1 template),py_compile + run.py --help 全部 PASS,从 0 到 1 创建 Skill 不再需要手动编排 13 个 step 脚本。

**4 条设计哲学贯穿产物**:
- **高度代码化**:🟢 步骤 ≥ 50%,LLM 只介入真语义点(本次 78.6%)
- **合理设计**:4 大类职责清晰,run.py 极简调度(247 行 vs 940 行)
- **渐进式披露**:每层只看该看的信息(用户只看 SKILL.md,CC 只看 references/llm_*.md)
- **好的骨架 = 后续维护和迭代的杠杆**:加新 step 改 3 个文件,修 bug 用 `--check` 单项验证,换 LLM 只改契约不动脚本——让 Skill 能从 v1 演化到 vN

---

**文档版本**:v1.0
**生成时间**:2026-07-14
**参考来源**:
- `commands/skill_create.md`(命令契约)
- `framework_configs/skill-create-guidelines.md`(规范)
- `docs/skill-create-用例-组件间流程设计.md`(实战案例)
- `evolution_workspace/skill_create_20260714_152750/final_report.md`(本次执行报告)
- iSpace 风格参考:`skill_evolve` (page 05c3820b) / `skill_optimize` (page 54e5ff9a)
