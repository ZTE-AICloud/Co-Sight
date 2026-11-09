---
name: traceaudit
description: Use when evaluating an already-completed Agent execution from its archived Claude JSONL traces, or a whole seed directory of them in batch. Runs a deterministic L0/L1 pipeline over the main trace and subagent traces and writes a five-dimension trajectory audit report. Offline-first: takes the main trace JSONL (--parent-jsonl) or a seed directory holding eval_datasets/seed.jsonl (--seed-dir) as its required input. Does not run business agents or modify artifacts.
---

# Trace Audit

评估一次**已经完成**的 Agent / 工作流执行。输入是归档的主 trace 和子 Agent trace，
输出是结构化的五维度轨迹评估报告。不启动业务 Agent，不修改业务产物，不改写原始 trace。

本 skill 只做**确定性**评估（L0 规则引擎 + L1 结构检查）。没有 LLM 语义裁判环节。
入口是**离线优先**的：单条评测必填参数只有一个主 trace 文件；批量评测必填参数是 `--seed-dir`。

## Skill Root

把包含本 `SKILL.md` 的目录视为 `skill_root`。**不要 `cd` 进入该目录**：用绝对路径调用
`node <skill_root>/scripts/traceaudit.mjs ...`，并保持当前工作目录为你的任务目录。

脚本之间的相对 import 由 Node 按**文件位置**解析，不依赖工作目录，所以在任何目录下执行结果都一样。

产物默认落在**调用方的工作目录**（`--outputs` 省略时的 `<cwd>/eval_trace_results/…` 与
`<cwd>/eval_trace_results/`）。若发现工作目录就是 skill 自身目录，脚本会直接报错退出，
避免把评测结果写进 skill 安装目录。

## 参数

单条评测一共三个参数，只有第一个必填；批量评测用 `--seed-dir`（外加可选 `--outputs` / `--timeout-ms`）。
`--outputs` 省略时，产物落在**调用方的工作目录**下。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--parent-jsonl` | 单条评测**是** | 主 trace 的 JSONL 文件路径。session id 取文件名（去掉 `.jsonl`）。不可与 `--seed-dir` 同时传递。 |
| `--subagents-dir` | 否 | 子 Agent trace 目录。省略时自动尝试 `<parent-jsonl 所在目录>/<session-id>/subagents`。不可与 `--seed-dir` 同时传递。 |
| `--outputs` | 否 | 单条评测时是报告输出目录本身，省略时写到 `<当前工作目录>/eval_trace_results/<case>_<session>_<时间>/`；批量评测时是父目录，产物落在 `<outputs>/eval_trace_results/`。 |
| `--seed-dir` | 批量评测**是** | seed 目录。其下固定存在 `eval_datasets/seed.jsonl`，逐条记录循环评测。给了它就不需要（也不允许）`--parent-jsonl` / `--subagents-dir`。 |
| `--timeout-ms` | 否 | 批量模式下单条评测的超时毫秒数（默认 `600000`，`0` 表示不限制）。 |

`--seed-dir` 与 `--parent-jsonl` / `--subagents-dir` **不能同时传递**：批量模式的 trace 坐标全部
来自 `seed.jsonl`，同时传参时会以 `invalid_arguments` 报错并退出（退出码 1），不会产生任何产物。

`caseId` 从主 trace 的 execute 触发命令推导：任何 `<命名空间>:execute <活动>` 形式都能识别，
推导不出来时回退为 session id。它只影响用例命名，不影响任何检查项。

## 运行

在**自己的工作目录**下用绝对路径执行（`<skill_root>` 是绝对路径）：

```bash
# 最小用法：只给主 trace
node <skill_root>/scripts/traceaudit.mjs --parent-jsonl "<主trace.jsonl>"

# 三参数全给
node <skill_root>/scripts/traceaudit.mjs \
  --parent-jsonl   "<主trace.jsonl>" \
  --subagents-dir  "<子Agent trace目录>" \
  --outputs        "<输出目录>"

# 批量评测：seed 目录 → 循环评测 → 汇总报告
node <skill_root>/scripts/traceaudit.mjs --seed-dir "<seed目录>" [--outputs "<父目录>"]
node <skill_root>/scripts/traceaudit.mjs batch --seed-dir "<seed目录>" [--outputs "<父目录>"]
```

先探路、不评估：

```bash
node <skill_root>/scripts/traceaudit.mjs validate --parent-jsonl "<主trace.jsonl>" [--subagents-dir <目录>]
node <skill_root>/scripts/traceaudit.mjs validate --seed-dir "<seed目录>"
node <skill_root>/scripts/traceaudit.mjs list   # 列出五个维度与其确定性检查项
```

`scripts/traceaudit.mjs` 也可作为模块 import。`evaluateTrace({ parentJsonlPath, subagentsDir, outputs })`
返回报告路径与 `rubricScores`；`evaluateSeedBatch({ seedDir, outputs, timeoutMs })` 返回批量汇总；
`validateInputs({...})` 返回 `{ ok, errors, warnings }`；`listDimensions()` 返回维度清单。

## 批量评测（seed 目录）

`--seed-dir` 下固定存在 `eval_datasets/seed.jsonl`。批量模式会：

1. 解析 `seed.jsonl`（兼容逐行 JSONL、单个纯 JSON 对象、JSON 数组、多个纯 JSON 对象首尾相接、
   以及 `{ "records": [...] }` 包装对象）。
2. 逐条取记录的 `run` 字段，读取 `run.session_id` 与 `run.session_dir`，定位主 trace
   （优先 `<session_dir>/<session_id>.jsonl`，再回退到目录内唯一的 `.jsonl`，最后尝试
   `run.case_dir`）；`run.subagents_dir` 存在且可解析时一并下传。
3. **循环**调用 `scripts/traceaudit.mjs` 逐条评测，每条写到自己独立的输出目录。
4. 全部跑完后汇总成 `batch-summary.json` 与 `batch-summary.md`。

单条失败（缺少 `run` / 找不到 trace / 子进程报错 / 超时 / 分数文件不可读）不会中断批量：
该条记为 `failed` 并继续，失败原因与阶段写入汇总。`run.subagents_dir` 写了但目录不存在时
不算失败，只在汇总的"警告"一节里记录。

```text
<输出根目录>/
├── batch-summary.json          # 结构化汇总（含逐用例明细、维度均分、失败原因与警告）
├── batch-summary.md            # Markdown 汇总报告
└── cases/
    └── <data_id>/              # 每条 trace 的完整报告，与单条评测产物一致
        ├── trajectory-report.json
        ├── trajectory-report.md
        ├── rubric-scores.json
        └── _intermediate/
```

输出根目录默认 `<调用方工作目录>/eval_trace_results/`；传了 `--outputs` 时改为
`<outputs>/eval_trace_results/`（此时 `--outputs` 是**父目录**，不是产物目录本身）。
只要有一条成功，退出码为 0；一条都没成功（或 seed 文件不可读）时退出码为 1。

## 输出

单条评测默认目录：`<调用方工作目录>/eval_trace_results/<case_id>_<session_short>_<timestamp>/`

不会写到 `parent-jsonl` 旁边 —— 离线 trace 常归档在 `~/.claude/projects/` 下，那里是 Claude 的
会话状态目录，不应被评估结果污染。也不会写到 skill 自身目录 —— 工作目录恰好是 `skill_root`
时会直接报错，提示改用 `--outputs` 或换到自己的工作目录执行。

| 文件 | 说明 |
|---|---|
| `trajectory-report.json` | 结构化轨迹评估报告 |
| `trajectory-report.md` | Markdown 汇总报告 |
| `rubric-scores.json` | 五维度得分（不可判维度为 `null`）、加权总分、`coverage`、`notApplicableDimensions`、等级、逐项检查明细 |
| `_intermediate/evaluation-trace.json` | 采集到的原始 trace |
| `_intermediate/evaluation-trace-processed.json` | 预处理后的 trace（execute 阶段 task 记录） |
| `_intermediate/l0-report.json` | L0 规则检查中间结果 |
| `_intermediate/l1-report.json` | L1 结构检查中间结果 |
| `_intermediate/insight-pack.json` | 证据包：episode、trace 信号、各维度证据状态与失败原因 |
| `_intermediate/report-validation.json` | 报告一致性与证据纪律自检结果 |

产品侧优先消费 `trajectory-report.json`、`trajectory-report.md`、`rubric-scores.json`；
需要解释"为什么这样打分"时再读 `insight-pack.json` 与 `report-validation.json`。

批量评测的输出根目录下另有 `batch-summary.json` / `batch-summary.md`（见上文"批量评测"），
逐用例报告落在 `cases/<data_id>/` 下，产物结构与单条评测一致。

## 评估模型

五个加权维度，每个 0–5 分，检查项定义在 `lib/rubrics.mjs`：

| 维度 | 权重 | 层 |
|---|---:|---|
| 流程合规性 `process-compliance` | 0.30 | L0 |
| Skill 调用完整性 `skill-invocation` | 0.20 | L0 |
| 审查完整性 `review-completeness` | 0.20 | L0 |
| 规则合规性 `rule-compliance` | 0.15 | L0 |
| 轨迹效率 `trace-efficiency` | 0.15 | L1 |

总分 = Σ(维度分 × 权重) / Σ(可判维度权重)，无红线、无总分封顶。等级：≥4.5 `EXCELLENT`，
≥3.5 `ACCEPTABLE`，≥2.0 `POOR`，<2.0 `CRITICAL`。

### 可判性（not-applicable）与证据覆盖率

检查项只有在 trace 里真的能判才算数。**没有证据的检查项既不算通过也不算失败**，记为
`not-applicable`（`passed: null`），不参与任何打分——不允许"没查成"被折算成"查过了，满分"。

- 维度内可判检查项占比 < 0.5 时，该维度不给分（`score: null`，`label: 不适用` / `证据不足`）。
- `coverage` = 拿到分的维度权重 / 全部维度权重（0–1）。
- `coverage < 0.6` 时**不给总分、不给等级**：`totalScore: null`，`grade: UNDETERMINED`，
  `renormalizedScore` 只作为可判维度的均分出现在报告里，不是总分。
- 报告与 `rubric-scores.json` 都带 `coverage`、`notApplicableDimensions`；Markdown 里有
  "不可判定项"一节逐条列出原因。批量汇总把不可判定用例单独成桶，不进入平均分。

典型情形：一次普通单轮会话（无子 Agent、只有一次 Skill 调用）在五个维度里只有一个维度可判，
覆盖率 0.20，结论是 `UNDETERMINED` 而不是高分——这套 rubric 判不了它。

D5 的 `hard_fail` 检查仍会在**维度内**强降分（降到 0/1），但不影响加权总分。

## 常量与配置

- 检查项的增删改一律改 `lib/rubrics.mjs`（维度、权重、`rule_checks` / `structure_checks`）。
  检查项必须与具体编排框架无关：不得编码 `drive` / `co-helm` 之类框架的专属规矩。
- `scoring.mjs` 负责把检查项折算成维度分；`.yaml` 文件已不再使用。
- 依赖零第三方包：JSONL 解析为 `lib/jsonl.mjs` 下的自实现。

## 边界

- 只评估已完成执行，不启动业务 Agent、不修改业务产物。
- 不假设被测执行来自某个编排框架：没有触发命令就是没有，不伪造 `/drive:execute` 之类的
  触发命令；审查类子 Agent 按类型名里的审查语义识别（`isReviewAgentType`）。
- 默认输出锚点取**调用方的工作目录**，且拒绝写进 skill 自身目录（解析见
  `lib/cli.mjs` 的 `resolveWorkspaceDir()`）。
- 只消费 trace，不读取执行计划、agent 定义或产物文件系统，报告中也不体现这些内容。
- 不做 Golden Eval 的 Precision / Recall / F1 数据集快照评估。
- 不从 `~/.claude/projects/` 猜 session：trace 坐标必须由 `--parent-jsonl` 显式给出，
  批量模式下则由 `eval_datasets/seed.jsonl` 里每条记录的 `run.session_id` / `run.session_dir` 显式给出。
- 批量模式不并发、不重试：一条记录对应一次顺序执行的评测进程。单条进程超时（`--timeout-ms`，
  默认 10 分钟）只终止该条并记为失败，不影响其余记录。
- `seed.jsonl` 被视为**可信输入**：其中的 `run.*` 路径按原样解析，路径内容会进入报告，
  不做越权校验。不要在不可信的 seed 文件上执行批量评测。
