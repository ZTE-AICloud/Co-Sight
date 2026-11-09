---
name: e2e-test-evaluator
description: "读取 e2e-test-runner 产出的 run_datasets/seed.jsonl，按 runtime-rubric 评分细则派并发 sub agent 逐条评测，汇总出加权分、通过率与报告。"
---

# agent-eval — 评测集评分

读取上一环节跑完的用例集，逐条按评分细则打分，给出单条结论与整轮汇总。

## Argument handling — IMPORTANT

This skill takes arguments. If `$ARGUMENTS` is provided, use it. Otherwise check the
conversation.

**参数原样透传，没有子命令**。Claude Code 的斜杠命令不能可靠转发参数，因此把
`$ARGUMENTS` 完整交给入口脚本：

```bash
python3 <SKILL.md 所在目录>/scripts/evaluate.py \
  --input <值> --output <值> --concurrency <值>
```

三个参数**全部可选**：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--input` | `outputs/` 下**目录名倒序第一**的 `e2e-test*` | 可指 **run 目录** / `run_datasets` 目录 / `seed.jsonl` 文件三种形态 |
| `--output` | 同 `--input` 默认规则（通常解析到同一个 run 目录） | 结果落其下的 `eval_datasets/`。**给的是 run 目录，不是 `eval_datasets/` 本身**。两条链独立解析，不互相牵连 |
| `--concurrency` | `1` | 本批同时派几个裁判 sub agent，范围 1~32 |

## 你的循环：两阶段，同一条命令

脚本**不含任何 LLM 调用**——裁判是**你**派的 Task。脚本每次启动都做同一件事：
扫 `.work/` 看还缺哪些裁判答案；缺就打印批次清单并退出，不缺就聚合落盘。

```
1. 运行 evaluate.py <参数>
   ├─ 打印「需要你出力：N 条用例待裁判，分 M 批」+ 每批的 data_id 与 prompt 绝对路径
   └─ 报错退出（参数/数据有问题，见下方「报错而非静默避让」）

2. 按它打印的批次清单派 claude 类型 sub agent。
   **每批同时发出该批全部 Task**，等整批返回后再发下一批（批次屏障）。
   每个 Task 的 prompt 只说一句话：

     读取 <prompt 文件绝对路径> 并严格按其中指示执行，
     把最终 JSON 写到其中指定的 answer 文件。

3. 全部批次完成后，**重跑同一条命令** → 聚合、落盘、打印「落盘完成」
```

**不要自己读 `.prompt.md` 的内容，也不要自己打分。** prompt 里塞着评分细则全文与
5 条用例的全部证据，读进你的上下文既浪费又会让后续判分漂移；裁判答案由 sub agent
直接落到 `.work/{data_id}.answer.json`，你全程不接触评分内容。

**主 agent 禁令**：你只许**派活、收活、跑脚本、汇报**。不得自行修改、覆盖或"微调"
任何裁判分数——包括你觉得明显不合理的那种。唯一例外是脚本判定不合格时，你把该条
**原样重派**给一个新裁判（见下）。

## 输出契约

**只读** `<input>` 侧的 `run_datasets/seed.jsonl`——那是 runner 的交付物，全程一个
字节不改。**只写** `<output>/eval_datasets/`：

```
<output>/
└── eval_datasets/
    ├── seed.jsonl                  ← 原字段一字不改 + 新增 eval 子对象
    ├── eval-manifest.json          # rubric 指纹 / 裁判模型 / 并发数 / 阈值
    ├── report.md                   # 人读报告
    └── .work/
        ├── {data_id}.prompt.md     # 脚本产：细则 + 用例 + 证据 + 输出 schema
        ├── {data_id}.answer.json   # 裁判产：逐条存证，保留不清理
        └── {data_id}.attempts      # 该条已派过几次裁判
```

`eval` 子对象（原记录字段一字不改，结果挂在新增键下）：

```json
{"data_id": "...", "input": "...", "expected_output": ["..."], "run": {...},
 "eval": {
   "status": "ok",
   "run_valid": false,
   "invalid_reason": "precondition 声明的目录不存在，扫描未执行",
   "items": [{"text": "...", "verdict": "hit|miss|unverifiable", "note": "..."}],
   "correctness": 2, "completeness": 1, "format_compliance": 3, "actionability": 3,
   "weighted_score": 2.05, "passed": false,
   "reasoning": "...", "attempts": 1
 }}
```

### 登记裁判模型

聚合落盘前，用 Write 工具写一份 `<output>/eval_datasets/judge.json`：

```json
{"model": "<裁判 sub agent 的模型>", "main_agent_model": "<你自己的模型>"}
```

**只有你知道自己的模型名**，脚本猜不准，所以这份文件由你写、脚本读。缺失不报错，
报告里显示"未登记"，但那样报告就失去了跨轮次可比性——建议每次都写。

## 写给裁判的评分依据

裁判是**独立会话**，只拿到一份内联的 prompt（脚本渲染），**不碰文件系统**：

| 给裁判 | 内容 |
|---|---|
| 评分细则 | `references/runtime-rubric.md` **全文**（随 skill 分发，是唯一生效版本） |
| 任务要求 | `input` |
| **环境声明** | **`precondition`** |
| 判据 | `expected_output` 逐项 |
| 证据 | `result.json` 的 `result` **全文**；缺失时退 `run.result_preview`（同样是完整文本） |
| 执行元数据 | `status` / `exit_code` / `elapsed_seconds` / `timed_out` / `error`，**标注"仅供参考，不得作为打分依据"** |
| 环境参照 | 该用例会话真正的 cwd（`workspace_dir`），供交叉验证 Agent 的环境类陈述 |

> **`precondition` 给裁判，与 runner 的做法正好相反。** runner 刻意不把它喂给被测
> Agent（其中常含答案原文，如待检出的明文凭据）；但裁判恰恰需要它——`precondition`
> 写着"某目录存在且可读"，正是判 `run_valid=false` 的直接依据。同一个字段，对被测
> Agent 是泄题，对裁判是判据。

## 评分算术：裁判只报事实，算术在脚本

裁判回四个维度的**整数分**与**逐项判定**；`weighted_score` 与 `passed` 由脚本算。

```
weighted = correctness×0.40 + completeness×0.30 + format×0.15 + actionability×0.15
通过      = 加权 ≥3.5 且 correctness ≥3.0 且 completeness ≥3.0
```

权重与阈值硬编码在 `scripts/config.py`；`tests/test_aggregate.py` 会**反向解析
rubric** 断言二者一致——改了 rubric 却忘了改 config，测试会红。

### 两处判据在当前数据形态下的落地解释

`runtime-rubric.md` 来自上游协议，有两处判据在本测试集里没有对应字段。这两条已经
写进裁判 prompt，此处记录以便追溯：

1. **`expected_output` 没有 required / optional 标注**（seed 只有 9 个扁平字段）。
   因此**整体视为 required**：逐项判定算命中率，命中率映射 completeness 档位。
   `unverifiable` 既不计分子也不计分母。
2. **测试集没有声明输出 Schema / 模板**。因此 `format_compliance` 以**该任务隐含
   要求的输出形态**为尺度（结构是否自洽、层次是否清晰、关键信息可否直接提取），
   不因"没符合一个不存在的 Schema"而扣分。

## 环境未就绪的用例：标记并隔离，不静默低分

这是本 skill 存在的主要理由之一。真实数据里出现过**全部用例**都因夹具路径未落地而
失败的情况（`precondition` 声称目录存在，但会话 cwd 下根本没有那个路径）。此时若
机械拿 `expected_output` 比对输出，会得出"Agent 很差"的假结论。

所以裁判在四个维度之外**额外判一个 `run_valid`**：本次执行环境是否如 `precondition`
所述就绪、Agent 是否真有机会完成任务。聚合时：

- `run_valid=false` 的条目**单列一节，绝不进任何平均值与通过率**；
- 但它的四维分**照样展示**——那正是"这批为什么无效"的证据；
- 全轮有效样本为 0 时，报告首行直书"本轮无有效评测结论"，**评测器本身不报错**。
  把"Agent 表现为空"报成"评测器失败"会误导人去查评测器。

## 聚合口径

- **单条**：三阈值全过才 `eval.passed = true`（rubric 的原口径）。
- **整轮**：有效样本 N/M、通过率、各维度均分、**加权平均分**。
  加权平均分 = **逐条 `weighted_score` 的平均**；各维度均分只作辅助（看是哪一维拖
  后腿），**不合成第二个"总分"**。
- **按 `dimension` 分组**列出通过情况，**各组之间不合成总分**：生成器的
  `dimension_weights` 是抽样配额权重，拿它当评分权重会让"抽了几条"影响"得几分"。
- **矛盾提示**：若裁判的逐项命中率与它自报的 completeness **明显冲突**，报告里打
  `inconsistent` 提示。**只提示、不覆盖**——completeness 档位表并不纯粹是命中率
  （rubric 里还有"关键类别遗漏"这类定性判据），硬覆盖会引入脚本自己的误判。

## 自愈与续跑

**已评过的条目跳过**，只派剩下的。因此续跑是增量的，中途中断不丢结果。

裁判答非所问时（JSON 不可解析、`items` 项数与 `expected_output` 不等、`data_id`
不匹配、四维分越界、`run_valid=false` 却没写理由）——脚本把该条**退回重派清单**，
你据此只重派这些条目。同一条**最多派 2 次**，仍不合格则该条记
`eval.status = "parse_error"` 并**单列**，整轮照常交付（不死循环、不阻塞）。

**没有强制重评的 CLI 参数。** 要让某条重评，删掉它的
`<output>/eval_datasets/.work/{data_id}.answer.json` 再跑即可。要整轮重来：

```bash
rm -rf <output>/eval_datasets
```

续跑要求两次的用例集合（`data_id` 序列）完全一致，否则报错——避免把两份不同的
测试集混进同一份结果里。

**退出码**：`0` = 评测正常完成（不论 Agent 考得好坏）；`1` = 有 `parse_error` 单列。
**退出码不表达通过率**——否则 `set -e` 的脚本会在 Agent 表现差时中断，而那恰恰是
你想看结果的时刻。

## 报错而非静默避让

以下情形一律报错退出（退出码 1），不猜、不回退：

- `--input` 解析不出 `seed.jsonl`（目录下没有、文件名不对、路径不存在）
- **`--input` 指向 `generated_datasets/`**——那是生成器的交付物，里面的用例还没有
  `run` 字段。报错会指名 `e2e-test-runner`，而不是笼统地说"找不到 seed.jsonl"
- 缺省 `--input`/`--output` 时 `outputs/` 下没有任何 `e2e-test*` 目录
- **有记录的 `run` 字段缺失**（还没跑过）——硬评只会产出一堆假低分，报错会列出全部
  缺失的 `data_id`
- 记录缺 `data_id` / `input`，`data_id` 含路径分隔符，`expected_output` 缺失或为空
- `--concurrency` 越界
- **`--output` 会覆盖 `--input` 的 `seed.jsonl`**
- **`--output` 解析出的产物目录落在某个用例的 `workspace/` 内，或落在 `agent_root` 内**
  ——`.work/*.prompt.md` 里有 `expected_output`（答案），落进被测目录等于把答案递给
  被测 Agent，且失真不可见。这条在 startup 早失败

## 明确不做

行为分析、副作用快照、深挖 `workspace/` 里的产物、rubric 漂移检查、`--model` 参数、
`--force` 参数。`workspace/` 只在 prompt 里给出路径作**参照系**，裁判不主动去读。

> 与两个邻居的分工：**generator** 造用例（`generated_datasets/`），**runner** 跑用例
> （`run_datasets/`，每用例一份 `workspace/` 副本），**本 skill** 判用例
> （`eval_datasets/`）。评测只读 runner 的交付物，不回写。

## 测试

```bash
python3 -m pytest <SKILL.md 所在目录>/tests -q
```

**纯确定性**：不调 `claude` CLI、不发网络请求、不需要打桩——裁判是主 agent 派的
Task，脚本里没有任何 LLM 节点。`tests/test_aggregate.py` 里含前面说的 rubric 反向守卫。
