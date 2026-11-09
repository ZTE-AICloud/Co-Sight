# 代码化 Skill 制作规范(内置默认规范)

> **目的**:本规范是 `/skill_create` 命令下 3 个 subagent 的**默认行为约束**,**无需用户通过 `--expert-guidance` 传入**。用户传 `--expert-guidance` 仅用于补充特殊约束,不会覆盖本规范。
>
> **适用范围**:任意业务领域的 Skill 制作(不仅限于"组件间流程设计"案例)。

---

## 1. 代码化精神(Code-First,最高优先级)

> **核心原则**:**能写代码就别让 LLM 推理**。LLM 仅用于"无法用规则穷举"的语义推理环节。

| 决策点 | 代码化方案 | LLM 方案 |
|--------|----------|----------|
| 输入处理 | **直接复制** `--requirement @file.md` 到 `01_<原文件名>.md` | ❌ 禁止重写/整理原文件 |
| 需求澄清 | AskUserQuestion 结构化表单 | ❌ 不允许 LLM 自由发挥 |
| 规格说明书 | 16 章节模板 + 字段强类型(表格/JSON Schema) | 仅用于"语义填充" |
| 单体实现 | Python dataclass + 主类(确定性逻辑) | 仅标记"无法代码化"的点 |
| 工程化 | scripts/*.py(确定性) + run.py 编排 | LLM 断点位置在 spec 中显式标注 |

## 1.5 输入文件处理(用户原文件忠实保留)

**产物约定**:无论 `--requirement` 是 `@file.md` 还是自然语言,**阶段 1 产物统一为 `01_xxx.md`**:

| 输入形式 | 阶段 1 产物 | 处理方式 |
|---------|------------|---------|
| `--requirement @<file>.md` | `01_<原文件名>.md`(保留原文件名/扩展名) | **直接复制**原文件到工作区,**不做任何重写/整理/格式化** |
| `--requirement "自然语言..."` | `01_requirement_brief.md`(若需澄清) | 通过 `AskUserQuestion` 澄清后,生成 brief |

**禁止**:
- ❌ 禁止在 spec-writer-agent 输入之前对用户原文件做任何"重写"/"整理"/"格式化"
- ❌ 禁止把 brief 强加给 `@file.md` 输入(原文件已自带完整需求)
- ❌ 禁止 spec-writer-agent 假设输入是 brief 结构(应自主解析任意 markdown)
- ❌ 禁止 framework 假设任何具体文件名/子目录名

## 1.6 中间产物可见性(必须打印到控制台)

**核心要求**:**每个阶段产物生成后,CC 主 Agent 必须通过 Bash `cat` / `head` / `tail` 把产物路径 + 摘要打印到控制台**,让用户实时看到流水线进度。

**强制打印的产物清单**(完整生命周期追踪,含中间制品):

| 阶段 | 产物 | 是否必须存在 | 打印方式 |
|------|------|-------------|---------|
| 阶段 1 | `01_<原文件名>.md`(用户原文件副本) | ✅(@file.md 时) | `wc -l <path>` + `head -10 <path>` |

> ****:init 时**不创建任何阶段 1 占位文件**(避免 @file.md 场景下产生"空占位 + 真实文件"双文件反模式)。阶段 1 产物名由 input 形式决定:@file.md → `01_<原文件名>.md`;自然语言 → `01_requirement_brief.md`。status 子命令动态扫描 `01_*.md` 取最新。
| 阶段 2 | `02_skill_spec.md` | ✅ | `wc -l <path>` + 章节标题列表(`grep -E "^## " <path>`) |
| 阶段 3 | `03_monolithic_impl.md` | ✅ | `wc -l <path>` + Python 代码块统计 + 7 段强制章节验证(文件元信息/依赖声明/LLM 兜底声明/步骤对照表/LLM 兜底说明/限制边界/测试方式) |
| 阶段 4 | `04_skill_dir/<skill-name>/` 完整目录 | ✅ | `find <path> -type f` 文件清单 + 每个文件 `wc -l` |
| 最终 | `final_report.md` | ✅ | `cat <path>` 全文 |

**01 brief 的存在性规则**(阶段 1 产物,无论 input 形式都涉及):
- ❌ **禁止**当 `--requirement @file.md` 时跳过 01 产物留痕(用户原文件已挪,01 仍必须存在,可标注"无需澄清"或简化为 5W1H 摘要)
- ✅ 01 brief 的目的是**留痕 CC 工作**:用户提问了什么、反问了什么、决策了什么
- ✅ 若确实无需澄清,01_requirement_brief.md 内容可以是 `# 无澄清需求 + 简短理由 + 直接进入阶段 2`

**禁止**:
- ❌ 禁止"静默"生成产物(只写文件不打印)
- ❌ 禁止只打印路径不打印内容(`echo "OK"` 之类无效摘要)
- ❌ 禁止跳过 01 brief 留痕(即使是"无需澄清"也必须有留痕文件)
- ✅ 每次打印至少包含:文件路径 + 大小/行数 + 内容预览(head -N 或 cat)

---

## 2. 步骤代码化属性标注(强制)

**每个 spec 步骤必须标注 3 个属性之一**:

| 属性 | 判定标准 | 实现方式 |
|------|---------|---------|
| 🟢 **纯脚本可做** | 输入/输出结构化 + 逻辑可纯代码表达 + 异常可代码化 | Python 纯代码 |
| 🟡 **需 LLM 辅助** | 逻辑基本确定但需规则匹配/命名生成 | prompt 模板 + 简单校验 |
| 🔴 **必须 LLM 推理** | 涉及语义判断/依赖分析/NLU | LLM + 充分上下文 + JSON Schema 契约 |

**硬约束**:
- 🟢 步骤占比 ≥ 50%(代码化导向,大部分步骤应该是纯脚本)
- 每个 🟡/🔴 步骤末尾必须有 `**LLM 断点**:` 行 + `**Prompt 模板**:` 行
- 每个 LLM 断点必须在 references/ 中对应一个 `stepN-rules.md`(顶部含 JSON Schema)

---

## 3. LLM 断点协议(对标 step4 V2,通用)

**协议**(框架只规定契约,不规定路径):
- run.py 检测到需要 LLM 推理时,**由 run.py 自行决定**断点文件的存放路径,并在 SKILL.md 中显式告知调用方
- 退出(返回码 0 + 提示)
- CC 读取任务文件,推理后写入**对应位置的**响应文件
- CC 调 `run.py --resume --llm-response <path>` 继续执行

> **本规范对目录/路径完全保持沉默**:
> - ❌ 禁止 framework 层面规定具体目录名(无论 `middle_content/` / `.skillx_state/` / `state/` / 任何其他)
> - ❌ 禁止 framework 层面举例"通常在 X 目录"——这种"举例"也会耦合建议,业务方应自行决定
> - ✅ run.py 实现时可选择:落盘到 `${workspace}/` 下某隐藏目录、不落盘(全内存传参)、或任何其他方式,**只要在生成的 SKILL.md 中告知调用方**

**响应文件契约**:
- 每个 `references/llm_{task_id}_{business_meaning}.md` 顶部**强制含响应 JSON Schema**
- 字段命名、必填项、枚举值必须与 spec 附录 B(异常处理矩阵)对齐
- Schema 验证失败必须给明确错误信息(指出哪个字段缺失/类型错误)

**LLM 断点文件名规则(强制,业务含义自解释)**:
- 契约文档:`llm_{task_id}_{business_meaning}.md`,其中 `business_meaning` 是该 LLM 任务的业务摘要(英文短横线短语)
- 应用脚本:`stepN_apply_{business_meaning}.sh` 或 `stepN_apply_{business_meaning}_{modifier}.sh`(去 `_llm_X` 后缀,加 modifier 区分场景)
- 跨步骤复用的 LLM 任务共享同一契约文件(如步骤 6/7 共用 `llm_a_component_dependency_analysis.md`)
- ❌ 反例:`step4-rules.md`、`stepN_apply_llm_X.sh`(看不出任务语义)
- ✅ 正例:`llm_a_component_dependency_analysis.md`、`step4_apply_interface_direction.sh`

**断点协议代码骨架**(通用,**state_dir 由调用方注入,不在 framework 中假设具体路径**):
```python
def write_llm_task(state_dir: Path, task_id: str, task_type: str, ...) -> None:
    """写入 LLM 任务文件并退出。state_dir 由 run.py 注入,本函数不做任何路径假设。"""
    task_file = state_dir / f"llm_task_{task_id}.json"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "task_type": task_type,
        "prompt_template_path": f"references/step{N}-rules.md",
        "response_expected": str(state_dir / f"llm_response_{task_id}.json"),
        "context": ...,
    }
    task_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[LLM-{task_id}] 需要大模型推理")
    print(f"  任务文件: {task_file}")
    print(f"  请推理后将结果写入: {payload['response_expected']}")
    sys.exit(0)  # 非错误退出
```

---

## 3.5 LLM 响应 schema 多模板组合原则,根治"字段不全")

**核心问题**:此前 LLM 断点常只声明 `insertions[]` 单模板,导致 revision loop 上 LLM 无法回填存量 + 识别联动变更。本节强制 **多模板组合**。

**v1.2.0 更新**:`incremental_modification_v2` 模板(4 字段必含)被 `minimal_core_combo`(3 字段必含)替代。理由:`fallback_markers` 在 LLM 推理质量良好时常为 `[]`,反而干扰阅读;`naming_decisions` 在多数场景下 LLM 直接在 `change_desc` 里命名更自然。3 字段核心 + 2 字段可选是更合理的默认。

**规则**(通用,不绑定特定业务):

| 业务模式 | 必含最小模板集合 | 推荐模板 | 来源 |
|---------|----------------|---------|------|
| `flow_design`(综合 LLM 断点,默认) | `insertions` + `row_updates` + `linkage_changes` | `minimal_core_combo`(3 字段) | `knowledge/llm_breakpoint_templates.json` |
| `flow_design`(综合 LLM 断点,需主动命名) | 3 字段 + `naming_decisions` | `core_3_plus_optional`(3+1 字段) | 同上 |
| `flow_design`(综合 LLM 断点,需显式兜底) | 3 字段 + `fallback_markers` | `core_3_plus_optional`(3+1 字段) | 同上 |
| `flow_design`(综合 LLM 断点,全功能) | 3 字段 + `naming_decisions` + `fallback_markers` | `core_3_plus_optional`(3+2 字段) | 同上 |
| `flow_design`(规则匹配 LLM 断点) | `fixes` 单模板即可 | `fixes` | 同上 |
| 其他业务模式 | 自由文本(`content` / `sections[]` / `entities[]` 等)| 不限制 | — |

**禁止**:
- ❌ flow_design 综合 LLM 断点只声明 `insertions` 单模板
- ❌ 自创字段名(如 `messages[]` / `entries[]` / `result[]` 等)
- ❌ `properties` 中只声明 1 个 keys(单模板是反模式 #3)
- ❌ 强制 4 字段必含(incremental_modification_已弃用)— 改用 minimal_core_combo 或 core_3_plus_optional

**字段名白名单**:`knowledge/llm_breakpoint_templates.json` 中声明的 `template_id_whitelist`(insertions / row_updates / linkage_changes / naming_decisions / fixes / fallback_markers)。校验脚本 `scripts/commands/skill_create.py check-completeness` 强制比对。

**LLM 契约文档命名**:起推荐 `llm_{task_id}_{business_meaning}.md`(见 `agents/skill-scaffolder-agent.md` §4a.5)。

---

## 4. 异常处理统一规范(代码化导向)

**附录 B 异常处理矩阵必填项**:
- 每行含 3 列:异常场景 / 严重性 / **代码化处理方式**(退出码或异常类型)
- 严重性枚举:FATAL(进程终止) / ERROR(子任务失败) / WARNING(可继续) / INFO(信息)
- 退出码分配:
  - 0 = 成功
  - 1 = 通用错误
  - 2 = 文件不存在
  - 3 = 解析失败
  - 4 = 外部依赖失败
  - 10 = LLM 断点退出(非错误,需 CC 推理后 --resume)
  - 11+ = 业务特定错误(按 spec 附录 B 定义)

**禁止使用**:
- ❌ "建议灵活处理"(软化措辞)
- ❌ "可能需要"(软化措辞)
- ❌ "根据情况"(软化措辞)
- ❌ 静默 try/except(吞掉错误)

---

## 5. 产物目录结构(对标 step4 V2 通用化骨架)

**标准结构**:
```
{skill-name}/
├── SKILL.md                    # 入口
├── scripts/                    # 独立 Python 脚本
│   ├── run.py                  # 主控(LLM 断点 + --resume)
│   ├── step{N}_*.py            # 每个 spec 步骤一个独立脚本
│   ├── validate_*.py           # 校验脚本(可选)
│   └── *.py                    # 辅助脚本(按需)
├── references/                 # LLM 断点契约 + 规则文档(**严禁全量复制外部知识库**)
│   ├── output-schema.md        # 输出格式规范
│   ├── step{N}-rules.md        # 每个 LLM 断点的契约(含 JSON Schema)(注:起推荐 `llm_{task_id}_{business_meaning}.md`)
│   └── <其他轻量规则子目录>/   # 仅限契约性文档,单目录总大小 ≤ 1 MB
└── templates/
    └── output-template.md      # 最终产物模板
```

**references/ 严格约束(通用, 新增,根治知识库被全量复制)**:

| 规则 | 原因 |
|------|------|
| ✅ 允许:契约文件(output-schema / stepN-rules / 自定义规则文档) | 供 CC 在 LLM 断点处 Read |
| ❌ 禁止:`cp -r` 复制整个外部知识库到 references/ | 知识库常达 GB 级且会随业务演进,Skill 包必须**轻量化** |
| ✅ 正确做法:在 SKILL.md 描述外部知识库**绝对路径**,由 run.py 通过 CLI 参数 `--consume-lib <path>` 运行时按需读取 | 引用而非打包,Skill 包可独立版本化 |
| ❌ 禁止:任何单目录 > 1 MB 或单文件 > 200 KB 的"参考资料"进入 references/ | 防呆兜底(覆盖度统计 P0-7 会校验) |

**目录命名约定**:
- `{skill-name}` 英文短横线命名(如 `inter-component-flow-design`)
- 步骤脚本前缀 `step{N}_`,N 从 1 开始
- 校验脚本前缀 `validate_`

---

## 6. SKILL.md frontmatter 三要素(强制)

**frontmatter 必填字段**:
```yaml
---
name: <skill-name>                    # 英文短横线
version: "<x.y.z>"                    # 语义化版本
description: |
  <做什么 — 1 句话>
  <触发场景 — 1 句话>
  <触发词 — 逗号分隔的关键词列表>
allowed-tools:                         # 必需的工具列表
  - Bash
  - Read
  - Write
---
```

**description 三要素说明**:
- **做什么**:1 句话说明 Skill 功能(必含"做什么"的动词)
- **触发场景**:1 句话说明何时使用
- **触发词**:逗号分隔的关键词列表,方便触发器匹配

---

## 6.5 references 复用源 + scripts 脚本语言规范)

### 6.5.1 references 复用源(GB 级防呆)

业务背景知识库、消费类库等可能 GB 级的资源,**严禁 `cp -r` 复制到 Skill 包的 `references/`**:

- ✅ **runtime 注入**:通过 `--consume-lib <abs_path>` 参数在 SKILL.md / run.py 中显式声明
- ✅ **小文件复制**:复用源(`< 1 MB`,如规则类文件)可全部复制到 Skill 包 `references/<category>/`
- ❌ **GB 级打包**:禁止整个目录(> 1 MB)用 `cp -r` 复制到 Skill 包

**框架校验**:`validate_skill_scaffold` P0-7 防呆 — references/ 单目录 > 1 MB 或单文件 > 200 KB → FAIL。

### 6.5.2 scripts 脚本语言技术栈声明(覆盖默认 Python)

Expert-guidance 可显式声明 Skill 的脚本语言,**覆盖 framework 默认 Python**:

| 声明 | 含义 |
|------|------|
| `expert-guidance` 含 "scripts 以 sh 代码为主" | 拆分为 `.sh` 脚本,主控 `run.sh`,LLM 响应经临时 JSON 文件 |
| `expert-guidance` 含 "scripts 以 py 代码为主" | 拆分为 `.py` 脚本,主控 `run.py`(默认)|
| 无显式声明 | 走 framework 默认 Python |

**框架校验适配**:`validate_skill_scaffold` 第 432 行的 `scripts/run.py` 硬编码改为读取 scaffold metadata 中的 `script_extension`(默认 `py`,声明 sh 时改读 `scripts/run.sh`)。

---

## 7. 中间产物目录(framework 完全不规定)

**framework 对中间产物目录保持完全沉默**:
- ❌ 禁止 framework 推荐/列举/举例任何具体目录名(包括但不限于 `middle_content/` / `.skillx_state/` / `state/` / `.cache/`)
- ✅ run.py 自行决定:落盘隐藏目录 / 落盘普通目录 / 全内存传参 / 不创建任何目录,**都允许**
- ✅ SKILL.md 必须显式告知调用方 run.py 的断点文件存放路径(若存在)

> **设计原则**:framework 规范层对**具体路径完全沉默**——既不强制也不推荐不举例。只有"由 run.py 决定 + SKILL.md 告知"这条不变量。Framework 应对业务完全通用,不耦合任何示例/推荐/历史案例的具体目录名。

---

## 7.5 阻断追溯报告(block_report)与反向同步(update_doc)模式)

### 7.5.1 阻断追溯报告(根治"错误信息丢 stdout 无法追溯")

任何"必须依赖 N 个上游产物才能继续"的步骤都可能触发阻断(如接口文档缺失、子系统不匹配、规则文件缺失等)。阻断时**必须**在业务方显式告知的状态目录下写 `<step_num>_block_report.json`(状态目录由 `run.{py,sh}` 自行决定,**规范完全保持沉默**;`SKILL.md` 必须在"参考文件"或"产物路径"段显式给出实际路径,供调用方读取),结构约定:

```json
{
  "blocks": [
    {
      "timestamp": "T10:23:45",
      "block_type": "missing_interface_doc" | "interface_subsystem_mismatch" | "missing_rule_file" | ...,
      "row_index": 3,
      "direction": "SRC -> TGT",
      "interface_name": "...",
      "interface_doc_path": "...",
      "detail": "业务流变更类型为'修改',接口 X 的文档不存在",
      "suggestion": "请在 path/to/doc.md 创建接口文档,确保发送方=SRC、接收方=TGT"
    }
  ]
}
```

> ** — STATE_DIR 占位符去路径耦合**:原写法用 `${STATE_DIR}` 占位符隐含 framework 假设路径,**改为"由 run 决定 + SKILL.md 告知"**。任何业务方实现可选择落盘隐藏目录(`.skillx_state/`) / 落盘普通目录 / 全内存传递 / 不创建任何目录,**都允许**;只要 `SKILL.md` 在合适位置给出实际路径即可。禁止 framework 层假设具体目录名(包括 `${STATE_DIR}` 这种占位符也视为隐性耦合)。

### 7.5.2 反向同步(update_doc)模式(根治"原需求文档不回写")

LLM 完成 V2 → V3 推进后,**最后一步必须支持** `--update-doc <原文档路径>` 参数:
- 模式:`assemble_output --update-doc <原需求文档.md>` → 在原文档同级目录写入结果文件,或在原文档特定节点追加
- SKILL.md 必须显式调用方式
- 退出码:成功(0) / 写文件失败(2) / update-doc 失败(3)

**适用业务**:任何"LLM 修改产物需回写到原输入文档对应节点"场景(组件间流程设计、需求方案细化、配置生成等)。

### 7.5.3 阻断退出码专用)

| 退出码 | 含义 |
|--------|------|
| 0 | OK |
| 1 | 通用错误(参数缺失 / 写文件失败)|
| 2 | 文件缺失 |
| 3 | 解析失败 / 校验失败 |
| **4** | **外部依赖阻断**(R5 接口文档缺失 / R8 规则缺失 / consume_lib 未注入)|
| 10 | LLM 断点退出 |
| 11-12 | 业务专用(变更数 0 / 过滤后 0 行等)|

---

## 7.6 强制 Explore 验证子步骤,根治"骨架像但跑飞"问题)

> **根因**:`/skill_create` Step 7 阶段 4 工程化拆分时,主 Agent(或 scaffolder)直接生成 .sh/.py 脚本,跳过了"实际行为"端到端验证。`04_skill_dir/组件间流程设计/` 因这个跳步产生 11 个 bug(LLM 断点协议失效、step4 不解析业务流、step6/7 mods 未入最终表、5 项拓扑校验 0/5、change_desc 三段式错误、R8 规则文件未真读等)。
>
> **本节强制**:Step 7 完成后,**必须**用 Explore agent 探查实际产物,把发现的问题作为 Step 8 最终报告的一部分。

### 7.6.1 探查清单(5 项强制)

| # | 探查项 | 检查方法 | 期望 |
|---|--------|---------|------|
| **E1** | 脚本实际行为 | 读每个 .sh 主体(不只读 spec/impl),看它实际做了什么 | 不是只 `cp IN OUT` 的空壳 |
| **E2** | 脚本之间数据流 | 模拟跑 step1~stepN,trace 每个产物被谁读 | `04_*.json` 是否真被 `05_*.sh` 读?`06_*.json` 是否真被 `08_*.sh` 读? |
| **E3** | LLM 断点续跑 | 模拟 LLM 响应(写 mock `llm_response_*.json`),跑 `bash run.sh --resume` | 响应是否真被写回?还是被后续步骤覆盖? |
| **E4** | 中间产物 schema | 读每个 `0N_*.json`,对照 `references/output-schema.md` | 字段是否完整?key 名是否一致? |
| **E5** | LLM 断点协议合规 | `grep -rE "exit 0.*LLM\|LLM.*exit 0" scripts/` | 应为 0 命中(LLM 等待必须 `exit 100`,见 `llm_checkpoint_sentinel_v1.md`) |

### 7.6.2 探查报告模板

```markdown
# Explore 探查报告 — {skill-name}

## 1. 探查概览
- 执行时间: YYYY-MM-DD
- 探查范围: scripts/*.sh + references/*.md + templates/*.md
- 探查 Agent: Explore (read-only)

## 2. 5 项探查结果
- [ ] E1 脚本实际行为: 详细列出每个 .sh 的输入/输出/逻辑核心
- [ ] E2 数据流串通: 用箭头画出 `01_*.json → step1 → 02_*.json → step2 → ... → final_*.md`
- [ ] E3 LLM 断点续跑: 模拟响应 → 跑 --resume → 检查响应是否真应用
- [ ] E4 中间产物 schema: 列出每个 JSON 的实际字段 vs spec 期望
- [ ] E5 LLM 断点协议: grep 模式 + 检查 `run.sh` 主循环(if-else + 100 检测)

## 3. 发现的问题
| # | 严重性 | 位置 | 描述 | 修复建议 |
|---|--------|------|------|---------|
| 1 | CRITICAL | step4_map_handlers.sh | 不解析 biz_if | 三分流 + R8 真读 |
| 2 | CRITICAL | run.sh | exit 0 不被 if ! bash 捕获 | if-else + 100 哨兵 |
| ... | ... | ... | ... | ... |

## 4. 总结
- CRITICAL: N 个
- HIGH: M 个
- LOW: K 个
- 评估: 骨架可交付 / 需修复 / 需返工
```

### 7.6.3 与 Step 8 final_report.md 集成

Step 8 final_report.md 必须包含"Explore 探查报告"链接或嵌入,作为 Skill 质量评估的依据。

```
final_report.md 结构:
- 各阶段产物路径
- 16 项硬约束清单结果
- **8 项目录骨架自检结果**
- **Explore 探查报告(N 个 CRITICAL,M 个 HIGH,K 个 LOW)**
- 下一步建议
```

### 7.6.4 触发哪些通用模式

Step 7 完成后,Explore agent 应主动检查:
- **`llm_checkpoint_sentinel_v1.md`** 协议合规(退出码 100)
- **`patterns/three_bucket_split_v1.md`** 模式应用(分流已知/待LLM/未知)
- **`patterns/topology_validation_v1.md`** 5 项校验
- **`patterns/tri_segment_desc_v1.md`** 三段式 change_desc
- **`patterns/business_flow_fallback_v1.md`** 接口待定兜底

未应用 → 在探查报告中标记为"`missing pattern`"。

### 7.6.5 与 /skill_optimize 的衔接

Explore 探查报告的"问题清单"可直接作为 `/skill_optimize` 的输入,无需主 Agent 重新分析。这样:
- Step 7 + Step 8(本轮)→ 出探查报告
- `/skill_optimize`(后续)→ 针对报告中的问题做静态打磨
- `/skill_evolve`(后续)→ 评测驱动

---

## 8. 拆分映射表(stage4 调试友好)

**`stage4_split_mapping.md` 必须存在**,但**不放在 Skill 目录**:
- ❌ `04_skill_dir/{skill-name}/stage4_split_mapping.md`(污染 Skill 目录)
- ✅ `04_skill_dir/_meta/stage4_split_mapping.md`(辅助元信息子目录)

同样,`stage3_meta.md`(从 impl 提取的文件元信息)也写到 `_meta/`,不进 Skill 目录。

> **🚨 Skill 目录只含可交付物**:SKILL.md + scripts/ + references/ + templates/。
> 所有辅助调试元信息统一放 `_meta/`(以 `_` 前缀标识)。

内容格式:
```markdown
# Stage 4 拆分映射表

| 阶段 3 主类方法 | 阶段 4 独立脚本 | 代码化属性 | LLM 断点 |
|----------------|----------------|----------|---------|
| `step_1_xxx` | `scripts/step1_xxx.py` | 🟢 | — |
| `step_7_xxx` | `scripts/step7_xxx.py` | 🔴 | LLM-A |
| ... |
```

**目的**:便于调试时定位"主类方法 → 独立脚本"的对应关系。

---

## 9. 16 章节规范(规格说明书模板,通用)

**结构**:
```
§1. 输入与输出
  §1.1 输入项表(必填)
  §1.2 读取的文件表(必填)
  §1.3 输出产物表(必填)
§2. 核心概念(≥3 类数据对象,每类含含义/列名/示例/提取规则)
§3. 执行流程总览(步骤图 + 关键约束)
§4~§N. 步骤详述(每个含操作/前置/输出/校验/异常 + 代码化属性)
附录 A. 输出产物格式规范(含模板示例)
附录 B. 异常处理矩阵(≥3 行,代码化处理)
附录 C. 术语速查(≥5 项)
```

---

## 10. 通用化硬约束(必读)

### 10.1 软化措辞禁令

禁止出现(违反 REWORK):
- "建议灵活" / "根据情况" / "可能需要" / "灵活处理"
- 任何带"灵活"二字的措辞

### 10.2 绝对路径禁令

禁止出现(违反 REWORK):
- `/media/vdb/xxx` / `C:\xxx` 等具体路径
- 改用 `${ENV_VAR}/xxx` 或 `Path(__file__).parent / "xxx"` 相对路径

### 10.3 业务专有名词禁令(本规范层面)

本规范本身**完全通用**,不绑定任何具体业务领域。

但 subagent 在生成 spec/impl/skill 时,**业务专有名词从 brief 推断**,不写死:
- 字段名(如"用例名"/"子系统名")从 brief 推断
- 文件名(如"req_design_document.md")从 brief 推断
- 接口协议名(如"SPA"/"MCC")从 brief 推断

---

## 11. 质量门槛(对标 step1-4 案例,通用化)

> 以下数字是**通用化质量门槛**,不绑定具体案例。
> :把"单文件 Python"/"dataclass 数 4~6"/"py_compile"等具体语言假设改为**语言无关度量**。

| 阶段 | 数量门槛 | 备注 |
|------|---------|------|
| 阶段 2 spec | ≥ 800 行(7 必填章节 + 条件章节按 brief 增量) | 11 步骤 + 5 数据对象 + 3 附录 |
| 阶段 2 spec | 步骤数 ≥ 5 | 过少不构成"Skill" |
| 阶段 2 spec | 🟢 步骤占比 ≥ 50% | 代码化导向 |
| 阶段 2 spec | 必填章节 ≥ 7(§1~§N + 附录 A/B/C) | 条件章节按 brief 增量(治"spec 多 35% 字节"反模式) |
| 阶段 3 impl | **主代码块 500~1500 行**(语言无关) | Python=单文件 Python;sh=bash 代码块;其他语言=对应载体 |
| 阶段 3 impl | **数据结构定义数 ≥ spec §2 概念数** | Python=dataclass;sh=jq schema + TSV header;其他语言=对应结构 |
| 阶段 3 impl | step_N 函数/方法数 = spec 步骤数 | 1:1 对应 |
| 阶段 4 Skill | 总文件数 ≥ 15 | SKILL.md + scripts + references + templates |
| 阶段 4 Skill | **scripts 数 ≤ spec 步骤数 + 1 + 3**(含流程类 3 个 validate_*.py 配额) | 主控 run.{py,sh} + N 个 step + 3 validate;严禁 _helper_* / lib_* / utils.*;详见 `validation_norms.md` §scripts 数估算公式 |
| 阶段 4 Skill | references/ 顶层 ≥ 3 | output-schema + ≥1 LLM 契约 + ≥1 其他 |
| 阶段 4 Skill | templates/ ≥ 1 | output-template.md(可含 1 个或多个细分模板) |

**验证手段映射表**(语言无关执行):
| 语言 | 语法检查 | CLI 入口检查 | mock 试跑 |
|------|---------|-------------|---------|
| Python | `python3 -m py_compile` | `python3 <file> --help` | mock workspace 跑通 |
| sh / bash | `bash -n` | `bash <file> --help` | mock workspace 跑通 |
| TypeScript | `tsc --noEmit` | `node <file> --help` | mock workspace 跑通 |
| 其他 | 语言自带 lint | `--help` | mock workspace 跑通 |

### 11.5 flow_design 模式的 5 条抽象设计原则,根治代码化程度低)

> 当 spec/writer 匹配到 `flow_design` 业务模式时,以下 5 条**抽象设计原则**必须显式遵守。
> 每条原则在 spec 中如何**具体落地**由业务决定,框架只规定抽象规则,不规定具体实例。
> 详细说明见 `knowledge/business_patterns.yaml` `flow_design.mandatory_design_principles` 段,
> 具体业务实例见 `norms/flow_design_style_guide.md`(非规范性示例)。

| # | 抽象原则 | 框架自检 grep 模式(用抽象关键词) |
|---|---------|---------|
| 1 | **分类-分支独立处理**:transform 步骤含 N 个类别对应 N 个独立分支处理表 | `grep -E "分支处理\|branch_handling\|分类-分支" spec §4` |
| 2 | **知识结构化提取**:knowledge_collection 步骤含结构化字段提取 + 目标集合过滤 | `grep -E "结构化提取\|结构化字段\|target_comps\|目标集合" spec §4` |
| 3 | **显式输入解析策略**:read 步骤显式声明输入形态 + 解析方法 | `grep -E "解析策略\|input_parsing\|章节定位\|目录扫描" spec §4` |
| 4 | **数据完整性错误阻断**:异常处理矩阵含"关键数据缺失即阻断+写追溯报告" | `grep -E "阻断\|block_report\|追溯报告" spec 附录 B` |
| 5 | **统一 LLM 断点入口**:LLM 断点用 minimal_core_combo 或扩展,各子场景走统一入口 | `grep -E "minimal_core_combo\|统一入口\|统一断点" spec §4` |

**校验脚本**:`scripts/commands/skill_create.py check-completeness` v1.2.0 起强制校验以上 5 项抽象原则。
校验方式:用抽象关键词 grep spec,确认每条原则在 spec 中有显式提及(不要求具体实例)。

**反例(明确禁止,均为反模式)**:
- ❌ 单一默认分支:`if type == "X": do(); else: do_default()` — 抽象原则 1
- ❌ raw dump:`jq -n --rawfile content file.md` — 抽象原则 2
- ❌ 假设未声明的目录结构:`${WORK_DIR}/<未在 brief 提及>/xxx.md` — 抽象原则 3
- ❌ 静默跳过:`if [[ ! -f "${file}" ]]; then continue; fi`(不写阻断报告) — 抽象原则 4
- ❌ 按子场景拆 LLM 断点:N=1 一个 LLM,N>1 另一个 LLM — 抽象原则 5

---

## 12. 实战原则

### 12.1 可执行性第一

**强制验证三件套**(每个阶段产物):
- `python3 -m py_compile <file>` 语法检查
- `python3 <file> --help` CLI 入口检查
- mock 试跑(传 mock workspace,验证 run() 跑通)

### 12.2 通用性优先

业务名词**全部从 brief 推断**,禁止:
- 在契约模板中 hardcode 具体业务名
- 写"req_design_document.md"/"用例名"/"consume_lib"等具体业务名词(除作为反例警告)

### 12.3 可调试性优先

每个阶段产物都**可独立检查**:
- spec 可用 `python3 -m json.tool` 验证 JSON 部分
- impl 可用 mock workspace 跑通
- skill 可用 `python3 scripts/run.py --help` 验证入口

---

## 13. 用户传 `--expert-guidance` 的边界

**仅用于补充本规范未覆盖的特殊约束**,如:
- "所有 Python 脚本必须用 4 空格缩进"(项目代码风格)
- "本场景的 LLM 推理必须在 30 秒内完成"(性能约束)
- "本 Skill 需要兼容 Python 3.7"(兼容性约束)

**禁止用于**:
- ❌ 重写本规范已定义的内容(如"代码化优先")
- ❌ 写死具体业务路径
- ❌ 替换默认 LLM 断点协议

如用户传了与本规范冲突的 `--expert-guidance`,subagent 应**优先遵循本规范**,并在产物中标注"用户指引与默认规范冲突,已采用默认规范"。

---

## 14. 关联文档

- `commands/skill_create.md` — 主命令契约
- `agents/specification-writer-agent.md` — 阶段 2 subagent
- `agents/code-implementer-agent.md` — 阶段 3 subagent
- `agents/skill-scaffolder-agent.md` — 阶段 4 subagent
- `scripts/commands/skill_create.py` — 薄壳 Python
- `docs/skill-create-用例-组件间流程设计.md` — 实战案例(展示本规范如何应用)

---

## 15. 维护说明

**更新原则**:
- 本规范的修改**必须经实战验证**
- 修改后需在实战案例文档中标注"基于规范版本 X.Y"
- 业务方建议通过 `--expert-guidance` 补充而非修改本规范

**版本历史**:
- v1.0.0:初版,基于"组件间流程设计"案例提炼
