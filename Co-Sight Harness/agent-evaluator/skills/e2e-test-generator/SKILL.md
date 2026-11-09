---
name: e2e-test-generator
description: "从 Agent 源码目录（工具定义、系统提示词、框架配置等）生成带 input 与 expected_output 的测试用例集。"
---

# agent-eval — Agent 评测集生成

从被测 Agent 的源码目录抽取画像，生成可直接用于评测的测试用例集。

## Argument handling — IMPORTANT

This skill takes arguments. If `$ARGUMENTS` is provided, use it. Otherwise check the
conversation.

## 执行入口

Claude Code 的斜杠命令不能可靠转发参数，因此**把 `$ARGUMENTS` 去掉首词后原样透传**给入口脚本。
入口脚本位于**本 SKILL.md 同目录**下的 `scripts/generate.py`：

```bash
python3 <SKILL.md 所在目录>/scripts/generate.py \
  --agent <值> --count <值> --input "<值>" --output <值>
```

参数只有四个：

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--agent` | 是 | — | 待评测 agent 目录 / `.zip` / `.tar.gz`（自动深挖锚点定位工程根，见下方「两类 Agent」） |
| `--count` | 否 | 5 | 测试集条数，范围 1~20 |
| `--input` | 否 | 空 | 生成要求（自由文本） |
| `--output` | 否 | `outputs/e2e-test-<时间戳>` | run 目录。**显式传入即原样使用**：不拼前缀、不加时间戳、不改名 |

### 你只需要做两步

**入口脚本会自己把全部确定性阶段跑完**（解析、解包、扫描、冻结画像、配额计算、
提示词产出、校验、落盘），并在**真正需要 LLM 出力的地方**停下来。所以你的循环是：

```
1. 运行 generate.py <参数>
2. 读它打印的「当前步骤」：
   ├─ 若写着「需要你出力」→ 按它列出的 .prompt.md 生成结果，
   │  写出同名 .answer.json（多个批次可交 Task 子 agent 并行）
   └─ 若写着「落盘完成」→ 结束，向用户汇报产出路径与退出码
3. 回到第 1 步，用它打印的续跑命令（带 --work）
```

**不要在 LLM 节点之外手工运行 parse.py / extract.py / plan.py 等脚本**——
`generate.py` 已经代劳。只有调试某一阶段时才单独运行它们。

续跑命令形如：

```bash
python3 <SKILL.md 所在目录>/scripts/generate.py \
  --work <run 目录>/generated_datasets/.work --count <值>
```

首次运行时 `--agent` / `--count` / `--input` / run 目录位置会记录到中间态目录的
`run-args.json`，续跑可省略；`--count` 与 `--input` 也会自动沿用，不必重复传。
**产出位置只认这份记录**，所以续跑时 `--work` 指到哪都不影响交付物落在哪。

## 两类 Agent

被测 agent 有两类工程布局，**锚点文件名**决定按哪套解析：

| 类型 | 锚点 | 工具面 / 入口 / 规则 |
|---|---|---|
| COSIGHT 类 | `COSIGHT.md` | `.cosight/{settings.json, skills/*/SKILL.md, rules/*.md}` |
| Claude 类 | `CLAUDE.md` | `.claude/{settings.json, skills/*/SKILL.md, rules/*.md}` |

- **深挖**：在 `--agent` 指向的路径及其全部子目录里找锚点，因此指到版本号子目录
  （`.../v1`）或工程根之上的一层都能正确定位。
- **Claude 类必须自带 `.claude/`**：只有 `CLAUDE.md`、目录里却没有 `.claude/`
  的，不认作 Claude 类工程（否则会把调用方自己的全局配置布局误当被测对象），
  按「无锚点」回退并在报告中告警。
- **双锚点**：同一目录下两种锚点并存时取 `COSIGHT.md` 并在报告里告警。
- **多工程**：若深挖到两个以上不同位置的锚点，报错要求明确指向，不猜。
- **无锚点**：回退以 `--agent` 自身为根，flavor 记为「未识别」，并在报告中警示。

报告与 `agent-profile.json` 都会标明识别的类型；两种类型的产出 schema 完全一致。

## 六阶段流水线

按实际执行顺序（`↻` 表示该脚本会跑两次，中间夹一次 LLM 出力）：

| 阶段 | 执行者 | 产物 |
|---|---|---|
| S0 输入解析 | `parse.py` | `00-asset.json` |
| S1 画像抽取 | `extract.py` | `10-profile-input.json` + `11-merge.prompt.md` |
| S1 能力点归并 | **你** | `11-merge.answer.json` |
| S1 冻结画像 | `freeze_profile.py` | `12-agent-profile.json` |
| S2 归类提示词 | `tag.py` | `20-tag.prompt.md` |
| S2 验收条目归类 + 重点解析 | **你** | `20-tag.answer.json` |
| S2 计划规划 | `plan.py` | `20-plan.json` |
| S3 提示词产出 | `prompts.py` | `30-gwt.prompt.md` / `30-batch-*.prompt.md` |
| S3 用例生成 | **你** | `30-*.answer.json` |
| S4 校验补生成 | `verify.py` ↻（有缺口时） | `40-verified.jsonl` / `41-verify.json` |
| S4 补生成 | **你**（有缺口时） | `31-repair-*.answer.json` |
| S5 落盘 | `emit.py` | 5 件交付物 + `50-emitted.json`（落盘标记） |

S2 拆成两个脚本：`tag.py` 只负责**问**（渲染归类提示词并定义答案 schema），
`plan.py` 只负责**算**（截断、加权、配额分配，零 LLM 调用）。无验收基线时
`tag.py` 自动跳过，不产生任何提示词。

**纯代码负责的部分**（你不要插手计算）：输入解析、解包、识别矩阵扫描、
验收基线截断、权重与配额分配、硬校验、去重、覆盖度检查、落盘。

**需要你出力的部分**：只有三处——能力点归并、验收条目归类 + 生成重点解析、
用例生成（含补生成）。这些地方脚本会产出 `.prompt.md`，你按其中的 schema 写出
同名 `.answer.json`（`.prompt.md` → `.answer.json`，文件名一一对应）。

### 写 answer 文件的规则

1. **只输出 JSON**，无解释、无 markdown 围栏。
2. `input` 必须自包含、可独立复现，**不得引用「上文」**。
3. `expected_output` 必须是**可判定要点**（字符串数组），不写「合理即可」类模糊表述。
4. `capability_ref` 必须是画像能力点清单里的 id 之一；档 C（无能力点）时**不要输出该字段**。
5. 不得与 `.prompt.md` 里「禁止重复素材」段的内容重复或近义改写。
6. 多个批次可用 Task 子 agent 并行处理（无强制并发要求，脚本不感知并发）。

**`30-gwt.answer.json` 额外要求 `gwt_index`。** 一条验收条目可以拆成多条用例（例如
同一条 `acceptance_criteria` 覆盖多种非法输入），每条都要填来源条目在列表中的序位。
脚本按它归属维度与 `source_ref`；缺该字段时按答案序位回退，序位超出保留条数的那条
会被**驳回**，不再默认归到第一个维度。

## 产出

落盘到 **run 目录**下的 `generated_datasets/`。run 目录默认是
`./outputs/e2e-test-<时间戳>/`（相对调用方 cwd），也可由 `--output` 指定。

```
outputs/e2e-test-20261014-101530/   ← run 目录（--output）
└── generated_datasets/
    ├── .work/                          ← 中间态，S0 就建好，摊平放
    │   ├── run-args.json               ← 参数 + 本轮 run 目录位置
    │   ├── 00-asset.json
    │   └── 50-emitted.json
    ├── seed.jsonl                      ← 5 件交付物，S5 落盘到此
    ├── agent-profile.json
    ├── eval-plan.json
    ├── manifest.json
    └── report.md
```

`<agent 名>` 的推导分两种，**共用同一个 slug 函数**（`common.naming_slug()`），因此两种口径内部
各自一致：

| 用途 | 取值 |
|---|---|
| `data_id` 前缀、`task_id` | **`project_id` 优先**（COSIGHT.md / CLAUDE.md 元数据表里工程自报的规范名）；缺失或 slugify 后为空时回退到路径推导 |
| run 目录默认名 | **只按 `--agent` 路径推导**（叶子是版本号目录如 `.../v1` 时退回父目录名，压缩包先去掉扩展名） |

run 目录单独走路径推导是刻意的：S0 建目录时画像尚未生成，拿不到 `project_id`。因此
**run 目录名与 `data_id`/`task_id` 可能不同名**。

`task_id` 是 `<agent 名>_<时间戳>`，写进 `manifest.json` / `50-emitted.json` / `report.md`。
它**与 run 目录名解耦**：显式传 `--output` 时目录可能叫任意名字，而 `task_id` 仍按上面这套
推导——时间戳由 S0 生成一次，记进 `run-args.json`，三处共用。

```
seed.jsonl            测试集（kind=seed）
agent-profile.json    画像：能力点 / 工具 / 边界 / 验收基线 / 引擎 / 已排除文件
eval-plan.json        评测计划：维度权重、配额、覆盖矩阵、来源统计
manifest.json         溯源：输入指纹 / 参数 / 时间戳 / 各产物 sha256
report.md             人读报告
```

`seed.jsonl` 单条记录：

```json
{"data_id":"<agent 名>_<dimension>_<seq>","kind":"seed","dimension":"functional",
 "capability_ref":"C01","source":"gwt|llm","source_ref":"clarified-agent-requirements.yaml#1",
 "input":"...","precondition":"...","expected_output":["要点1","要点2"]}
```

`source="gwt"` 的条目物化自验收基线：`<--agent>/.agent-genesis/work/<agent>/agent-creation/`
下的 `clarified-agent-requirements.yaml` 中 `acceptance_criteria` 列表（`#N` 即列表序位）。
**只从 `--agent` 本身拼接查找，不向上回溯**；归档输入以解包根为起点。该文件缺失、
字段为空或条目缺 `given`/`when`/`then` 时按无基线处理并在报告中告警。

`capability_ref` 在档 C（画像抽到 0 能力点而降级）时**整个键不出现**——
不是空字符串，是键本身不存在。

**退出码**：`0` 正常；`1` 有缺口（按实际条数落盘）或前置失败。

**中间态一律保留**在 `generated_datasets/.work/` 下（含落盘后），供复核与排查；
落盘成功会写入 `50-emitted.json` 标记。

**重跑不复用旧结果**。run 目录每轮一个，产物位置只有两种来源：

| 调用 | 语义 | run 目录 | 中间态目录 |
|---|---|---|---|
| 带 `--agent`、无 `--output` | **开新一轮** | 新建 `outputs/e2e-test-<时间戳>` | 其下 `generated_datasets/.work/` |
| 带 `--agent --output D` | **开新一轮** | 用 `D`，原样；`D` 不存在就连同 `.work/` 一起建 | `D/generated_datasets/.work/` |
| 带 `--work` | 同一轮**续跑** | 读 `run-args.json` 记录的，忽略 cwd | 用给定目录，保留已填答案接着往下走 |

**同一 run 目录再开一轮会被拒绝**，判定是 `.work/` 里有没有文件：

- 有 `50-emitted.json` → 报错「已跑完」，打印落盘时间与条数
- 有其他文件 → 报错「已有未完成的进度」，打印停在哪个阶段，并给出两条出路：
  接着跑用 `--work <该目录>`，重跑先 `rm -rf <run 目录>`
- `.work/` 为空（S0 建完就崩留下的空壳）或不存在 → 放行

报错而非静默避让是刻意的：`--output` 是用户自己写的路径，改个名再跑会让人
以为跑对了。

`--output` 与 `--work` 同时给出时校验一致——指向同一 run 目录算重复声明，放行；
矛盾则报错。`--work` 指向的目录若没有 `run-args.json`（旧的、或手工建的），
因无法确定产出位置而报错，提示用 `--agent` 开新一轮。

**为什么续跑必须复用同一目录**：一轮需要多次调用才能走完——每个 LLM 节点
（能力点归并、验收条目归类、用例生成）都由主 agent 读提示词、写答案，然后再次调用
推进。所以 `generate.py` 每次打印的续跑命令都带 `--work <该轮中间态目录>`，
照着跑即可。

## 维度骨架

| id | 名称 | 权重 |
|---|---|---|
| `functional` | 功能正确性 | 3 |
| `tool_use` | 工具调用正确性 | 3 |
| `boundary` | 边界与鲁棒性 | 2 |
| `instruction` | 指令遵循与输出格式 | 2 |
| `safety` | 安全与越权边界 | 2 |
| `failure` | 异常与降级 | 2 |

`--input` 里明确提到的方向会**抬权重**（软偏置，六维全保留），不会删维度。

## 三约束（向用户转述时不可含糊）

1. **不造假**：用例只来自被测 Agent 的真实能力声明与验收基线（`clarified-agent-requirements.yaml`
   的 `acceptance_criteria`）；抽不到就如实降级，不编造能力点。
2. **缺口不静默**：条数未达标时按实际落盘 + 退出码 1 + `report.md` 顶部醒目告警。
3. **只读被测对象**：全程不修改被测 Agent 的任何文件；解包只发生在临时中间态目录。
