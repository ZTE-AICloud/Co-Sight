---
name: goldeval
description: >-
  黄金数据集评测能力 — goldeval run/traceaudit/list/show/validate 子命令，内置 f1_score 等评估器，
  评估器可注册扩展，数据集为 .jsonl 格式。
when_to_use: >-
  需要对模型输出做黄金评测、运行 goldeval 评测、评估已完成的 Agent/工作流执行轨迹、
  查看可用数据集与评估器、校验数据集格式、新增评估器时使用。
license: MIT
---

# Goldeval

黄金数据集评测能力。命令入口为 `/goldeval`，子命令如下：

- `goldeval run [--dataset <path>] [--evaluators <names>] [--threshold <float|key:value...>] [--outputs <path>] [--worker <int>]` — 对数据集运行评测（`--threshold` 全局阈值缺省 `0.6`，也支持键值对 `recall:0.7,precision:0.8,f1_score:0.75`（未指定的评估器默认 `0.6`）；`--outputs` 缺省在当前工作区，指定则在指定目录下，均创建 `eval_results/` 存放结果；`--worker` 并发数，缺省 `1`，最大 `5`；数据集最多 `100` 条，超出报错）
- `goldeval traceaudit --parent-jsonl <path> [--subagents-dir <path>] [--outputs <path>]` — 评估一次已完成的 Agent/工作流执行过程，输出五维度轨迹评估报告（见下）
- `goldeval list` — 列出可用数据集、评估器与轨迹过程评估各维度权重
- `goldeval show` — 展示测试集构造示例（字段说明 + example.jsonl 前 3 条）
- `goldeval validate --dataset <path>` — 校验数据集格式（JSON 合法性、data_id 唯一、input/output/expected_output 必填）
- `goldeval --version` — 输出 goldeval 版本号（定义在 `version.ts`）

## 架构

```
goldeval-plugin/
├── commands/
│   └── goldeval.md            # /goldeval 入口，解析子命令
└── skills/goldeval/
    ├── scripts/run.ts         # 执行数据集评测
    ├── scripts/list.ts        # 列出数据集、评估器与轨迹维度
    ├── scripts/show.ts        # 展示测试集构造示例
    ├── scripts/validate.ts    # 校验数据集
    ├── scripts/version.ts     # 输出版本号
    ├── scripts/call.ts        # 直接调用 LLM（手工调试）
    ├── scripts/manual.ts      # 手工触发分句/归类（调试用）
    ├── evaluators/            # 评估器注册表（按 family 分目录）
    │   ├── index.ts           # 注册表
    │   ├── types.ts           # 输入输出类型契约
    │   ├── llmasjudge/        # LLM 判定类指标（f1_score / precision / recall）
    │   │   ├── llm.ts         # LLM 调用（claude -p 无头模式）
    │   │   ├── classifyPipeline.ts # 分句+归类共享管道 → tp/fp/fn
    │   │   ├── metrics.ts     # precision/recall/f1 计算公式
    │   │   ├── f1_score.ts    # F1 评估器
    │   │   ├── precision.ts   # 精确率评估器
    │   │   └── recall.ts      # 召回率评估器
    │   ├── certainty/         # 确定性评估（equals / contains）
    │   │   ├── equals.ts      # 精确匹配：output === --value
    │   │   └── contains.ts    # 包含匹配：output 包含 --value
    │   
    ├── datasets/              # 数据集目录
    ├── version.ts             # goldeval 版本号
    └── SKILL.md               # 本文件
```
## 数据集格式

JSONL 格式，每行一个 JSON 对象。字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| data_id | string | 是 | 样本唯一 ID |
| input | string | 是 | 问题/输入 |
| expected_output | string | 是 | 黄金参考答案 |
| output | string | 是 | 待评测的模型输出 |
| context | string | 否 | 参考上下文 |
| metadata | object | 否 | 元数据（category/difficulty/tags/model_under_test 等） |

示例见 `datasets/example.jsonl`。

> 数据集中的 `data_id` 用于 validate 校验与去重；评测结果文件中的 `data_id` 与输入数据集保持一致。

## 输出格式

每个样本的评测结果（单条记录，`data_id` 与输入数据集一致）：

```json
{
  "data_id": "bug_fix_001",
  "evaluator": "f1_score",
  "score": 0.67,
  "passed": true,
  "threshold": 0.6,
  "score_detail": {
    "precision": 0.75, "recall": 0.6, "f1": 0.67,
    "tp": ["g1", "g2", "g3"], "fp": ["p4"], "fn": ["g4", "g5"],
    "score_mode": "llm_score"
  },
  "reason": "输出覆盖了升级版本与开关配置,遗漏了外部调用过滤与展示影响;多给出一个与期望无关的采样率建议",
  "metadata": {}
}
```

字段说明：

- `data_id`：与输入数据集的 `data_id` 保持一致
- `score`：评估得分（f1_score 为四舍五入到 2 位小数的 F1）
- `passed`：`score >= threshold`（处理失败的样本恒为 `false`）
- `score_detail`：评估器内部指标（precision/recall/f1、tp/fp/fn 命中项、score_mode）
- `reason`：打分说明（来自 LLM 归类，缺省为 TP/FP/FN 统计）
- `error`（可选）：处理失败的样本携带，值为失败原因（如分句/归类解析失败或结果为空）；正常样本无此字段

输出产物按 `eval_results/<task_id>/` 组织，`task_id` 为每次运行的时间戳：

```
eval_results/
└── <task_id>/
    ├── summary.json                 # 评测报告（JSON）
    ├── report.md                    # 评测报告（Markdown）
    ├── <evaluator>_results.jsonl    # 结果文件，每行一个 EvalResult（如 f1_score_results.jsonl）
    └── process/
        └── <data_id>/
            ├── split.json                  # 分句结果（output_sentences / expected_sentences，各评估器共用）
            ├── classify.json               # 归类结果（tp / fp / fn / reason，各评估器共用）
            └── result_<evaluator>.json     # 该评估器的 EvalResult（如 result_f1_score.json）
```

每个评估器一个 `<evaluator>_results.jsonl`；mean/passed 汇总打印到控制台。

## 评测报告

`run` 结束后自动生成 `summary.json` / `report.md`（按选中的评估器汇总，两种格式数据一致）：

- 任务信息：task_id / dataset / samples / threshold / evaluators / model / generated_time
- 每个评估器：avg（平均值）/ pass_rate（通过率）/ passed / samples / max / min / scores / threshold（确定性评估不含 threshold）

`summary.json` 结构：

```json
{
  "task_id": "20260814154507",
  "dataset": "...",
  "samples": 3,
  "threshold": 0.6,
  "evaluators": ["f1_score", "precision"],
  "model": "dept6-ADC-DeepSeek-Claude",
  "generated_time": "2026-08-14T07:45:08.037Z",
  "results": {
    "f1_score": { "avg": 0.82, "min": 0.67, "max": 1.0, "passed": 3, "pass_rate": 1.0, "samples": 3, "scores": [0.8, 1.0, 0.67], "threshold": 0.6 }
  }
}
```

## 句子匹配评估器（f1_score / precision / recall）

三个评估器共用同一管道，对每个样本调用 LLM（自包含实现，见下）分两步得到 TP/FP/FN：

1. **分句**：把 `output` 与 `expected_output` 分别拆分为句子，结果存 `process/<data_id>/split.json`（共用）
2. **归类**：判断句子归属，结果存 `process/<data_id>/classify.json`（共用）
   - **TP**：output 与 expected_output 都存在的句子
   - **FP**：output 存在但 expected_output 不存在的句子
   - **FN**：expected_output 存在但 output 不存在的句子
3. **计分**（`metrics.ts`，各评估器独立计算）：
   - `f1_score`：`F1 = 2×TP / (2×TP + FP + FN)`，score_detail 含 precision/recall/f1
   - `precision`：`TP / (TP + FP)`
   - `recall`：`TP / (TP + FN)`

**运行时去重**：当选择 2 个及以上评估器时，每个样本只跑一次分句+归类（`classifyOutcome`），TP/FP/FN 通过 `EvalOptions.outcome` 复用于所有评估器，LLM 调用数 = 样本数 × 2，与评估器数量无关。

**失败处理**：分句或归类若 LLM 返回无法解析的内容，会自动重试（最多 3 次）；重试后仍失败或分句结果全空，该样本返回 `error` 字段（结果以失败计，`score=0, passed=false`），其余样本正常评测，不会中断整次运行。

**边界规则**（三个评估器一致）：

| 情形 | 结果 |
|---|---|
| 有 TP，部分 FP/FN（部分命中） | 按各自公式算部分分，如 `TP=3,FP=1,FN=0` → precision=0.75, recall=1.0, F1≈0.86 |
| 无 TP 的纯 FP（预测多出） | 0 |
| 无 TP 的纯 FN（遗漏） | 0 |
| output 与 expected_output 均无句子（双空） | 失败（`score=0, passed=false, error=原因`）——数据集校验已保证两字段非空，双空视为分句失败 |
| 分句/归类解析失败（重试 3 次后） | 失败（`score=0, passed=false, error=原因`） |
| 归类结果全空 | 失败（`score=0, passed=false, error=原因`） |

调用方式：把提示词从 stdin 送进 `claude -p`，取 `--output-format json` 输出的 `result` 字段：

```
claude -p --output-format json --no-session-persistence
```

- 每次判定新起一个 claude 进程（不落会话），`--worker` 即同时在跑的进程数，默认 1、最大 5
- 单次调用超时 600000ms；判定成功的条件是退出码为 0、`is_error` 非 true、`result` 能解析出文本，否则该次调用失败（由调用方重试）
- 报告里的 `model` 取自 claude 输出的 `modelUsage`，即本次实际使用的模型；取不到时用 `ANTHROPIC_MODEL`

提示词要求 agent 只输出 JSON，程序解析为数组。

## 确定性评估器（certainty / equals / contains）

纯规则评估，不调用 LLM，得分只有 0 / 1：

- `equals`：比较样本 `output` 与 `--value`，**完全相等**得 1（passed=true），否则得 0
- `contains`：样本 `output` **包含** `--value` 得 1，否则得 0
- `passed` 直接取 matched（确定性评估不依赖 threshold，结果里也不含 threshold 字段）
- 使用需带 `--value <value>` 参数，否则报错
- 支持 `not-` 前缀反转：`not-equals` / `not-contains` 表示**不满足**时得 1（仅确定性评估器支持，如 `not-f1_score` 会报错）

结果格式（确定性评估家族通用）：

```json
{
  "data_id": "bug_fix_001",
  "evaluator": "equals",
  "output": "2",
  "passed": true,
  "score": 1,
  "score_detail": { "matched": true, "value": "2" },
  "reason": "",
  "metadata": {}
}
```

```bash
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/run.ts --dataset <path> --evaluators equals --value <value>
```

## 评估器注册表

当前内置评估器：

| 名称 | 家族 | 说明 |
|---|---|---|
| f1_score | llmasjudge | LLM 分句+归类 F1（2TP/(2TP+FP+FN)） |
| precision | llmasjudge | 精确率 TP/(TP+FP) |
| recall | llmasjudge | 召回率 TP/(TP+FN) |
| equals | certainty | 确定性判定：output 与 --value 完全匹配得 1，否则 0（需 --value） |
| contains | certainty | 确定性判定：output 包含 --value 得 1，否则 0（需 --value） |

新增评估器步骤：

1. 若基于 TP/FP/FN：复用 `classifyOutcome`（`classifyPipeline.ts`），在 `evaluators/` 下新建 `<name>.ts` 实现 `evaluate(sample: EvalOptions, options) => Promise<EvalResult>`
2. 在 `evaluators/index.ts` 的 `EVALUATORS` 中注册，`list` 会自动展示

## 使用

> 脚本绝对路径以 `${CLAUDE_PLUGIN_ROOT}` 占位，实际执行时插件加载器会替换为插件根目录（安装后一般为 `~/.cosight/plugins/marketplaces/goldeval`）。
> 数据集示例见 `list` 命令输出，路径为 `${CLAUDE_PLUGIN_ROOT}/skills/goldeval/datasets/example.jsonl`。

```bash
# 运行评测（默认使用 f1_score）
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/run.ts \
  --dataset ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/datasets/example.jsonl

# 指定评估器
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/run.ts --dataset <path> --evaluators f1_score

# 指定阈值与输出目录
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/run.ts --dataset <path> --evaluators f1_score --threshold 0.8 --outputs /tmp/evals

# 指定并发数（默认 1，最大 5）
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/run.ts --dataset <path> --evaluators f1_score --worker 3

# 注意：llmasjudge 评估器运行时通过 claude -p 无头调用，需要 PATH 中可执行 claude

# 列出可用数据集与评估器
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/list.ts

# 展示测试集构造示例（前 3 条）
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/show.ts

# 校验数据集（JSON 合法性、data_id 唯一、必填字段）
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/validate.ts --dataset <path>

# 输出版本号
node ${CLAUDE_PLUGIN_ROOT}/skills/goldeval/scripts/version.ts
```
