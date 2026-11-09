---
name: e2e-test-runner
description: "读取 e2e-test-generator 产出的 seed.jsonl，按并发数调度 claude -p 逐条执行，收集会话数据并把执行结果回写进原始用例。"
---

# agent-eval — 评测集执行

读取上一环节生成器落盘的测试集，逐条喂给被测 Agent 并记录执行结果。

## Argument handling — IMPORTANT

This skill takes arguments. If `$ARGUMENTS` is provided, use it. Otherwise check the
conversation.

**参数原样透传，没有子命令**。Claude Code 的斜杠命令不能可靠转发参数，因此把
`$ARGUMENTS` 完整交给入口脚本：

```bash
python3 <SKILL.md 所在目录>/scripts/run_tests.py \
  --input <值> --output <值> --agent <值> --concurrency <值>
```

四个参数**全部可选**，不传则走默认：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--input` | `outputs/` 下目录名倒序第一的 `e2e-test*` | seed.jsonl 来源。可指 **run 目录** / **generated_datasets 目录** / **seed.jsonl 文件**三种形态 |
| `--output` | 解析出的 `--input` 所在的同一个 run 目录 | 产物落其下的 `run_datasets/`。**给的是 run 目录，不是 `run_datasets/` 本身** |
| `--agent` | 读输入侧 `manifest.json` 的 `agent_root` | 被测 agent 根目录，也是**每用例副本的复制源**（只读，会话实际跑在副本里） |
| `--concurrency` | `1` | 并发数，范围 1~32 |

主 agent 只需**运行脚本、转述结果**——探测、调度、回写全在脚本里，没有需要 LLM
出力的环节（这一点与生成器不同：生成器有三处 `.prompt.md` → `.answer.json`，
需要主 agent 反复介入；runner 一次跑完即交付）。

## 四步流程

按实际执行顺序。**每一步都已由 `run_tests.py` 代劳，不要手工执行**：

| 步骤 | 执行者 | 动作 |
|---|---|---|
| 1 | `run_tests.py` | 解析 `--input`，定位并读取 `seed.jsonl` |
| 2 | `run_tests.py` | `--agent` 为空时读输入侧 `manifest.json` 的 `agent_root`，比对树哈希 |
| 3 | `run_tests.py` | 按 `--concurrency` 并发调度 `claude -p` 执行每条用例（各跑在自己的副本里） |
| 4 | `run_tests.py` | 把该会话的日志拷进用例目录的 `sessions/` |
| 5 | `run_tests.py` | 把执行结果写回记录，并把 seed.jsonl 落盘到 `<output>/run_datasets/` |

**刻意不做**：行为分析、阶段检测、产物快照、`report.md`。这些是 `run_e2e.py`
（AgentGenesis 专用）的职责，与本 skill 的通用 seed 契约解耦。`run` 字段只承载
**执行状态**与**会话归档线索**，评测（对 `expected_output` 的判定）留给下游环节。

> `run_e2e.py` 走的是另一条路：共享 cwd + 前后快照比对副作用（`take_side_snapshot`
> / `diff_side_effects`），把"agent 改了什么"记下来。本 skill 反过来——用每用例副本
> 让它**改不到**源目录，因此不需要副作用快照。两种契约并存，不要互相套用。

## 执行契约

每条用例如下 spawn 一个独立会话：

```bash
claude -p --permission-mode bypassPermissions --output-format json --session-id <uuid4>
```

| 项 | 约定 |
|---|---|
| **cwd** | **该用例自己的 `agent_root` 副本**——`<output>/run_datasets/{data_id}/workspace/`，用例之间互不可见 |
| **stdin** | **只喂 `case.input`**。`precondition` 不入 prompt（其中常含答案原文，如待检出的明文凭据） |
| **env** | 追加 `CLAUDE_CODE_DISABLE_NONWHITELISTED_MCP=1`，屏蔽非白名单 MCP |
| **超时** | 默认 600s；seed 记录带 `timeout` 字段时以它为准（当前生成器不产该字段） |
| **会话 id** | 由 runner **预生成** uuid4 并经 `--session-id` 传入，不是从 result 里读的（原因见下节） |

**没有 `--no-session-persistence`**。该 flag 会让会话不落盘：`session_id` 照常有值，
但磁盘上找不到任何日志（已实测确认）。带上它，日志拉取 100% 落空。

### 隔离模型

每个用例跑之前，跑一遍 `shutil.copytree(agent_root, <case>/workspace)`，会话的 cwd
指向这份副本。因此：

- **用例之间互不可见**：A 写的报告不会出现在 B 的工作目录里；
- **源目录只读**：被测 Agent 的产物全部落在副本内，`agent_root` 跑完仍是原样
  （可用 `sha256_tree` 前后比对验证，这正是隔离的直接判据）；
- **并发安全**：副本彼此独立，`--concurrency >1` 不再互相覆盖；
- **重跑干净**：进用例前旧副本整目录删除再复制，所以"重跑"必然从干净起点开始，
  哪怕你只删了 seed 记录里的 `run` 字段、没删用例目录。

副本**保留**在用例目录下（不自动清理），供事后查看该用例实际写了哪些文件。
代价：磁盘占用从 O(1) 变为 **O(N × agent_root)**。

两个前置约束，违反会直接报错退出：

- **产物目录必须落在被测目录之外**。副本在产物目录之下，若产物目录在
  `agent_root` 内部（例如 `--agent .` 且 `outputs/` 在工程里），复制会无限递归。
- **源目录被写脏只告警、不阻断**。startup 会比对 `agent_root` 的实算树哈希与生成器
  `manifest.json` 里的 `agent_sha256`；不一致说明上次生成之后源目录被写过（典型是
  上一轮评测留下的报告文件）。此时残留会被**原样复制进每一份副本**——隔离了用例
  之间，却把污染固化成共同起点，所以必须提醒；但不拦：你可能是改了 agent 想重测。
  实算哈希记进 `run-manifest.json` 供追溯。

### 会话日志归档

每个用例跑完后，把该会话的日志从 CLI 的落盘位置拷进用例目录的 `sessions/`。
CLI 按 cwd 分目录落盘，本机有两个配置根（`~/.claude`、`~/.cosight`），
所以搜索根是 `~/.*/projects`，命中两种同名的形态：

```
<projects>/<cwd 编码>/<session_id>.jsonl               主会话（文件）
<projects>/<cwd 编码>/<session_id>/subagents/*.jsonl   子代理（目录）
```

**id 由 runner 预生成并经 `--session-id` 传入**，而不是从 `result.json` 里读。
这不是风格选择：`--output-format json` 是**最后一次性**吐出的，超时被 kill、
stdout 无法解析、CLI 缺失这三种场合根本拿不到 result——而会话日志是**增量落盘**
的，那会儿早就躺在磁盘上了。靠 result 反推 id 的话，最需要 trace 的失败用例
反而一个日志都拿不到。预生成的 id 另有一层好处：并发下不可能串号。

由此得到一条硬约束：**`--no-session-persistence` 不能加回来**。加了之后
`session_id` 照常有值，但磁盘上什么都没有，归档会 100% 落空。

日志缺失**不改 `status`、不改退出码**：`status` 归被测 Agent（跑没跑成，由
`exit_code` 派生），`session_error` 归评测基建（日志录没录到）。把基建故障算进
退出码，等于让答对的 Agent 背锅，还会污染下游的通过率口径。缺失只在 Run Summary
里计数并往 stderr 发一条 WARN。

## 产出

```
<output>/
└── run_datasets/
    ├── seed.jsonl                  ← 原字段 + run 子对象
    ├── run-manifest.json           # 环境记录：agent_root / 期望与实算哈希 / 隔离模式
    └── {data_id}/
        ├── stdout.txt              # CLI 完整标准输出（空则空文件）
        ├── stderr.txt              # CLI 完整错误输出
        ├── result.json             # claude -p --output-format json 的解析结果
        ├── timing.json             # {elapsed_seconds, exit_code, timed_out}
        ├── sessions/               # 该会话的 CLI 日志归档（可能缺席，见 session_error）
        └── workspace/              # 该用例的 agent_root 副本（是工作目录，不是结果产物）
```

`workspace/` 是会话真正的工作目录，里面是**被测 Agent 跑完后的目录状态**——报告、
缓存之类都在其中。读产物请认上面那 4 个文件，不要把 `workspace/` 里的东西当结果
（判定 `expected_output` 时它常是重要证据，但语义上属于"输入环境的镜像"）。
`sessions/` 则是会话**过程**的记录，供下游 `traceaudit` 做轨迹评测。

`{data_id}` 用例目录名直接取自 seed 记录的 `data_id`（如
`明文密码智能体_functional_001`）。它含路径分隔符时脚本会报错拒绝，不会写出目录外。

`result.json` 有三种形态：

| 情形 | 内容 |
|---|---|
| 合法 JSON | claude 的完整 JSON 输出，原样落盘 |
| 半截 JSON（超时被 kill） | `{"partial_result": true, "extracted_text": "..."}`，从截断处抢救 `result` 字段 |
| 无法解析 | `{"parse_error": true, "raw": "<完整 stdout>"}` |

三种形态都保存完整文本，不设长度上限。stdout 为空时**不产生** `result.json`——
空壳文件比缺席更误导。

### 回写 schema

原记录字段**一字不改**，结果挂在新增的 `run` 子对象下：

```json
{"data_id": "明文密码智能体_functional_001", "kind": "seed",
 "dimension": "functional", "capability_ref": "C01",
 "input": "...", "precondition": "...", "expected_output": ["..."],
 "run": {
   "status": "passed",
   "exit_code": 0,
   "elapsed_seconds": 12.3,
   "timed_out": false,
   "result_preview": "<result 全文，不截断、不改写>",
   "case_dir": "/abs/path/to/<run 目录>/run_datasets/明文密码智能体_functional_001",
   "workspace_dir": "/abs/path/to/<run 目录>/run_datasets/明文密码智能体_functional_001/workspace",
   "session_id": "f7078c0b-fddb-4450-8cba-ad8b8cb43395",
   "session_dir": "/abs/path/to/<run 目录>/run_datasets/明文密码智能体_functional_001/sessions"
 }}
```

`case_dir` 是用例目录（5 件产物所在处），`workspace_dir` 是该用例的副本目录
（会话的 cwd）。两者都是绝对路径。用例崩在"复制副本"这一步时副本可能根本没建成，
但 `workspace_dir` 键仍会出现——照着路径找不找得到，以 `status` 和 `error` 为准。

会话三项：

| 键 | 出现条件 | 说明 |
|---|---|---|
| `session_id` | **恒出现** | runner 预生成的 uuid4。日志的钥匙，补拷靠它；下游 `traceaudit` 也要 |
| `session_dir` | 日志确实拷到 | `sessions/` 的绝对路径 |
| `session_error` | 日志没拷到 | `not_found`（磁盘上没有）或 `copy_failed: <细节>` |

`session_dir` 与 `session_error` **互斥**：成功的判据是 `session_dir` 在、
`session_error` 不在。两者都不改 `status`——理由见上节。

`status` 取值：

| 值 | 条件 |
|---|---|
| `passed` | `exit_code == 0` |
| `timeout` | 超过单用例超时（`exit_code` 为 `null`——进程被 kill，没有自己的退出码） |
| `failed` | 其余（含 CLI 不存在 → `exit_code` 127） |

用例执行过程本身崩溃（非被测 Agent 失败）时额外带 `run.error`，该条记 `failed`，
**不中断整轮**；其余用例照常跑完。

`run.error` 与 `run.session_error` 刻意分开：前者是"会话没跑起来"，后者是
"跑起来了但日志没录到"。前者影响 `status`，后者不影响。

## 只读输入

`--input` 指向的那份 `seed.jsonl` **只读**，全程一个字节都不改——它是生成器的
交付物，有 `manifest.json` 里的 sha256 存证。结果只写 `<output>/run_datasets/seed.jsonl`
这一份副本。

`--output` 若解析出会覆盖 `--input` 的 seed（即 `--input` 直接指向某个
`run_datasets/seed.jsonl`，`--output` 又指回它的上一层 run 目录），脚本报错拒绝。

## 续跑

**已带 `run` 字段的用例会被跳过**，只跑剩下的。每跑完一条就把结果刷回
`<output>/run_datasets/seed.jsonl`，因此中途中断不会丢已完成的结果。

续跑要求两次的用例集合（`data_id` 序列）完全一致，否则报错——避免把两份不同的
测试集混进同一份结果里。要换测试集先删：

```bash
rm -rf <output>/run_datasets
```

**没有强制重跑的 CLI 参数**。要让某条用例重跑，从
`<output>/run_datasets/seed.jsonl` 里删掉该条的 `run` 字段即可：

```bash
# 删 "run" 字段（用例目录可留可删）
```

> 用例目录不用手工删：进用例前旧 `workspace/` 与旧 `sessions/` 都会被整目录删除
> 重建，所以重跑必然从干净起点开始，结果可复现。`stdout.txt` 等产物会被覆盖。
>
> `sessions/` 也要擦，是因为重跑会生成**新的 session_id**；不擦的话新旧两份会话
> 会并排躺在目录里，而 `run.session_dir` 只指得到目录本身，光看目录分不出哪份
> 属于本轮。

### 补拷会话日志

续跑时会顺带处理"**有 `run` 但缺 `session_dir`**"的记录：拿记录里的 `session_id`
重新搜一遍日志，找到就补进 `sessions/` 并补写 `session_dir`。

这是拷贝失败后的**唯一补救路径**。续跑契约是"已带 `run` 的用例会被跳过"，于是
拷贝失败的用例永远等不到第二次机会——而重跑整条既花一次 API 费用、答案还可能
不同、历史结果也没了，可你要的只是一份本就躺在磁盘上的日志。

补拷**只动会话三项**：`status` / `exit_code` / `elapsed_seconds` 是被测 Agent 的
既成结果，不该因为事后补录日志而变化。

> 0.1.0 留下的旧记录没有 `session_id`（那一版开着 `--no-session-persistence`，
> 日志压根没落盘），补拷会按"拿不到钥匙"跳过，不会去猜。要日志只能重跑。

**退出码**口径是**整份 seed.jsonl 的最终结果**，而非本轮新跑的部分：
`0` = 无 `failed` 且无 `timeout`；`1` = 有其一。因此续跑时旧轮次遗留的失败仍会让
退出码为 1。**会话日志缺失不计入退出码**——它只在 summary 里计数并往 stderr
发 WARN（理由见"会话日志归档"一节）。

## 报错而非静默避让

以下情形一律报错退出（退出码 1），不猜、不回退：

- `--input` 解析不出 seed.jsonl（目录下没有、文件名不对、路径不存在）
- 缺省 `--input` 时 `outputs/` 下没有任何 `e2e-test*` 目录
- `--agent` 为空且输入侧没有 `manifest.json`，或其中没有 `agent_root` 字段
- `manifest.json` 里的 `agent_root` **路径不存在**——它指向生成中途解包出来的
  中间态（`.work/extracted/...`），run 目录被清理或换机器后就失效。此时提示显式
  传 `--agent`，而不是退到别的目录：用例的 precondition 引用了相对路径的 fixture，
  跑在错的根上会让全部用例假失败，比报错危险得多
- seed 记录缺 `data_id` / `input`，或 `data_id` 含路径分隔符
- `--concurrency` 越界
- **`--output` 指向的产物目录落在 `--agent` 内部**——副本在产物目录之下，会让
  `copytree` 无限递归地复制自己。这条在 startup 早失败，而不是等每条用例各自崩

## 测试

```bash
python3 -m pytest <SKILL.md 所在目录>/tests -q
```

不依赖真实 `claude` CLI——测试通过 monkeypatch `subprocess.Popen` 打桩。会话日志
也一并打桩：`conftest.py` 有个 autouse fixture 把 `config.SESSION_LOG_GLOBS` 指到
临时目录，**任何测试都不会去扫真实的 `~/.claude`**（否则既慢又不密闭，还会把开发者
自己几百份会话日志当数据源）。要验证"日志确实归档"的用例把该 fixture 作为参数取到
路径，再用 `test_run.write_fake_session_log` 造一份假日志即可。

## 与 AgentGenesis 那份的关系

`agent-genesis/skills/e2e-test-runner/` 是同名的另一个 skill，走的是**另一套契约**
（`run_e2e.py`：共享 cwd + 前后快照比对副作用，产物落 `report_dir/sessions/{id}/`，
结果写平级键而非 `run` 子对象），**没有**会话日志拉取。本 skill 的 `run.session_dir`
与它的平级 `session_dir` 不是一回事，不要互相套用。
