---
name: state-machine
description: "Use when an agent needs to read or update drive's `.drive/<plan_dir>/executeState.json` (stage progress, plan-review gate, HITL flags). Triggers on '状态怎么读' / 'stage 推进' / 'state_cli update'. 跨 mode 通用 state 工具，phase 模式走 state_cli 命令。"
user-invocable: false
allowed-tools: Bash(python3 *state_cli.py*)
---

# State Machine

- **载体**: `.drive/<plan_dir>/executeState.json`（运行时状态，fcntl 锁 + revision 自增）。
- **谁写**: 履职完毕的 agent 自己汇报。编排层只读不写。
- **怎么写**: 只经本 skill 的 `scripts/`，不直接 Edit —— 加锁、原子写、留痕都在脚本里

## 写入通道

```bash
SC="${CLAUDE_SKILL_DIR}/scripts/state_cli.py"

python3 "$SC" read --planning-dir <dir>
python3 "$SC" require --planning-dir <dir>
python3 "$SC" update --planning-dir <dir> --set active_stage=analyze
python3 "$SC" transition --planning-dir <dir> --to <stage>
python3 "$SC" request-confirmation --planning-dir <dir> --stage <stage>
python3 "$SC" log --planning-dir <dir> --event stage_advanced --field to=analyze
```

| 脚本 | 职责 |
|------|------|
| `scripts/state_write.py` | `executeState.json` 读写，fcntl 排他锁，revision 单调自增，乐观并发校验 |
| `scripts/state_schema.py` | 阶段字段校验与越界字段剪除（字段定义见 `references/schema-fields.md`） |
| `scripts/audit_append.py` | `run-log.jsonl` 事件追加 |
| `scripts/envelope.py` | 上述脚本的统一返回协议 |
| `scripts/state_rules.py` | VALID_TRANSITIONS / STAGES / VERDICT_REQUIRED_TARGETS 权威定义 |

阶段流转权威定义见 `scripts/state_rules.py` 的 `VALID_TRANSITIONS` 表。

阶段列表（builtin STAGES）：start → analyze → plan → execute → evaluate → completed。

`transition` 子命令必须由 orchestrator 调用，前缀 `DRIVE_TRUSTED=1`：

```bash
DRIVE_TRUSTED=1 python3 "$SC" transition --planning-dir <dir> --to <stage>
```

无前缀时 hook 与 state_cli.py 自身均拒绝执行。
