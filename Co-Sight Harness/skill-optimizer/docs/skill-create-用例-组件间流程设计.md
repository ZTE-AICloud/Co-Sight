# 实战案例:用 `/skill_create` 从 step1 自然语言思路生成完整工程化 Skill

> **目的**:演示用 `/skill_create` 命令,以"组件间流程设计"任务为示范,展示从用户自然语言思路 → 完整 cosight Plugin 形态 Skill 的完整流程。
>
> **本案例对照**:`/media/vdb/skillx-alpha/代码化skill制作/` 4 步方法论的"代码化封装版"。

---

## 0. 案例背景

### 0.1 原始方法论(对照)

`/media/vdb/skillx-alpha/代码化skill制作/` 是用户手工完成的 4 步方法论样例:

| 步骤 | 文件 | 行数 | 性质 |
|------|------|------|------|
| step1 | `step1：组件间流程设计-方案.md` | 30 行 | 自然语言思路 |
| step2 | `step2：组件间流程设计-Skill规格说明书.md` | 700 行 | 16 章节规格说明书 |
| step3 | `step3：组件间流程设计-代码实现.md` | 1100 行 | 单体 Python 实现 |
| step4 | `step4：组件间流程设计V2/` | 36 文件级 | 完整工程化 Skill |

### 0.2 用 `/skill_create` 复现的目标

调用本命令后,自动产出**结构完全等价**的 4 阶段产物,关键差异:

| 维度 | 手工方法论 | `/skill_create` 自动化 |
|------|----------|---------------------|
| 阶段 1 brief | 用户自己整理 5W1H | CC 主动反问代码化相关问题 |
| 阶段 2 spec | 用户写 700 行规格 | `specification-writer-agent` 自动生成(每个步骤标 🟢🟡🔴) |
| 阶段 3 实现 | 用户手写 1100 行 Python | `code-implementer-agent` 自动生成(🟢 用纯代码,🟡🔴 用 TODO) |
| 阶段 4 Skill | 用户手写 9 个脚本 + run.py | `skill-scaffolder-agent` 拆分主类方法为独立脚本 |
| 校验 | 人工 review | 16 项硬约束 + 8 项目录骨架自检 |

---

## 1. 调用命令

```bash
# 完整流程(从 step1 思路开始,跑到完整 Skill)
/skill_create \
  --requirement @/media/vdb/skillx-alpha/代码化skill制作/step1：组件间流程设计-方案.md \
  --skill-name inter-component-flow-design \
  --consume-lib-path "${CONSUME_LIB_PATH}"
```

### 1.1 解析后的参数

| 参数 | 值 | 来源 |
|------|----|------|
| `--requirement` | step1 全文(30 行) | 从文件加载 |
| `--skill-name` | `inter-component-flow-design` | 用户指定 |
| `--output-dir` | `evolution_workspace/skill_create_YYYYMMDD_HHMMSS/` | 自动 |
| `--start-stage` | 1 | 默认 |
| `--end-stage` | 4 | 默认 |
| `--skip-stage-3` | false | 默认(包含阶段 3) |
| `--consume-lib-path` | `${CONSUME_LIB_PATH}` | 环境变量 |

---

## 2. Step 1:必走 3 题二次确认(AskUserQuestion)

### Q1 · 产物形态(代码化引导)

CC 展示的选项:

- **代码化 Skill (Plugin 形态,推荐)** — 对标 step4 V2,SKILL.md + scripts/ + references/ + templates/,确定性逻辑用 Python,语义推理用 LLM 断点
- 仅规格说明书(spec 即终点,用户自己实现)
- 独立 CLI 工具(单文件 Python)

**用户选择**:代码化 Skill (Plugin 形态)

### Q2 · 跳过模式

- 全跑(含阶段 3 单体实现,推荐) — 阶段 3 是 stage4 骨架来源
- 跳过阶段 3(直接 spec → 工程化 Skill)

**用户选择**:全跑

### Q3 · 专家指引

- 沿用 CLI `--expert-guidance`
- 我要补充/修改
- 不使用指引

**用户选择**:沿用 CLI(用户没传 `--expert-guidance`,故为空)

### Step 2:用户 1 句最终确认

CC 展示:
```
即将执行 /skill_create:
  - Skill 名: inter-component-flow-design
  - 范围: 阶段 1 → 4(含阶段 3)
  - 工作区: evolution_workspace/skill_create_20260710_140000/
确认开始?(回复"确认"或"开始")
```

用户回复:确认

---

## 3. Step 3:创建工作区(调薄壳 Python)

```bash
python3 scripts/commands/skill_create.py init \
  --output-dir /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000 \
  --skill-name inter-component-flow-design \
  --start-stage 1
```

**输出**:
```
[OK] 工作区已创建: /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000
  - state.json: .../state.json
  - 起始阶段: 1, 结束阶段: 4
```

**工作区初始结构**:
```
skill_create_20260710_140000/
├── state.json                          # 状态文件
├── 01_requirement_brief.md             # 占位(0 字节)
├── 02_skill_spec.md                    # 占位(0 字节)
├── 03_monolithic_impl.md               # 占位(0 字节)
└── 04_skill_dir/                       # 阶段 4 产物根
```

---

## 4. Step 4:阶段 1 — 需求澄清

CC 主 Agent 直接处理(不调子 Agent)。

### 4.1 5W1H 反问(代码化引导)

CC 用 `AskUserQuestion` 提问:

- **What**:Skill 要做什么(尽量描述成"输入→处理→输出"的明确管道)
  - 用户答:输入是 req_design_document.md,输出是子系统的组件间流程设计结果 .md
- **Why**:为什么需要
  - 用户答:把子系统间协作流程细化为子系统内部组件间协作流程
- **Who**:谁会调用
  - 用户答:5G NR 基站设计人员
- **Where**:数据来源 / 产物落盘位置
  - 用户答:输入在 `${需求工作目录}/req_design_document.md`,知识库在 `consume_lib/`
- **When**:触发场景
  - 用户答:做"特性域变更分析"时
- **How**:大致处理思路
  - 用户答:11 步流水线:读组件变更 → 读子系统间流程 → 过滤 → 转换 → 决策分支 → 插入 → 补全 → 生成 PlantUML → 详细变更 → 组装

### 4.2 代码化反问(关键)

CC 注意到用户提了"决策分支"(可能软化),主动反问:
> "决策分支能否明确化?是'如果 N=1 → 步骤 6,否则 → 步骤 7'这种确定性逻辑,还是需要 LLM 推理?"

用户答:确定性的 if/else,不需要 LLM。

### 4.3 输出 brief

`01_requirement_brief.md`(约 200 行,5W1H 结构化):

```markdown
# 组件间流程设计 Skill — 需求简报

> **版本**: 1.0.0
> **创建时间**: 2026-07-10 14:00:00

## What
- 输入:`${需求工作目录}/req_design_document.md` + 用例名 + 子系统名
- 处理:11 步流水线
- 输出:`${需求工作目录}/子系统设计/${用例名}_${子系统名}_子系统流程设计结果.md`

## Why
把子系统间协作流程细化为子系统内部组件间协作流程,生成组件间交互时序表 + PlantUML 时序图 + 组件详细变更内容。

## Who
5G NR 基站设计人员(做特性域变更分析时调用)

## Where
- 输入:`${需求工作目录}/req_design_document.md`
- 知识库:`consume_lib/`(子系统间接口文档 + 组件库文档 + 组件间接口文档)
- 输出:写入 `req_design_document.md` 的对应用例章节

## When
做"特性域变更分析"时,组件变更分析完成后调用

## How
11 步确定性流水线(无 LLM 推理):
1. 读组件变更分析 → 过滤用例+子系统 → N 条记录
2. 读子系统间流程设计 → 提取 3 素材(交互时序表/PlantUML/详细变更)
3. 过滤子系统间交互时序表 → 仅当前子系统 → V1
4. 查询子系统间接口 → 转换组件引用 → V2
5. 决策分支:N=1 → 步骤 6, N>1 → 步骤 7
6. 单变更直插
7. 多变更:知识收集 + 依赖分析 + 消息插入
8. 变更描述补全 + 完整性收尾
9. 生成 PlantUML 时序图
10. 生成组件详细变更内容
11. 组装 + 写入 + 校验

## 关键决策(代码化导向)
- **产物形式**:代码化 Skill (Plugin 形态)
- **决策分支**:确定性 if/else,无 LLM
- **异常处理**:用退出码(2/3/4/...) + stderr
- **LLM 断点**:仅在步骤 7(多变更依赖分析)需要 LLM,共 1 个断点
```

CC 展示 brief,问"是否进入阶段 2"。用户答:确认。

更新 `state.json`:
```json
{
  "completed_stages": [1],
  "current_stage": 1
}
```

---

## 5. Step 5:阶段 2 — 规格说明书生成

CC 调 `specification-writer-agent`(传入 `01_requirement_brief.md` + 空 expert-guidance)。

### 5.1 Agent 输出

`02_skill_spec.md`(约 700 行,16 章节结构)生成完成。关键片段:

```markdown
# 组件间流程设计 Skill 规格说明书

> **版本**: 1.0.0
> **状态**: 待评审
> **定位**: 将子系统间协作流程细化为子系统内部组件间协作流程,生成组件间交互时序表、PlantUML 时序图及组件详细变更内容。

---

## 3. 执行流程总览

```
步骤 1: 读取组件变更分析 → 按 ${用例名称} + ${子系统名称} 筛选 → 得 N 条变更记录
步骤 2: 读取子系统间流程设计 → 提取三个素材
步骤 3: 过滤子系统间交互时序表 → 仅保留涉及 ${子系统名称} 的行 → V1
步骤 4: 逐行查询子系统间接口文档 → 转换组件引用 → V2
步骤 5: 决策分支
         ├─ N = 1 ─→ 步骤 6(单变更直插)
         └─ N > 1 ─→ 步骤 7(多变更分析)
步骤 8: 变更描述补全 → 消除所有"待补充"/"业务流待定" → V3(最终版)
步骤 9: 基于 V3 生成 PlantUML 时序图
步骤 10: 基于 V3 生成组件详细变更内容
步骤 11: 组装三步产物 → 写入 req_design_document.md → 最终校验
```

> **关键约束**:步骤 1→2→3→4→5→(6|7)→8→9→10→11 必须顺序执行,不可跳过。

---

## 4. 步骤 1:读取组件变更分析,获取待处理变更行

### 4.1 操作
1. 打开 `${需求工作目录}/req_design_document.md`
2. 定位到「统域变更分析」→「组件变更分析」章节
3. 读取组件变更分析表格的全部行
4. 筛选:`行.用例 == ${用例名称}` 且 `行.子系统 == ${子系统名称}`
5. 筛选结果记入 `${组件变更记录集}`,行数记为 **N**

### 4.2 前置条件
- `req_design_document.md` 存在
- 包含「统域变更分析」章节

### 4.3 输出
- `${组件变更记录集}`(N 条)
- N 用于步骤 5 分支决策

### 4.4 校验规则
- N > 0(否则抛"未找到组件变更记录")

### 4.5 异常处理
| 异常场景 | 严重性 | 代码化处理方式 |
|---------|--------|---------------|
| 文件不存在 | FATAL | 退出码 2 + stderr 输出路径 |
| 表格解析失败 | ERROR | 退出码 3 + diff 输出 |
| N == 0 | WARNING | 退出码 0 + warning 到日志 |

**代码化属性**:🟢 纯脚本可做(Python 30 行实现)
**对应脚本**:`scripts/step1_load_changes.py`(阶段 4 拆分)
```

### 5.2 代码化属性标注(核心创新)

11 个步骤的代码化属性:

| 步骤 | 名称 | 代码化属性 | 备注 |
|------|------|----------|------|
| 1 | 读取组件变更 | 🟢 纯脚本 | 文件读取+过滤 |
| 2 | 读取子系统间流程 | 🟢 纯脚本 | 文件读取+章节提取 |
| 3 | 过滤时序表 | 🟢 纯脚本 | 表格过滤 |
| 4 | 查询接口+转换 | 🟢 纯脚本 | 文档查询+字符串处理 |
| 5 | 决策分支 | 🟢 纯脚本 | if/else |
| 6 | 单变更直插 | 🟢 纯脚本 | 表格插入 |
| 7 | 多变更依赖分析 | 🔴 必须 LLM | 语义判断+依赖分析 |
| 8 | 变更描述补全 | 🟡 需 LLM 辅助 | 命名规则生成 |
| 9 | 生成 PlantUML | 🟢 纯脚本 | 模板渲染 |
| 10 | 生成详细变更 | 🟢 纯脚本 | 模板渲染 |
| 11 | 组装+写入+校验 | 🟢 纯脚本 | 文件操作 |

**统计**:
- 🟢 步骤:9 / 11(82%) ✅ 超过 50% 阈值
- 🟡 步骤:1 / 11(9%)
- 🔴 步骤:1 / 11(9%)
- LLM 断点:1 个(步骤 7)

### 5.3 16 项硬约束自检

CC 调薄壳 Python 校验:
```bash
python3 scripts/commands/skill_create.py validate \
  --output-dir /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000 \
  --skill-name inter-component-flow-design
```

**输出**:
```
[OK] 阶段 2 规格说明书: .../02_skill_spec.md
[SKIP] 阶段 4 工程化 Skill: 目录不存在
[RESULT] 阶段 2 校验通过(阶段 4 跳过,因未到阶段 4)
```

更新 `state.json`:
```json
{
  "completed_stages": [1, 2],
  "current_stage": 2
}
```

---

## 6. Step 6:阶段 3 — 单体 Python 实现

CC 调 `code-implementer-agent`(传入 `02_skill_spec.md`)。

### 6.1 Agent 输出

`03_monolithic_impl.md`(约 1000 行,单文件)生成完成。关键片段:

```python
class ComponentFlowDesigner:
    """组件间流程设计 单体实现"""

    def __init__(self, workspace, use_case, subsystem):
        self.workspace = Path(workspace)
        self.use_case = use_case
        self.subsystem = subsystem
        self.state = {}

    # 🟢 步骤 1: 纯代码实现
    def step_1_load_changes(self) -> StepResult:
        """读取组件变更分析,获取待处理变更行

        对应 spec §4
        前置: req_design_document.md 存在
        输出: self.state["changes"]
        校验: N > 0
        """
        try:
            doc_path = self.workspace / "req_design_document.md"
            if not doc_path.exists():
                return StepResult(
                    step_num=1, success=False,
                    error=f"文件不存在: {doc_path}",
                    error_code=EXIT_FILE_NOT_FOUND,
                )
            content = doc_path.read_text(encoding="utf-8")
            changes = self._parse_changes_table(content)
            self.state["changes"] = changes
            return StepResult(step_num=1, success=True, output=changes)
        except Exception as e:
            return StepResult(
                step_num=1, success=False, error=str(e),
                error_code=EXIT_PARSE_ERROR,
            )

    # 🟢 步骤 2-6,9-11: 同样纯代码实现
    def step_2_load_subsystem_flow(self): ...
    def step_3_filter_timing_table(self): ...
    # ...

    # 🔴 步骤 7: TODO 标记
    def step_7_multi_change_analysis(self) -> StepResult:
        """多变更记录—依赖分析(对应 spec §10)

        涉及 LLM 推理,stage4 会在此处拆分为独立脚本 + LLM 断点
        """
        # TODO: LLM 断点
        # 当前阶段: 用 mock 实现演示
        mock_response = self._mock_llm_inference()
        self.state["multi_change_result"] = mock_response
        return StepResult(step_num=7, success=True, output=mock_response)

    # 🟡 步骤 8: 用 prompt 模板占位
    def step_8_complete_descriptions(self) -> StepResult:
        """变更描述补全(对应 spec §11)

        需 LLM 辅助(stage4 拆分)
        """
        # 此步骤在 stage4 会拆分为独立脚本 + 简单 LLM 推理
        mock = self._mock_description_fill()
        self.state["completed"] = mock
        return StepResult(step_num=8, success=True, output=mock)
```

### 6.2 语法检查

```bash
python3 -m py_compile 03_monolithic_impl.md
# [OK] 语法正确
```

### 6.3 mock 试跑

```bash
python3 03_monolithic_impl.md --workspace /tmp/test_workspace --use-case test --subsystem SPA
# [STEP 1] 读取组件变更
# [STEP 2] 读取子系统间流程
# ...
# [STEP 11] 组装最终输出
# [DONE] 所有步骤完成(使用 mock LLM 响应)
```

更新 `state.json`:
```json
{
  "completed_stages": [1, 2, 3],
  "current_stage": 3
}
```

---

## 7. Step 7:阶段 4 — 工程化 Skill 生成

CC 调 `skill-scaffolder-agent`(传入 `02_skill_spec.md` + `03_monolithic_impl.md`)。

### 7.1 拆分映射(先于生成)

scaffolder-agent 先写 `stage4_split_mapping.md`,列出"阶段 3 方法 → 阶段 4 脚本"映射:

| 阶段 3 方法 | 阶段 4 脚本 | 备注 |
|----------|----------|------|
| `step_1_load_changes` | `scripts/step1_load_changes.py` | 🟢 纯代码 |
| `step_2_load_subsystem_flow` | `scripts/step2_load_subsystem_flow.py` | 🟢 纯代码 |
| `step_3_filter_timing_table` | `scripts/step3_filter_timing_table.py` | 🟢 纯代码 |
| `step_4_convert_component_ref` | `scripts/step4_convert_component_ref.py` | 🟢 纯代码 |
| `step_5_decision_branch` | (无需独立脚本,在 run.py 中实现) | 🟢 纯代码 |
| `step_6_single_change_insert` | `scripts/step6_single_change_insert.py` | 🟢 纯代码 |
| `step_7_multi_change_analysis` | `scripts/step7_multi_change_analysis.py` | 🔴 LLM 断点(对应 step7-analysis-rules.md) |
| `step_8_complete_descriptions` | `scripts/step8_complete_descriptions.py` | 🟡 简单 LLM |
| `step_9_generate_plantuml` | `scripts/step9_generate_plantuml.py` | 🟢 纯代码 |
| `step_10_generate_detail_changes` | `scripts/step10_generate_detail_changes.py` | 🟢 纯代码 |
| `step_11_assemble_output` | `scripts/step11_assemble_output.py` | 🟢 纯代码 |

### 7.2 生成的目录结构

```
04_skill_dir/inter-component-flow-design/
├── SKILL.md
├── scripts/
│   ├── run.py                                # 主控(LLM 断点 + --resume)
│   ├── step1_load_changes.py                 # 🟢
│   ├── step2_load_subsystem_flow.py          # 🟢
│   ├── step3_filter_timing_table.py          # 🟢
│   ├── step4_convert_component_ref.py        # 🟢
│   ├── step6_single_change_insert.py         # 🟢
│   ├── step7_multi_change_analysis.py        # 🔴(LLM 断点)
│   ├── step8_complete_descriptions.py        # 🟡
│   ├── step9_generate_plantuml.py            # 🟢
│   ├── step10_generate_detail_changes.py     # 🟢
│   └── step11_assemble_output.py             # 🟢
├── references/
│   ├── output-schema.md                      # 输出格式规范
│   └── step7-analysis-rules.md               # LLM 断点契约(🔴)
└── templates/
    └── output-template.md                    # 最终产物模板
```

### 7.3 LLM 断点协议(对标 step4 V2)

`scripts/run.py` 核心:

```python
def need_llm_checkpoint(state_dir: Path, task_id: str, ...):
    """写入任务文件后退出,等待 CC 推理。state_dir 由 run.py 决定(如 .skillx_state/)。"""
    task_path = state_dir / f"llm_task_{task_id}.json"
    task_path.write_text(json.dumps({...}, ensure_ascii=False, indent=2))
    print(f"[LLM-{task_id}] 需要大模型推理")
    print(f"  任务文件: {task_path}")
    sys.exit(0)  # 非错误退出

def resume_with_response(task_id: str, response: dict):
    """CC 推理后,从 llm_response 读取响应,继续执行"""
    ...
```

`references/step7-analysis-rules.md` 核心(含 JSON Schema):

```markdown
# 步骤 7 LLM 推理规则

> **对应 spec §10**
> **代码化属性**:🔴 必须 LLM 推理
> **LLM 断点**:🧠 LLM-B

## 输出契约(严格 JSON Schema)

\`\`\`json
{
  "type": "object",
  "properties": {
    "insertions": {"type": "array", "items": {...}},
    "row_updates": {"type": "array"},
    "linkage_changes": {"type": "array"}
  },
  "required": ["insertions", "row_updates", "linkage_changes"]
}
\`\`\`
```

### 7.4 8 项目录骨架自检

CC 调薄壳 Python:
```bash
python3 scripts/commands/skill_create.py validate \
  --output-dir /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000 \
  --skill-name inter-component-flow-design
```

**输出**:
```
[OK] 阶段 2 规格说明书: .../02_skill_spec.md
[OK] 阶段 4 工程化 Skill: .../04_skill_dir/inter-component-flow-design
[RESULT] 全部校验通过
```

更新 `state.json`:
```json
{
  "completed_stages": [1, 2, 3, 4],
  "current_stage": 4
}
```

---

## 8. Step 8:出最终报告

CC 写 `final_report.md`,关键内容:

```markdown
# 组件间流程设计 Skill 创建完成报告

## 阶段产物

| 阶段 | 产物 | 路径 | 大小 |
|------|------|------|------|
| 1 | 需求简报 | 01_requirement_brief.md | 4 KB |
| 2 | 规格说明书 | 02_skill_spec.md | 25 KB |
| 3 | 单体 Python | 03_monolithic_impl.md | 38 KB |
| 4 | 工程化 Skill | 04_skill_dir/inter-component-flow-design/ | 13 files |

## 自检结果

### 16 项硬约束清单(阶段 2)
- ✅ 含 16 章节
- ✅ §1.1/1.2/1.3 三个表格
- ✅ §2 核心概念 6 类
- ✅ §3 执行流程图
- ✅ §4~§N 步骤详述 11 个,每个含 5 字段
- ✅ 每个步骤标注代码化属性(🟢×9 / 🟡×1 / 🔴×1)
- ✅ 🟢 占比 82% > 50%
- ✅ 附录 A 输出格式规范
- ✅ 附录 B 异常处理矩阵 4 行
- ✅ 附录 C 术语速查 7 项
- ✅ 全文无软化措辞
- ✅ 全文无绝对路径
- ✅ 1 个 LLM 断点标记(🧠)
- ✅ 步骤数 11 ≥ 3
- ✅ 无循环引用

### 8 项目录骨架(阶段 4)
- ✅ SKILL.md 含 frontmatter
- ✅ SKILL.md description 三要素
- ✅ scripts/ 含 run.py(`--help` 可执行)
- ✅ references/ 含 output-schema.md
- ✅ templates/ 含 output-template.md
- ✅ step7-analysis-rules.md 含 JSON Schema
- ✅ scripts/ 共 11 个(≥ spec 步骤数 11)
- ✅ 目录结构与 step4 V2 一致

## 下一步建议(任选)

### A. 静态打磨(推荐)
/skill_optimize --skill-path /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000/04_skill_dir/inter-component-flow-design/SKILL.md \
  --expert-guidance "5G NR 基站设计领域的代码化要求"

### B. 结构层重构
/skill_refactor --skill-path /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000/04_skill_dir/inter-component-flow-design/SKILL.md

### C. 评测驱动拉满（推荐简化入参）
/skill_evolve --skill-path /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000/04_skill_dir/inter-component-flow-design/SKILL.md \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'

# 纯 Python 评测脚本(明确"非 slash command",跳过 wrap/extract/warn)
/skill_evolve --skill-path /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000/04_skill_dir/inter-component-flow-design/SKILL.md \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-sh 'python3 run_pipeline.py --req-id RAN-3404224 --activity 需求分析 --sub-activity 用户需求分析'

### D. 直接试跑
cd /media/vdb/skillx-alpha/evolution_workspace/skill_create_20260710_140000/04_skill_dir/inter-component-flow-design && python3 scripts/run.py --help
```

---

## 9. 对比与总结

### 9.1 与手工方法论产物对比

| 维度 | 手工方法论 | `/skill_create` 自动化 | 差异 |
|------|----------|---------------------|------|
| 总耗时 | 数小时~数天(人工) | 10~30 分钟(LLM) | 节省 80%+ |
| spec 行数 | 700 行 | 700 行(等价) | 内容等价,文字略不同 |
| 步骤代码化属性 | 未标注 | 🟢×9 / 🟡×1 / 🔴×1 | **新增维度** |
| 阶段 3 单体 | 1100 行 | 1000 行(略精简) | 等价 |
| 阶段 4 脚本数 | 9 个 + run.py | 11 个 + run.py | 更细化(每步独立) |
| 硬约束校验 | 人工 review | 16 项 + 8 项自动校验 | **新增自动化** |
| LLM 断点契约 | 在 step4 V2 中手工写 | 16 项硬约束 + references/ 自动生成 | **更严格** |

### 9.2 与代码化skill制作 目录对比

```
代码化skill制作/  (手工版,33 文件)
├── step1：组件间流程设计-方案.md
├── step2：组件间流程设计-Skill规格说明书.md
├── step3：组件间流程设计-代码实现.md
└── step4：组件间流程设计V2/  ← 这是最终产物
    ├── SKILL.md
    ├── scripts/  (10 个 Python 脚本)
    ├── references/  (7 个 .md)
    └── templates/

skill_create_20260710_140000/04_skill_dir/inter-component-flow-design/  (自动化版)
├── SKILL.md
├── scripts/  (11 个 Python 脚本)
├── references/  (2 个 .md,可按需扩展)
└── templates/
```

**关键差异**:
- 自动化版**每个 spec 步骤独立一个脚本**(stage4 拆分忠实于 stage3 主类方法),更彻底
- 自动化版**显式标注代码化属性**,驱动脚本拆分决策
- 自动化版**LLM 断点契约必带 JSON Schema**,减少运行时错误
- 自动化版**支持 `--start-stage N` 恢复**,断点可继续

### 9.3 实战结论

`/skill_create` 命令**成功封装**了"代码化 Skill 制作"4 步方法论:

1. ✅ **代码化精神贯穿**:阶段 1 主动反问、阶段 2 标 🟢🟡🔴、阶段 3 标 🟢 纯代码、阶段 4 拆分忠实于主类
2. ✅ **LLM 断点协议保留**:对标 step4 V2 的 `--resume` + 任务/响应 JSON 文件
3. ✅ **自动化校验**:16 项硬约束 + 8 项目录骨架自检,失败立即反馈
4. ✅ **可恢复性**:state.json 支持 `--start-stage N` 断点续跑
5. ✅ **薄壳 + CC 编排**:不强行套用 orchestrator,保持 skill_refactor 的设计模式一致性

---

## 10. 后续改进方向

| 改进点 | 优先级 | 说明 |
|-------|--------|------|
| 加入 stage4 拆分的"反 LLM 滥用"二次检查 | 中 | 对标 stage2 硬约束,确保 stage4 不引入不必要的 LLM 调用 |
| 加入 stage3 → stage4 的"拆分忠实度"指标 | 低 | 计算"主类方法数 vs 独立脚本数"比例,过低时报警 |
| 支持 multi-skill 批量创建 | 低 | 当前是单 Skill 模式,未来支持"同时创建 3 个相关 Skill" |
| 集成 `/skill_optimize` 自动触发 | 低 | stage4 完成后自动跑一次轻量优化(默认 dry-run) |

---

## 11. 关联文档

- **本命令契约**:`commands/skill_create.md`
- **薄壳 Python**:`scripts/commands/skill_create.py`
- **Subagent 契约**:
  - `agents/specification-writer-agent.md`
  - `agents/code-implementer-agent.md`
  - `agents/skill-scaffolder-agent.md`
- **手工方法论**:`/media/vdb/skillx-alpha/代码化skill制作/`
- **参考案例**:`docs/重构案例-d7bcf0da-Skill组件间流程设计.md`(本案例的"重构"对照)
