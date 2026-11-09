# 评分分析报告

> 本报告由 LLM 端到端生成,框架仅落盘不修改。
> 计算细节和数据来源请参见报告各章节。

## 基本信息

- **Round**: <LLM 填写,如 1;baseline 填 baseline>
- **Candidate**: <LLM 填写,如 baseline / 1 / 2>
- **Run**: <LLM 填写,如 1>
- **生成时间**: <LLM 用 Bash date 拿当前时间>

## 摘要(框架从这里读分数)

- **结果分数**: <LLM 必填,百分制 0~100 之间的数字,如 53.27,保留 2 位小数>
- **CASE 总数**: <LLM 填写,实际评测 case 数>
- **数据来源文件数**: <LLM 填写,涉及到的 JSON/MD 文件数>
- **分数聚合方式**: <LLM 填写,如 算术平均 / 加权平均 / 最大值 / 最小值 等>
- **平均输入 Token**: <LLM 必填,macro-mean over cases(整数,如 51811);`valid_token_case_count=N` 表示 N 个 case 有有效 token>
- **平均输出 Token**: <LLM 必填,macro-mean(整数,如 31567);`valid_token_case_count=N`>
- **平均时间消耗**: <LLM 必填,macro-mean ms 整数,如 1562661;`valid_duration_case_count=N`;或秒+单位,如 1562.66s>
- **总输入 Token**(deprecated,sum 口径,仅作审计用): <LLM 选填,整数>
- **总输出 Token**(deprecated): <LLM 选填>
- **总时间消耗**(deprecated): <LLM 选填,ms 或秒+单位>

> **口径说明**:`平均*` 字段是主推指标,口径与 `结果分数` 一致(macro-mean over cases);`总*` 字段保留作向后兼容,会被 0 拉低(某 case token 采集失败时),不推荐作评估主指标。

## 评分推理

<LLM 自由发挥,2-5 段,说明:
- 数据是怎么探查的
- 分数是怎么算的
- 跟预期的对比
- 平均输入/输出 Token/平均时间消耗 的口径(macro-mean over cases,排除 token=0/duration=0 的 case)>

## 各 CASE 明细(必填)

> 本节用 markdown 表格列出每个评测 case 的独立分数 + 资源消耗。case_id 直接用 LLM 在评测产物中看到的标识符(如 RAN-3532502 / CASE-001 / TC-yyy 等)。

| CASE ID | 分数(百分制 0~100) | 输入 Token | 输出 Token | 耗时(ms) | token 缺失? | 数据来源文件 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| <case_id_1> | <分数> | <整数> | <整数> | <整数> | <是/否> | <相对路径> | <可选> |
| <case_id_2> | <分数> | <整数> | <整数> | <整数> | <是/否> | <相对路径> | <可选> |
| ... | ... | ... | ... | ... | ... | ... | ... |

> 输入 Token / 输出 Token / 耗时列:与 score.json 的 `info.{input_tokens_per_case, output_tokens_per_case, duration_ms_per_case}` 对齐;`token 缺失?` 列标 `是` 表示该 case 资源指标采集失败(记 0),平均聚合时从分母中隔离。

## 根因分析(当结果分数 < 100 时必填)

<LLM 写 2-5 句话,自由发挥,说明分数低于 1 的原因>

## 关键发现

- <要点 1>
- <要点 2>
- <要点 3>
- ...

## 风险信号

- <风险 1>
- <风险 2>
- ...

## CASE 证据数据(必填,生成 result_diff_report.md 的输入)

> 本节提供每 case 的 3 段证据(gold / llm_output / diff_notes),由 LLM 探查 phase3-eval/{req_id}_*/ 直接抽取。
> 写入 score.json 的 info.{gold_per_case, llm_output_per_case, diff_notes_per_case} 三个字典,
> 🆕 **2026-07-31 改造**:gold_per_case / llm_output_per_case 的 value 是**绝对路径字符串**(`/...` 开头),framework 渲染层按路径 Read 真文件原文;diff_notes_per_case 仍是字段字符串(LLM-as-Judge 输出)。
> 字典 value 缺失时留空串(不是相对路径)。
> **路径约定见业务方 YAML `score_extraction.extraction` 段**(模板不写死具体文件名,业务变更只改 YAML)。

| CASE ID | gold 文本绝对路径 | llm_output 文本绝对路径 | diff_notes(完整,不要截断) |
| :--- | :--- | :--- | :--- |
| <case_id_1> | `/.../inputs/gold/<R_*.md>` | `/.../inputs/agent/<C_*.md>` | <diff_notes 全文> |
| <case_id_2> | `/.../inputs/gold/<R_*.md>` | `/.../inputs/agent/<C_*.md>` | <diff_notes 全文> |
| ... | ... | ... | ... |

## CASE Trace 路径(trace-aware 诊断必备)

> 本节提供每 case 的 trace **路径 list**(`/...` 开头的绝对路径,framework 端 Read 真文件)。
> 写入 score.json 的 `info.trace_paths_per_case` 字典,key=req_id,**value = list of 绝对路径**:
> 第 1 位 `trace.log`(整体轨迹,简化版,主推),后续 `subagents/agent-*.jsonl`(各 skill 轨迹,含 skill 片段)。
> 抽取:1) `ls -d phase2-exec/{req_id}_*/ | head -1` 取 case_dir;
> 2) `realpath {case_dir}/trace/trace.log` → list[0];3) `ls {case_dir}/session/run/*/subagents/agent-*.jsonl` 逐个 `realpath` 全部 append。
> **不放 trace.jsonl(详细版已弃用)**。文件不存在 → 该 case 对应 value 留空 list。

| CASE ID | trace 路径 list(第 1 位 trace.log,后续 subagents/*.jsonl) |
| :--- | :--- |
| <case_id_1> | [`/.../phase2-exec/<{req_id}_*>/trace/trace.log`, `/.../phase2-exec/<{req_id}_*>/session/run/<uuid>/subagents/agent-*.jsonl`, ...] |
| <case_id_2> | [`/.../phase2-exec/<{req_id}_*>/trace/trace.log`, `/.../phase2-exec/<{req_id}_*>/session/run/<uuid>/subagents/agent-*.jsonl`, ...] |
| ... | ... |

## 计算过程(可选,LLM 想展示就展示)

    # LLM 自己写数学算式,例如:
    # values = [read_json(f).get("total_score") for f in json_files]
    # result_score = sum(values) / len(values)  # 保持百分制 0~100
    # 注意:本节用 4 空格缩进展示代码,不要用 ```python 围栏(避免与外层 markdown 围栏嵌套导致 framework 抽取截断)

## 元信息

- **提取方式**: LLM 端到端生成(框架仅落盘)
- **模板版本**: 填空式 v1
- **生成时间**: <LLM 用 Bash date 拿>
