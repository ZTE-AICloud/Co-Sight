# flow_design 模式的具体实例风格指南(非规范性)

> **重要声明**:本文件是**非规范性**(non-normative)文档,仅展示"flow_design 业务模式"的**具体业务实例**,
> 用于说明抽象原则在某个具体业务中如何落地。本文件**不**是规范的一部分,业务方在编写自己的 spec/skill 时
> **不应**把本文件的实例当作必须照搬的模板。
>
> 规范请看:
> - `framework_configs/norms/spec_norms.md`(抽象原则)
> - `framework_configs/knowledge/business_patterns.yaml` `flow_design.mandatory_design_principles`(抽象规则)
> - `framework_configs/skill-create-guidelines.md` §11.5(框架级校验)
>
> 本文件是规范之外的"实例参考"。

---

## 抽象原则 vs 具体实例的对应关系

| 抽象原则(规范) | 具体实例(本文件,非规范性) |
|----------------|---------------------------|
| 分类-分支独立处理 | 业务流变更类型三分支(修改/待验证/新增) |
| 知识结构化提取 | 5 类组件知识字段 + 组件间接口双向过滤 |
| 显式输入解析策略 | 从单文件 `req_design_document.md` 内定位章节 + 解析表格 |
| 数据完整性错误阻断 | 接口文档缺失/不一致即阻断退出 + 写阻断报告 |
| 统一 LLM 断点入口 | N=1 与 N>1 走同一断点,auto-insertions 作为 LLM 输入 |

> **关键提醒**:上表中"具体实例"是某次具体业务(flow_design 的一个具体案例:组件间消息流程设计)
> 的实现选择,不是规范的一部分。其他业务方在编写自己的 spec 时,可参考本表的对应关系
> **自行决定**如何把抽象原则落到自己的业务上。

---

## 实例 1:分类-分支独立处理 — "业务流变更类型三分支"

### 抽象原则回顾

> 当 transform 步骤的输入数据含有"分类列",该步骤必须为每个已知类别定义独立的处理分支。

### 具体实例(组件间流程设计业务)

`组件间流程设计` 业务的 transform 步骤涉及"业务流变更类型"列,该列有 3 个已知类别:
- `修改` — 走存量接口文档查询 + 阻断
- `待验证` — 保留原样,等人工
- `新增` — 走规则文件匹配 + LLM 兜底

### 三分支模板示例

| 变更类型 | 处理逻辑 | 是否走 LLM |
|---------|---------|-----------|
| `修改` | 查存量接口文档,提取发送方/接收方;缺失即**阻断退出** + 写 `step{N}_block_report.json` | ❌ |
| `待验证` | 保留原行,**不转换**,留待人工补全 | ❌ |
| `新增` | ① 查规则文件<br>② 规则存在 → 标记 `_pending` 走 LLM-A 匹配<br>③ 规则不存在 → 默认 = 变更组件名 | 部分 |

### 反例(此实例中)

- ❌ `if flow_type == "修改": ... else: ...` 用一个 else 覆盖"待验证"和"新增" — 静默错误
- ❌ 把三分支合并成一个 LLM 调用 — 浪费 LLM 算力,信息损失

---

## 实例 2:知识结构化提取 — "5 字段 + 双向过滤"

### 抽象原则回顾

> knowledge_collection 步骤必须按"结构化字段"提取关键信息,且对"实体间关系"做目标集合过滤。

### 具体实例(组件间流程设计业务)

`组件间流程设计` 业务的 knowledge_collection 步骤提取组件知识时,采用 5 类字段:

| 字段 | 类型 | 提取规则 |
|------|------|---------|
| `responsibility` | string | `## 职责` 段第一行非空文本 |
| `capabilities` | array | `## 组件能力描述` 表格的所有数据行 |
| `business_capability` | string | `## 业务能力描述` 段第一行 |
| `business_flows` | string | `## 业务流` 段第一行 |
| `workflow` | string | 首个 ```plantuml 代码块 |

### 双向过滤示例(组件间接口)

```yaml
# 目标组件集合 = V2 中出现 ∪ 变更记录中的组件
target_comps = {子系统.组件 | V2.rows[*].src/tgt ∪ 变更记录[*].组件}

# 仅保留 sender AND receiver 都在 target_comps 内的接口
if interface.sender in target_comps AND interface.receiver in target_comps:
    emit(interface)
else:
    skip()
```

### 其他业务怎么落地?

> **关键**:5 个字段名(`responsibility`/`capabilities`/...)是**本业务的实例选择**,
> 不是抽象规则。**其他业务**应该根据自己知识库的实际章节命名,自行决定字段名和提取规则。
> 例如:
>
> - **数据提取业务**:字段可能是 `entity_name` / `entity_type` / `attributes` / `relations` / `metadata`
> - **文档生成业务**:字段可能是 `title` / `sections` / `template_vars` / `format` / `output_path`
> - **配置生成业务**:字段可能是 `service_name` / `version` / `dependencies` / `resources` / `env_vars`

**抽象规则 = "提取若干结构化字段,字段名/数量由业务决定";具体实例 = "提取 N 个具体字段,字段名固定"**。
本文件展示的是后者,规范是前者。

---

## 实例 3:显式输入解析策略 — "单文件章节定位"

### 抽象原则回顾

> read 步骤必须从业务方实际的输入文件直接解析,严禁假设未在 brief 中明示的目录结构。

### 具体实例(组件间流程设计业务)

`组件间流程设计` 业务读输入时,采用"单文件 + 章节定位"策略:

1. 输入文件: `${REQ_WORK_DIR}/req_design_document.md`(单文件,业务方在 brief 中声明)
2. 在文件内定位"组件变更分析"章节
3. 取章节后的第一个 Markdown 表格
4. 解析表头 + 数据行,根据双键(用例名 + 子系统名)过滤
5. 列名变体匹配:支持"用例/用例名称/UseCase"等多种命名

### 反例(此实例中)

- ❌ 假设存在 `${REQ_WORK_DIR}/统域变更分析/组件变更分析/{用例名}.md` — brief 没声明
- ❌ 用 `--input-dir` 接收目录参数 — brief 写的是单文件

### 其他业务怎么落地?

> **关键**:本实例的解析策略适用于"单文件 + 多章节 + 内嵌表格"的输入形态。
> 其他业务可能有不同的输入形态:
>
> - **目录扫描业务**:输入是 `${REQ_WORK_DIR}/cases/*.md` 多个文件,需要 glob 扫描
> - **API 拉取业务**:输入是远程 API 的 JSON 响应,需要 HTTP 请求 + JSON 解析
> - **多文件业务**:输入是 `${REQ_WORK_DIR}/{config,schema,data}.yaml` 3 个文件,分别解析

抽象规则 = "read 步骤必须显式声明自己的解析策略";具体实例 = "采用 X 解析策略"。

---

## 实例 4:数据完整性错误阻断 — "接口文档缺失即阻断"

### 抽象原则回顾

> 关键数据完整性错误必须阻断退出 + 写追溯报告,严禁静默跳过。

### 具体实例(组件间流程设计业务)

`组件间流程设计` 业务在 transform 步骤遇到"修改"类型时,会查存量接口文档。
本业务对"接口文档缺失"的处理是**阻断**而非跳过:

- 缺失路径:`${CONSUME_LIB_PATH}/design/系统库/子系统间接口/<interface_name>.md`
- 阻断行为:`sys.exit(1)` + 写 `step{N}_block_report.json`
- 报告内容:block_type=missing_interface_doc,row_index,expected_path,suggestion

### 阻断 vs 跳过的权衡

| 阻断 | 跳过 |
|------|------|
| 数据保真度高 | 流程跑通率高 |
| 业务方必须响应 | 业务方无需响应 |
| 适合关键数据 | 适合非关键数据 |
| 通过 --resume 可恢复 | 静默丢失,难发现 |

**抽象规则**:关键数据走阻断,非关键数据可跳过。**具体实例**:接口文档是"修改"类型的依据,缺失=无法转换,
所以是"关键数据" → 阻断。

---

## 实例 5:统一 LLM 断点入口 — "N=1 与 N>1 共用"

### 抽象原则回顾

> 多子场景共用一个 LLM 断点,子场景差异作为输入参数传递。

### 具体实例(组件间流程设计业务)

`组件间流程设计` 业务有"变更组件数 N=1 vs N>1"两个子场景,采用**统一 LLM 断点**:

- LLM 断点契约:`minimal_core_combo`(3 字段:insertions + row_updates + linkage_changes)
- N=1 时的差异:脚本确定性生成 `auto_insertions` 作为 LLM 输入的一部分
- N>1 时的差异:`auto_insertions` 为空,LLM 自行决定
- 不分两个 LLM 断点(N=1 一个 + N>1 另一个)

### 为何不按子场景拆分?

- LLM 看到不完整上下文
- 2 次调用 + 2 个 checkpoint 增加复杂度
- 子场景边界划分难

### 其他业务怎么落地?

> **关键**:本实例的"统一入口"原则适用于任何"有 N 个相似子场景"的 LLM 推理。
> 其他业务应根据子场景的相似度决定:
>
> - **子场景相似度高**(如 N=1 vs N>1、本组件 vs 跨组件):统一入口
> - **子场景差异极大**(如组件级 vs 子系统级 vs 系统级):可能需要多个 LLM 断点,但每个断点仍是 unified 入口(覆盖该层级的所有子场景)

---

## 反例(本业务中明确禁止)

| # | 反例 | 违反的抽象原则 |
|---|------|---------------|
| 1 | 单一默认分支:`if type == "X": do(); else: do_default()` | 分类-分支独立处理 |
| 2 | raw dump:`jq -n --rawfile content file.md` | 知识结构化提取 |
| 3 | 假设未声明的目录结构:`${WORK_DIR}/<未声明>/xxx.md` | 显式输入解析策略 |
| 4 | 静默跳过:`if [[ ! -f "${file}" ]]; then continue; fi` | 数据完整性错误阻断 |
| 5 | 按子场景拆 LLM 断点:N=1 一个 LLM,N>1 另一个 LLM | 统一 LLM 断点入口 |

---

## 与规范文件的关系

```
规范(必须遵守):
  framework_configs/norms/spec_norms.md            ← 抽象原则的详细说明
  framework_configs/knowledge/business_patterns.yaml ← 5 条抽象原则定义
  framework_configs/skill-create-guidelines.md §11.5 ← 框架级校验

非规范(本文件,仅供参考):
  framework_configs/norms/flow_design_style_guide.md ← 具体业务实例(本文件)
```

业务方编写自己的 spec 时:
- **遵守规范** 强制(5 条抽象原则)
- **参考本文件** 自愿(具体实例可借鉴,但**不是必须照搬**)

如果业务方的输入数据有"业务流变更类型"列,且该列恰好有 3 个类别,本文件的"三分支"实例可直接借鉴。
如果业务方的列名是别的(如"操作类型"),类别数也不一定是 3,那么业务方应**自行决定**如何落地"分类-分支"抽象原则。

---

## 写于 2026-07-13
## 路径:`framework_configs/norms/flow_design_style_guide.md`
