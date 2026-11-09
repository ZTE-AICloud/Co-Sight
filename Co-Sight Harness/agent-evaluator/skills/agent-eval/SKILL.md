---
name: agent-eval
description: "一条命令跑完 Agent 评测全链：从 Agent 源码生成测试集 → 并发执行 → 逐条裁判评分 → 轨迹审计 → 汇总报告。需要「评测这个 Agent」「跑一轮评测」「生成测试集并跑分并出报告」时使用；只要其中某一段，用 e2e-test-generator / e2e-test-runner / e2e-test-evaluator / traceaudit。"
---

# agent-eval — Agent 评测全链编排

四段串行：**generate → run → eval → trace**，产物落在同一个 run 目录。本 skill 只做编排：

- 每段都用 **Skill 工具**进入上游，不直接调上游脚本；进入前先 `begin`。
- 唯一自有脚本是 `scripts/state.py`：只读写 `<run>/.state/`，只检查锚点存在性与哈希，不解析业务产物。
- **只有产物缺失才停**；上游退出码只进汇报，不进流程控制。
- 上游 SKILL.md 已给出的规则（写作规范、裁判禁令、批次屏障等）本文不重复。

## 参数

| 参数 | 默认 | 去向 |
|---|---|---|
| `--agent` | — | 必填。只给 generator，后续阶段不再传。 |
| `--count` | 5 | generator，范围 1~20。 |
| `--requirement` | 空 | generator 的生成要求（`--input`），抬高对应维度权重。 |
| `--output` | `outputs` | **父目录**，不是 run 目录。本轮一律新建 `<--output>/e2e-test-<时间戳>`。 |
| `--concurrency` | 1 | 同时给 runner 与 evaluator，范围 1~32。第四段顺序执行，没有此参数。 |
| `--resume` | 空 | 编排层续跑，给 run 目录；与 `--output` 互斥。见「续跑与对账」。 |

解析 `$ARGUMENTS`；未提供时看对话。本 skill 没有子命令。Skill 的 args 会替换正文中的 `$ARGUMENTS`（含表格与代码块），本文要引用它须写成 `\$ARGUMENTS`。

## run 目录

四个阶段必须落在同一个 run 目录：

```
<父目录>/                          ← --output，默认 outputs/
└── e2e-test-<YYYYmmdd-HHMMSS>/
    ├── .state/{state.json,events.jsonl}
    ├── generated_datasets/        ← generator
    ├── run_datasets/              ← runner
    ├── eval_datasets/             ← evaluator
    └── eval_trace_results/        ← traceaudit（目录名由上游拼出）
        ├── batch-summary.json
        ├── batch-summary.md
        └── cases/<data_id>/
```

传参约定：

- generator：`--output <run 目录>`
- runner / evaluator：`--input <run 目录> --output <run 目录>`
- traceaudit：`--seed-dir <run 目录> --outputs <run 目录>`

父目录取默认 `outputs/` 时，下游「倒序第一」的缺省匹配命中的就是本轮；父目录是其他路径时必须显式传参。
`--output` 是**父目录**。编排层每轮新建 run 目录，不复用旧目录，唯一例外是 `--resume`。

### 父目录校验

规范化路径后取最后一段，以 `e2e-test` 开头即报错（只按名字判定）：

```
--output 是父目录，不是 run 目录。
  收到：outputs/e2e-test-20261016-095720
  请传它的父目录：outputs/
```

若该目录含 `.state/state.json`，追加提示：`要续跑请改用：--resume <该目录>`。

### 创建与初始化

```bash
mkdir -p "<父目录>"
mkdir "<父目录>/e2e-test-<时间戳>"        # 不带 -p；已存在即报错停住
python3 <SKILL.md 所在目录>/scripts/state.py init --run-dir "<run 目录>" \
    --agent "<--agent>" --count <--count> --requirement "<--requirement>" \
    --output-parent "<父目录>" --concurrency <--concurrency>
```

第二条 `mkdir` 失败（同一秒内重复调用）直接报错，不改名、不加后缀。`init` 在进入第一段前完成；状态写失败就停住。

## 状态机

```bash
python3 <SKILL.md 所在目录>/scripts/state.py <子命令> --run-dir "<run 目录>" [选项]
```

每段四值，迁移严格线性：

```
pending|failed|running --begin--> running --complete--> done
                                        \--fail-----> failed
```

- 前序段未全部 `done` 时 `begin` 以退出码 2 拒绝。
- `running` 可再次 `begin`（中断后重入）；`done` 不能直接 `begin`。
- `failed` 只在「串接判据」的**停**分支设置。被测用例自身 `failed` / `timeout` 不改段状态。
- `status` 只读，输出 `next_action`（generate / run / eval / trace / report / blocked）。按它分流，不要自己推导。
- 退出码：`0` 成功；`2` 守卫拒绝（非法迁移 / 参数错配 / 前置缺失）；`1` 脚本自身错误。**2 不是故障，按原文转述并停住，不重试。**

### 锚点

每段一个锚点，`complete` 时要求它存在并记录 sha256：

| 段 | 锚点（相对 run 目录） |
|---|---|
| generate | `generated_datasets/seed.jsonl` |
| run | `run_datasets/seed.jsonl` |
| eval | `eval_datasets/report.md` |
| trace | `eval_trace_results/batch-summary.json` |

### 调用点

| 时机 | 命令 |
|---|---|
| `mkdir` 成功后 | `init --agent … --count … --requirement … --output-parent … --concurrency …` |
| 进入每段之前 | `begin --stage <段> [--input-path <本段所需输入>]` |
| 该段交付后 | `complete --stage <段> --exit-code <上游退出码> [--warning …]` |
| 命中「停」分支 | `fail --stage <段> --reason <上游原文错误>` |
| `--resume` 开场 | `reconcile [--agent … --count … --requirement … --concurrency …]` |

**先 `begin` 才能进 Skill。** 没有 `running` 状态就进入上游，中断后状态机无法指出从哪段续跑。

### 续跑与对账

`--resume` 给 **run 目录**，与 `--output` 互斥。校验顺序固定：

1. 目录存在且含 `.state/state.json`；否则拒绝（历史目录不支持续跑，不做收养或迁移）。
2. 冻结参数 `--agent` / `--count` / `--requirement` 必须与首轮一致，错配报错并给「开新一轮 / 只改并发」二选一。`--concurrency` 是唯一允许变化的参数，变化写 `resume.params_update`。
3. `reconcile` 按产物纠正状态：
   - `running` 且锚点已在 → 升级 `done`，`exit_code=null`，写 `reconcile.promote`。
   - `done` 但锚点缺失或哈希变化 → 降级 `pending`，并级联降级其后所有已完成段（下游产物基于旧输入），写 `reconcile.downgrade`。
   - 有降级时 `stop=true`、`next_action=blocked`，本次停在该段之前；再执行一次 `--resume` 才重跑。
   - 全部 `done` 且无降级 → `next_action=report`，直接读聚合产物出汇报。
4. 按 `next_action` 进入对应段。`running` 与 `failed` 都从该段重入，段内增量交给上游续跑契约。

**重跑已完成的段**：删除锚点 → `--resume`（降级并停住）→ 再 `--resume`（重跑）。第二条不能省，它把「产物没了」显式化。

## 四段流程

### 一、生成测试集

```
Skill(skill="e2e-test-generator",
      args="--agent <值> --count <值> --input \"<requirement>\" --output <run 目录>")
```

```bash
python3 <SKILL.md 所在目录>/scripts/state.py begin --run-dir "<run 目录>" \
    --stage generate --input-path "<--agent>"
```

载入后按 generator 的循环执行：

1. 运行 `generate.py`，读它打印的「当前步骤」。
2. 若写着「需要你出力」，按它列的 `.prompt.md` 写出同名 `.answer.json`。
3. 用它打印的续跑命令（带 `--work`）**再次通过 Skill 进入**；重复直到「落盘完成」。

多批次可用 Task 子 agent 并行，不强制。

**判定看 `generated_datasets/seed.jsonl`，不看退出码。** 退出码 1 可能是「有缺口但已写出」或「前置失败」；只有 seed 不在才停。

```bash
# seed.jsonl 在（退出码 0 或 1 都算交付）
python3 .../state.py complete --run-dir "<run 目录>" --stage generate \
    --exit-code <上游退出码> --warning "缺口：<实际条数>/<--count>"
# seed.jsonl 不在
python3 .../state.py fail --run-dir "<run 目录>" --stage generate \
    --reason "<上游原文错误>"
```

### 二、执行

```
Skill(skill="e2e-test-runner",
      args="--input <run 目录> --output <run 目录> --concurrency <值>")
```

进入前从 `generated_datasets/manifest.json` 取 `agent_root`，交给 `begin` 校验存在：

```bash
python3 .../state.py begin --run-dir "<run 目录>" --stage run \
    --input-path "<agent_root>"
```

该 skill 没有 LLM 环节，载入后一次跑完即交付。

- **编排层不传 `--agent`。** 让 runner 读 manifest 的 `agent_root`：generator 深挖后会定位到子目录，传原始路径会让用例的 fixture 相对路径全部假失败；压缩包输入时 `agent_root` 还指向解包中间态。
- `agent_root` 不存在（中间态被清理或换了机器）时 `begin` 以退出码 2 拒绝：提示用同一条命令重开一轮。不要转述 runner「请显式传 `--agent`」的建议，它在编排层有害。
- **退出码 1 不能停。** 它表示有 `failed` / `timeout` 用例，正是要看评分的时刻。会话日志缺失也不计入退出码。

runner 返回后一律 `complete`，退出码 1 照记：

```bash
python3 .../state.py complete --run-dir "<run 目录>" --stage run \
    --exit-code <上游退出码> [--warning "会话日志缺失：<n> 条"]
```

### 三、评分

```
Skill(skill="e2e-test-evaluator",
      args="--input <run 目录> --output <run 目录> --concurrency <值>")
```

进入前 `begin --stage eval --input-path "<run 目录>/run_datasets/seed.jsonl"`。载入后遵守它的三条硬约束：不自己读 `.prompt.md`、批次屏障、主 agent 不改分。

评分循环：

1. 进入 skill，它打印批次清单。
2. 按清单派裁判 Task；**每批同时发出，等整批返回**后再发下一批。
3. 全部完成后，用 Write 写 `<run 目录>/eval_datasets/judge.json` 登记裁判模型（`model` / `main_agent_model`）。
4. 再次进入同一个 skill，args 不变，聚合写出。

聚合完成即 `complete --stage eval`；有 `parse_error` 单列时用 `--warning` 记条数。

### 四、轨迹评测

```
Skill(skill="traceaudit",
      args="--seed-dir <run 目录> --outputs <run 目录>")
```

进入前 `begin --stage trace --input-path "<run 目录>/eval_datasets/seed.jsonl"`。

带 `--seed-dir` 时默认走批量，不需要写 `batch` 子命令；`validate` / `list` 本流程不调。该段纯确定性（L0 规则 + L1 结构检查），没有 LLM 环节。

- **`--seed-dir` 给 run 目录，不是 `run_datasets/`。** traceaudit 按 `<seed-dir>/eval_datasets/seed.jsonl` → `<seed-dir>/seed.jsonl` 查找，命中的是第三段产物。
- **`--outputs` 也给 run 目录。** 它在下面自己拼 `eval_trace_results/`，路径不受编排层控制。
- **不传 `--subagents-dir`**：runner 归档日志时已一并拷入 `sessions/`，省略时 traceaudit 自动解析到同一位置。
- **不传 `--timeout-ms`**：默认单条 600s，对实际量级（约 0.1s/条）没有约束力。
- **不并发**：批量模式逐条顺序执行，编排层的 `--concurrency` 只走前三段。

**退出码 1 表示「一条都没成功」**，不是「有失败用例」，照旧只进汇报。`batch-summary.json` 在就 `complete`（`succeeded=0` 也照记），不在才 `fail`。

「文件不在」只剩进程被外力打断（超时、Ctrl-C、机器挂了）这一种情形；常态失败表现为树在、条目全是 `status: failed`。逐条失败带 `stage`（`resolve` / `evaluate` / `collect`），最常见是 `resolve`——`run.session_id` 缺失或 `session_dir` 已不存在。

## 串接判据

| 阶段结束 | 动作 | 状态 |
|---|---|---|
| generate 有 `seed.jsonl` | 继续，退出码 1 也继续；缺口记入告警 | `complete` |
| generate 无 `seed.jsonl` | 停，打印上游原文错误 | `fail` |
| run 跑完 | 继续，不论 `failed` / `timeout` / 日志缺失多少 | `complete` |
| eval 跑完 | 继续，有 `parse_error` 单列也照常交付 | `complete` |
| trace 有 `batch-summary.json` | 继续，`succeeded=0` 也继续；失败原因记入告警 | `complete` |
| trace 无 `batch-summary.json` | 停，报上游原文错误，说明只剩半成品树 | `fail` |

**退出码不能当判据。** 按退出码决定流程，会在被测 Agent 表现差时中断，而那正是要看结果的时刻。第二段会话日志大面积缺失也照常进第四段：缺日志的用例记为 `failed`，不影响其余用例出分。

## 报错

| 情形 | 动作 |
|---|---|
| `--agent` 缺失 | 报错，提示参数格式。 |
| `--output` 最后一段以 `e2e-test` 开头 | 报错停住，提示应是父目录；含 `.state/state.json` 时提示改用 `--resume`。 |
| run 目录已存在 | 报错停住，提示稍后重试或换 `--output`。 |
| `--resume` 与 `--output` 同时给 | 报错停住，说明互斥。 |
| `--resume` 目录没有 `.state/state.json` | 报错停住，说明状态机只覆盖新轮次。 |
| 冻结参数与首轮不一致 | 报错停住，列出冲突值并给「开新一轮 / 只改并发」二选一。 |
| 对账发现产物缺失或被改写 | 降级 `pending`，`next_action=blocked`，本次停住。 |
| `agent_root` 不存在 | `begin` 以退出码 2 拒绝，提示重开一轮。 |
| 上游各自的 startup 校验 | 不重复，上游会早失败且报错更精确。 |

## 最终汇报

读 `<run 目录>/eval_datasets/report.md` 与 `<run 目录>/eval_trace_results/batch-summary.md`，不要只看退出码。

**结果分（eval）**：有效样本 N/M、通过率、加权平均分、`run_valid=false` 条数、`parse_error` 条数（有则单列）。

**轨迹分（trace）**：`succeeded` / `failed` 条数、平均总分、等级分布（`EXCELLENT` / `ACCEPTABLE` / `POOR` / `CRITICAL`）、五维均分（流程合规性、Skill 调用完整性、审查完整性、规则合规性、轨迹效率）、失败条目的 `stage` 分布。

**两段并排陈列，不要合成综合分。** 结果分量「对不对」，轨迹分量「过程规不规范」，量纲与阈值都不同；报告里要写明这条。

组合提示：

- eval 有效样本为 0（或 `run_valid=false` 占多数）时，**必须**注明：

  > 本轮结果分无效（环境未按 `precondition` 就绪）。下列轨迹分只反映 Agent 的过程行为，不代表任务完成度。

- 反过来，trace `succeeded=0` 时直接置顶告警，但照常交付；只报结果分，并说明轨迹分缺失的原因（通常是会话日志未归档或 `run.session_id` 缺失）。

全链告警：

| 来源 | 告警 |
|---|---|
| generate | 缺口：实际条数对比 `--count` |
| run | `timeout` / `failed` 条数、会话日志缺失数、源目录脏 WARN |
| eval | 无效样本、`parse_error` 条数、裁判重派次数 |
| trace | `succeeded=0` 置顶；失败条目的 `stage` 分布；`batch-summary.md` 的「警告」一节 |
| 四段 | 各自退出码与耗时 |
| state | 是否续跑、对账升降级、`--concurrency` 中途变更 |

状态机信息读 `.state/state.json` 与 `.state/events.jsonl`，并入上表。最后给出四段产物与 `.state/` 的路径。

## 明确不做

- 不做行为分析、副作用快照，不深挖 `workspace/` 里的产物；轨迹审计只看会话，不看工作目录残留。
- 不替上游做参数校验之外的判定：不改 seed、不改分数、不覆盖裁判结论、不改 traceaudit 的产物目录命名。
- 不给第四段加前置校验（`validate` 不解析 trace 坐标，抓不到日志未归档；逐条失败原因已在 summary 里）。
- 不做状态文件收养与迁移、不做并发锁；不记录段内子步骤状态（由上游增量契约负责）。

## 与四个上游的分工

| skill | 职责 | 产物 |
|---|---|---|
| `e2e-test-generator` | 造用例 | `generated_datasets/` |
| `e2e-test-runner` | 跑用例（每用例一份 `workspace/` 副本） | `run_datasets/` |
| `e2e-test-evaluator` | 判结果对不对 | `eval_datasets/` |
| `traceaudit` | 判过程规不规范（五维轨迹） | `eval_trace_results/` |
| 本 skill | 建 run 目录、串起四段、维护状态机、汇总判读 | run 目录与 `.state/` |

只要其中某一段就单独用那个 skill，它们的参数面更细（例如 runner 可单独指定 `--agent`）。
