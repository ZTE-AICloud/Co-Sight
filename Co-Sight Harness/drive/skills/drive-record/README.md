# drive-record

> **drive run 多源回放** —— 把一次 `/drive` 执行的事实拼成 `REPORT.md`，gap 检测内嵌 §B。
>
> user-invocable skill，仅在用户调 `/drive-record <plan_dir>` 时触发（`disable-model-invocation: true`）。

---

## 这是什么

drive-record 是 drive 的**只读回放工具**。用户调 `/drive-record <plan_dir>` 后：

1. 拼 3 类来源（runtime 记录 + 事件流 + chat session）成时间线
2. 跑 9 类完整性 / 一致性 gap 检测
3. 落盘 `<plan_dir>/REPORT.md`（人读）+ `<plan_dir>/record_gaps.json`（机读）
4. 返回 envelope（summary + completeness + session 关联）

**核心价值：暴露 schema drift / 锁失效 / 契约产物缺失等信号**——这些在 drive 运行中看不出来，跑完事后才能扫到。

---

## 数据源

| 来源 | 角色 | 缺时表现 |
|---|---|---|
| `.drive/<plan_dir>/` runtime 记录 | drive runtime contract 真相：阶段流转 / agent spawn/complete / verdict / files_changed / revision | 分两组分别处理 |
| `~/.claude/projects/<cwd-hash>/<sid>.json` chat session | agent 之间对话真相：user gate prompt / 各 agent 输出 | cwd-hash 未文档化 → 静默 skip；用户可 `--session <id>` 显式覆盖 |

runtime 记录内部再分两组（**严重度差异**）：

| 分组 | 文件 | 缺时 gap |
|---|---|---|
| Runtime SDK 通道产物 | `run-meta.json` / `intent.md` / `waves.yaml` / `topo-state.json` / `executeState.json` / `run-log.jsonl`（6 个）| `missing_file` **HIGH** |
| LLM 契约产物 | `manifest.md` / `taskRecord.yaml` / `evaluation/verification-report.md`（3 个）| `missing_file` **LOW** |

**关键**：任何**默认**来源缺失都不会让 drive-record 退出；缺的事实会**作为 gap 显式报告**，用户能看到「这次回放缺了什么」，而不是以为「drive-record 全看到了」。

---

## 9 类 Gap

`record_gaps.json` + `REPORT.md §B` 列出。修改 `scripts/gaps_detector.py` 时同步改 `references/gap-catalog.md`。

| 类型 code | 严重度 | 含义 | drive 修复点 |
|---|---|---|---|
| `revision_gap` | **CRITICAL** | `executeState.json.revision` 落后于 `run-log.jsonl` 中 `agent_spawned` 记录的 `state_revision_at_spawn` | `state_write.py` 的 fcntl 锁逻辑 |
| `missing_file` | HIGH / LOW | Runtime SDK 产物缺失 → HIGH；LLM 契约产物缺失 → LOW | runtime 启动检查 / 对应 agent .md |
| `missing_event` | HIGH/MEDIUM | `run-log.jsonl` 缺关键事件（`drive_startup` / `stage_advanced` / `drive_completed`）或 `stage_advanced` 次数 < 4 | `state_cli.py` 调用点 |
| `pending_confirmation_stuck` | HIGH | `pending_confirmation` 字段非空但 `updated_at` 超过 1 小时前未推进 | drive 调度逻辑 |
| `stale_running_agent` | HIGH | `agent_invocations.<task_id>.<reviewer>.status=running` + `started_at` 距今 > 30min（reviewer 卡死）| review 流程 / drift detector 阈值 |
| `missing_summary` | MEDIUM | `task_results.<id>.status=ok` 但 `artifacts/<id>/SUMMARY.md` 不存在 | executor 协议 |
| `timestamp_anomaly` | MEDIUM | `run-log.jsonl` 事件时间戳出现倒序（违反 append-only 单调） | `audit_append.py` |
| `unmapped_state_field` | LOW | `executeState.json` 含 schema 未声明字段（schema drift 早期信号） | runtime 版本管理 |

排序：`detect_gaps()` 返回按 `(CRITICAL → HIGH → MEDIUM → LOW, type)` 排序，便于 reviewer 自上而下扫。

严重度判定原则：

- **CRITICAL**：data correctness 受影响（`revision_gap` 表明状态机锁可能失效，后续 update 走错基础）
- **HIGH**：Runtime SDK 通道产物缺失，或 `pending_confirmation` 卡住 — 用户可见的 record 不完整
- **MEDIUM**：可能影响调试但不阻断审计
- **LOW**：LLM 契约产物缺失或 schema drift 早期信号 — 无需立即修

---

## 使用

用户调：

```
/drive-record <plan_dir>
```

Claude 解析参数 → 调 CLI → 渲染 SUMMARY 卡片。

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/cli.py --plan-dir <abs path>
```

参数：

| 参数 | 必填 | 用途 |
|---|---|---|
| `--plan-dir` | 是 | `.drive/<plan_dir>/` 绝对路径；相对路径时 Claude 自动加 `.drive/` 前缀 |
| `--cwd <cwd>` | 否 | 当前 cwd 与调 drive 时不同（用户在另一个 worktree）→ 用于 §5 session 定位 |
| `--session <id>` | 否 | cwd-hash 算法未文档化，§5 找不到 session 时显式覆盖 |

参数解析规则：

| 情况 | 动作 |
|---|---|
| 路径不存在 | **不调 CLI**，告诉用户「路径不存在，请确认是 `.drive/<plan_dir>/`」 |
| 路径是 `plan-<id>` 但当前 cwd 是项目根 | 自动加 `.drive/` 前缀再 resolve 一次 |
| 省略 plan_dir | **目前不支持**（`cli.py` 强制必填）；如要支持，需加 `.drive/.current-plan` / mtime 扫描 fallback |

---

## 输出

### envelope（CLI stdout）

```json
{
  "ok": true,
  "data": {
    "report_md": "/abs/path/.drive/<plan_dir>/REPORT.md",
    "summary": {"total": 3, "critical": 0, "high": 1, "medium": 2, "low": 0},
    "session_path": "~/.claude/projects/<cwd-hash>/<sid>.json",
    "plan_name": "<plan_name from run-meta>",
    "mode": "phase | dag",
    "completeness": {"runtime_present": 6, "runtime_total": 6, "llm_present": 3, "llm_total": 3}
  }
}
```

失败时：

| `reason` | 给用户的话 |
|---|---|
| `invalid_arg` | `--plan-dir` 不存在或不是目录；让用户重给 |
| `write_failed` | plan_dir 无写权限；让用户检查 |
| `internal` | 子模块 bug；附 details 段错误信息 |

### SUMMARY 卡片（Claude 渲染）

```
## /drive-record SUMMARY
- plan: <plan_name>
- mode: phase | dag
- completeness: Runtime <X/Y> + LLM <X/Y>
- gaps: total=N critical=C high=H medium=M low=L
- 报告: <plan_dir>/REPORT.md
- session: <~/.claude/projects/.../sid.json>（若已找到）
```

渲染规则：

- `critical > 0` → SUMMARY 顶部加 🚨 红字「CRITICAL gap 存在」
- `high > 0` → 末尾加 ⚠️「HIGH gap 存在；建议先翻 REPORT.md §B」
- session 路径没找到 → 静默不显示那行
- **不复述 gap 详情** —— 让用户翻 REPORT.md §B，否则对话冗长

### REPORT.md 结构

| 段 | 内容 |
|---|---|
| §0 | 元信息（plan_name / mode / 起始时间 / 锚定 git_head）|
| §1 | 时间线（按 wall-clock 排序的 runtime 事件 + 关键 agent spawn/complete）|
| §2 | DAG 拓扑 + wave 推进（mode=dag 时）或阶段流转（mode=phase 时）|
| §3 | verdict + evaluation 摘要 |
| §4 | files_changed 清单（与 git diff 对照）|
| §5 | chat session 关联（若已找到） |
| §B | **Gap 检测结果**（按严重度排序）|

### record_gaps.json（机读）

```json
{
  "plan_name": "<name>",
  "detected_at": "<ISO8601>",
  "gaps": [
    {
      "type": "revision_gap",
      "severity": "CRITICAL",
      "details": {"current_revision": 7, "expected_minimum": 12, "stale_agents": [...]},
      "fix_hint": "state_write.py 的 fcntl 锁逻辑"
    }
  ]
}
```

供 CI / 监控消费。

---

## 内部架构

```
cli.py
├── record_reader.py      # 读 9 个 runtime record 文件（run-meta / intent / waves / topo-state / executeState / run-log + manifest / taskRecord / verification-report）
├── timeline_builder.py   # 多源时间线合并（runtime events + chat session 消息）
├── gaps_detector.py      # 9 类 gap detector，分类汇总
├── build_report.py       # 把 timeline + gaps 渲染成 REPORT.md
├── session_locator.py    # cwd-hash → sid.json 定位
└── env.py                # envelope 返回协议（与 state-machine / dag-runtime 等 5 副本同模式）
```

每个脚本职责清晰单一。`cli.py` 是唯一入口；Claude 不应直接调其它子脚本（依赖同目录模块路径，会破）。

---

## Gotchas

- **CRITICAL > 0 → 顶部红字**：drive-record 的核心价值就是暴露 schema drift / 锁失效信号。
- **HIGH > 0 → 末尾 ⚠️**：温和提示，不抢戏。
- **不直接读 plan_dir 内 runtime 记录文件**：CLI 已做；重复读会绕开 gap detector 的单源逻辑，破坏一致性。
- **session 找不到 → 静默**：CLI 行为如此；Claude 不要主动解释「找不到 session」（噪音）。
- **`.drive/` 在 `.gitignore` 里**：REPORT.md 也不入 git；用户如要留档自行复制。
- **DAG vs phase 模式共用同一结构**：§0.1 / §2 标记 `mode=dag` / `phase`；SUMMARY 也带 mode 字段。
- **省略 plan_dir 但 `.drive/` 空**：不要硬猜，AskUserQuestion 报错路径不存在。

---

## 添加新 gap 类型

修改 `scripts/gaps_detector.py` 时**4 处同步**：

1. 写 detector 函数（返回 `Iterable[Gap]`，命名 `_detect_<type>`）
2. 加入 `detect_gaps()` 的 extend 链
3. 在 `references/gap-catalog.md` 加一行
4. 加对应测试（参考 `test_gaps_detector.py`）

**禁止**不写 detector 只在 catalog 列条目——catalog 是真相源的 mirror，不是预想。
