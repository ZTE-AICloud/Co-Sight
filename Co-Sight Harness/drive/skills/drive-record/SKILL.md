---
name: drive-record
description: Use when a user wants to review a completed /drive execution — pass a plan_dir to produce a human-readable REPORT.md timeline with gap detection surfaced inline in §B, or a self-contained HTML replay (via generate_report.py) for browser-viewable timeline + artifacts. Triggers on phrases like "复盘 drive 执行", "drive 跑完看下结果", "/drive-record", "REPORT.md", "看下这次 drive 哪里有问题", "drive 复盘 HTML".
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py --plan-dir *)
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py --plan-dir * --cwd *)
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py --plan-dir * --session *)
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/generate_report.py --plan-dir *)
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/generate_report.py --plan-dir * --out *)
---

# /drive-record

用户调 `/drive-record <plan_dir>` 时执行：拼装一次 drive 执行的**多源回放** —— 把执行事实合到一份 `REPORT.md` 给用户看（"完整过程"长什么样，gap 检测结果内嵌在 §B）。**只读**，不改 drive runtime。

drive-record 默认拼 3 类来源；任何缺失按 gap 报告（不静默吞）：

1. **drive runtime 记录**（`.drive/<plan_dir>/`）—— 文件 + run-log 事件流 + state machine 状态；这是 drive 的 runtime contract 真相。
2. **chat session json**（`~/.claude/projects/<cwd-hash>/<sid>.json`）—— agent 之间说过什么；cwd-hash 未文档化，找不到时静默 skip（用户可 `--session <id>` 显式覆盖）。

CLI 已经做了 90% 的工作 —— 多源拼装、timeline 合并、gap 检测、envelope 输出。Claude 的工作是：**解析参数 → 调 CLI → 把 envelope 渲染成用户能秒懂的 SUMMARY**。

## 步骤

### 1. 解析 plan_dir

用户**必须**给 `<plan_dir>` 路径（cli.py `--plan-dir` 必填）。

| 情况 | 动作 |
| --- | --- |
| 用户给了路径 | `Path(arg).expanduser().resolve()` 取绝对路径；允许 `.drive/<name>` 形式 |
| 路径不存在 | **不要调 CLI**。告诉用户「路径不存在，请确认是 `.drive/<plan_dir>/`」 |
| 路径是 `plan-<id>` 但当前 cwd 是项目根 | 自动加 `.drive/` 前缀再 resolve 一次 |

`.drive/` 默认在用户项目的 cwd 下；不是绝对路径时需先确认 cwd。

> **省略 plan_dir 自动查找（`.current-plan` / mtime 扫描）尚未实现**：SKILL 描述过的"用户不给路径 → 找最近 plan"是 plan，cli.py 现在强制必填。如要支持，得在 cli.py 加 fallback + 扩 `allowed-tools`（读 .drive/.current-plan + ls mtime）。

### 2. 选择输出格式

| 用户意图 | 用哪个 |
|----------|--------|
| 默认（要看 gap 检测 + session 关联） | `cli.py --plan-dir <abs>` → SUMMARY 卡片 |
| 用户说 "HTML" / "浏览器" / "发个文件" | `generate_report.py --plan-dir <abs> --out <plan_dir>/.drive-replay.html` → 写 self-contained HTML |
| 用户要 Markdown 全文 | `cli.py --plan-dir <abs>` + 告诉用户 REPORT.md 路径 |

`generate_report.py` 是只读 HTML 回放器：Gantt timeline + gate marker + 关键事件 + artifacts + 底层文件。所有数据从 `.drive/<plan_dir>/` 真实文件读，CSS token 用过 drive-viz tokens（保证视觉一致）。

### 3. 跑 CLI（Markdown 路径）

调 `cli.py` —— frontmatter `allowed-tools` 已预授权该命令。**不要**直接调其它子脚本（依赖同目录模块路径，会破）。

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py --plan-dir <abs path>
```

可选参数（按需追加，不要默认全加）：
- `--cwd <cwd>`：当前 cwd 与调 drive 时不同（用户在另一个 worktree）→ 用于 §5 session 定位。
- `--session <id>`：Claude Code 的 cwd-hash 算法未文档化，§5 找不到 session 时让用户显式覆盖。

退出码：0 = 成功；1 = 失败。stdout 是 envelope JSON。

### 3. 渲染 SUMMARY（成功路径）

CLI 返回 envelope.data 含：

| 字段 | 来源 | 用法 |
| --- | --- | --- |
| `report_md` | `<plan_dir>/REPORT.md` 绝对路径 | 给用户报告位置 |
| `summary` | `{total, critical, high, medium, low}` | gap 数 |
| `session_path` | `~/.claude/projects/.../sid.json` 或 `null` | §5 session 关联 |
| `plan_name` | `run-meta.json.plan_name` 或 plan_dir 目录名 | SUMMARY 标识 |
| `mode` | `executeState.mode`（`phase` / `dag`） | SUMMARY 标识 |
| `completeness` | `{runtime_present, runtime_total, llm_present, llm_total}` | 完整度分数 |

渲染卡片（**不要直接 dump REPORT.md 全文，太长**）：

```
## /drive-record SUMMARY
- plan: <plan_name>
- mode: phase | dag
- completeness: Runtime <X/Y> + LLM <X/Y>
- gaps: total=N critical=C high=H medium=M low=L
- 报告: <plan_dir>/REPORT.md
- session: <~/.claude/projects/.../sid.json>（若已找到）
```

**渲染规则**：
- `critical > 0` → SUMMARY 顶部加 🚨 红字「CRITICAL gap 存在」
- `high > 0` → 末尾加 ⚠️「HIGH gap 存在；建议先翻 REPORT.md §B」
- session 路径没找到 → 静默不显示那行（CLI 已 silently skip）
- **不要复述 gap 详情** —— 让用户翻 REPORT.md §B，否则对话冗长

### 4. 失败路径

envelope `ok=false` → 显示 reason（人话）+ details（机器细节）。常见：

| `reason` | 给用户的话 |
| --- | --- |
| `invalid_arg` | `--plan-dir` 不存在或不是目录；让用户重给 |
| `write_failed` | plan_dir 无写权限；让用户检查 |
| `internal` | 子模块 bug；附 details 段错误信息 |

## 数据源

drive-record 的真相从 3 个来源拼出，每个角色不同、缺时表现也不同：

| 来源 | 角色 | 缺时 |
| --- | --- | --- |
| `.drive/<plan_dir>/`（runtime 记录） | drive runtime contract 真相 —— 阶段流转、agent spawn/complete、verdict、files_changed、revision。文件本身分两组：Runtime SDK 通道产物（run-meta.json / intent.md / waves.yaml / topo-state.json / executeState.json / run-log.jsonl，6 个）由 drive runtime 强保证；LLM 契约产物（manifest.md / taskRecord.yaml / evaluation/verification-report.md，3 个）靠对应 LLM agent 自觉写 | Runtime SDK 产物缺 → `missing_file` HIGH gap；LLM 契约产物缺 → `missing_file` LOW gap；事件缺 → `missing_event` HIGH/MEDIUM gap |
| chat session json | agent 之间对话的真相 —— user gate 的 prompt 内容、各 agent 输出 | cwd-hash 算法未文档化 → 静默 skip；用户可 `--session <id>` 显式覆盖 |

**关键**：任何**默认**来源缺失都不会让 drive-record 退出；缺的事实会**作为 gap 显式报告**。这样用户能看到「这次回放缺了什么」，而不是以为「drive-record 全看到了」。

## Examples

### 完整 plan_dir

**用户说：** `/drive-record /path/to/proj/.drive/plan-20260818-0930-fix-import-deadlock`

**动作：**
1. 解析 plan_dir = `/path/to/proj/.drive/plan-20260818-0930-fix-import-deadlock`（绝对路径，已存在）
2. 调 `cli.py --plan-dir /path/...`
3. envelope.ok=true，data.summary={total:3,critical:0,high:1,medium:2,low:0}
4. 渲染 SUMMARY：3 gaps / 1 HIGH / session 已关联
5. HIGH>0，末尾加 ⚠️ 提示用户翻 §B

**结果：** 用户看到 SUMMARY 卡片 + 路径，HIGH gap 详情在 REPORT.md §B。

### 省略 plan_dir（cwd 下 .drive/ 有 current-plan 指针）

**用户说：** `/drive-record`（无参数）

**动作：**
1. 读 `<cwd>/.drive/.current-plan` → 拿到 `plan-20260818-0930-fix-import-deadlock`
2. 拼接为 `<cwd>/.drive/plan-...`
3. 调 cli

**结果：** 不用问用户，直接跑。

### 错路径

**用户说：** `/drive-record /tmp/nonexistent`

**动作：**
1. 解析 → 路径不存在
2. **不调 cli**。直接告诉用户「路径不存在；请确认是 `.drive/<plan_dir>/`」

**结果：** 0 次 cli 调用；节省 token。

### CRITICAL gap 出现

**用户说：** `/drive-record .drive/plan-x`

**动作：**
1. 解析 → cli 跑成功
2. summary={critical:1,high:0,medium:0,low:0}
3. 渲染 SUMMARY：🚨 顶部加红字「CRITICAL gap 存在」
4. 提示用户「先看 §B 的 `revision_gap` 类型 gap」

**结果：** 用户被引导去看 schema drift / 锁失效信号。

## Gotchas

- **CRITICAL > 0 → 顶部红字**（不能藏末尾）：drive-record 的核心价值就是暴露 schema drift / 锁失效信号。
- **HIGH > 0 → 末尾 ⚠️**：温和提示即可，不抢戏。
- **不要直接读 plan_dir 内 runtime 记录文件**：CLI 已做；重复读会绕开 gap detector 的单源逻辑，破坏一致性。
- **session 找不到 → 静默**：CLI 行为如此；Claude 不要主动解释「找不到 session」（噪音）。
- **`.drive/` 在 `.gitignore` 里**：REPORT.md 也不入 git；用户如要留档自行复制。
- **DAG vs phase 模式共用同一结构**：§0.1 / §2 标记 `mode=dag` / `phase`；SUMMARY 也带上 mode 字段。
- **省略 plan_dir 但 `.drive/` 空**：不要硬猜，AskUserQuestion 报错路径不存在。

## 参考（按需读）

Claude 调 cli 时不需要这些；改这个 skill / 调试时才看：

- `references/gap-catalog.md` —— 9 类 gap 严重度 + drive 修复点（修改 detector 时同步）
- `references/event-catalog.md` —— `run-log.jsonl` 事件类型清单（`_EVENT_TAG_MAP` 的镜像）
- `references/schema-fields.md` —— 9 个 runtime record 文件的字段定义（按 Runtime SDK + LLM 契约分组；`KNOWN_STATE_FIELDS` 的镜像）