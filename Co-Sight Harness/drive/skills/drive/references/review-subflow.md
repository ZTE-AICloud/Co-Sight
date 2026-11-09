# execute 阶段 review 子流程

worker 产出后、wave barrier 前，对代码类 task 跑 code review + security review。
补 evaluator 的 L0/L1/L2 覆盖不到的部分：evaluator 查"AC 有没有达成"，reviewer 查
"达成的方式有没有埋雷"。

## 触发条件

判定由 `scripts/review_flow.py select` 做，不靠模型判断。全部满足才进 review：

| 条件 | 跳过时的原因串 |
|---|---|
| `mode == code` | `mode='analysis' 非 code` |
| `status == completed` | `status='failed' 未完成` |
| `task_category != simple` | `task_category='simple' 无需 review` |
| `files_changed` 含非文档文件 | `files_changed 无代码文件` |

文档类后缀：`.md` `.markdown` `.txt` `.rst` `.json` `.yaml` `.yml` `.toml` `.ini`
`.csv` `.tsv` `.lock`（大小写不敏感）。

跳过的 task **不写 REVIEW.md**，barrier 前自检也不把它算作缺失 —— 自检调同一个
`select` 拿"应该有"的名单。

## 派 reviewer

对 `select` 返回的每个 task_id，**同一条消息里并发** spawn 两个：

```python
Task(subagent_type="code-reviewer",     prompt=..., run_in_background=False)Task(subagent_type="security-reviewer", prompt=..., run_in_background=False)
```

prompt 必含两个字段：`task_id` / `files_changed`。

两个 reviewer 都只读，读同一 `files_changed` 无冲突；关注点正交，无顺序依赖。

## 写 state（agent_invocations）

reviewer 调用记录必须落 `executeState.agent_invocations` —— 这是 reviewer 状态
在 workflow 的 single source of truth。不写的话 `/drive-record` §1 时间线、§B
drift detector、未来 dashboard 全断。

写入协议（PROP-20260820-001）：

**spawn 前**：记 `status=running` + `started_at` + `attempt`

```bash
python3 /state-machine update --planning-dir .drive/<plan_dir> \
  --set-json 'agent_invocations.<task_id>.code-reviewer={"status":"running","started_at":"<ISO>","attempt":<N>}'
```

**reviewer 返回后**：补 `status` / `finished_at` / `duration_sec` / `verdict` /
`findings`：

```bash
python3 /state-machine update --planning-dir .drive/<plan_dir> \
  --set-json 'agent_invocations.<task_id>.code-reviewer={"status":"completed","started_at":"<ISO>","finished_at":"<ISO>","duration_sec":<sec>,"verdict":"<v>","findings":{"critical":<n>,"high":<n>,"medium":<n>,"low":<n>},"attempt":<N>}'
```

字段约束（`skills/state-machine/scripts/state_schema.py:AGENT_INVOCATION_STATUSES`
/ `VALID_REVIEWER_VERDICTS`）：

- `status`: `running` / `completed` / `failed` / `skipped`
- `verdict`: `approve` / `warning` / `block`（**`auto_mode` 下零 finding 仍写
  `approve`** —— verdict 是 reviewer judgment，gate-level skip 不污染）
- `findings`: `{critical, high, medium, low}` 全非负 int
- `attempt`: ≥1 int（重派递增，详见下节）

### CRITICAL 重派时 attempt 递增

reviewer 出了 CRITICAL → 重派同 task_id 的 executor → 重做后再 review。
**重派是新一轮 invocation**，不是同一条：

```bash
# 重派前（旧 attempt 被覆盖）
python3 /state-machine update --planning-dir .drive/<plan_dir> \
  --set-json 'agent_invocations.<task_id>.code-reviewer={"status":"completed",...,"verdict":"block","findings":{"critical":1,...},"attempt":1}'

# 重派后
python3 /state-machine update --planning-dir .drive/<plan_dir> \
  --set-json 'agent_invocations.<task_id>.code-reviewer={"status":"completed",...,"verdict":"approve","findings":{"critical":0,...},"attempt":2}'
```

**取最新 attempt 作为当前 reviewer 状态**（覆盖前一次）。前一次 findings 仍在REVIEW.md，state 不重复存历史 —— drive-record §1 时间线只显示 attempt=N 的行。

### reviewer 卡死处理（drift detector）

reviewer 进程被 kill / 卡死会留 `status="running"` 永久。**不自动改 state** —保持 drive contract（state 只能走 SDK + audit 通道）。

`/drive-record` §B 的 `gaps_detector.py:_detect_stale_running_agents` 检测：`status=running` + `started_at` 距今 > 30min → HIGH gap。用户决定：

- 补审（重新 spawn）
- 接受现状（手动 `/state-machine update --set-json ...=failed`）
- 重新跑整轮

## severity 决策

两个 reviewer 的 findings 合并后按最高 severity 决策：

| 最高 severity | 动作 |
|---|---|
| CRITICAL | 重派同 task_id 的 executor，prompt 追加 `fix 以下 review findings: <list>`，重做后再 review。**重做上限 2 次** |
| HIGH | 不重做。写 REVIEW.md，`summary.fail_notes` 追加 `HIGH findings: <count>` |
| MEDIUM / LOW | 写 REVIEW.md，不阻塞，不进 fail_notes |
| 无 finding | 写 REVIEW.md 空 findings 段，`verdict: approve` |

## CRITICAL 修不掉

第 2 次重做后仍有 CRITICAL 时**停下问人**，不要自行标 partial。

`agents/evaluator.md` 的 L0 检查规则是 `status ∈ {partial, failed} → L0 不过 `，L0 不过则 `verdict = fail` 并回退到 plan 重规划。也就是说标一次 partial 的代价是**整轮 workflow 回退**，这个代价必须由人决定，不能静默触发。

把 findings 讲给用户：file:line、snippet、两次都没修掉的原因。然后按回答走：

| 用户回答 | 动作 |
|---|---|
| accept | `status=completed`，findings 记入 REVIEW.md（连同用户接受的理由），继续 |
| partial | `status=partial`，接受 L0 不过 → 回退 plan 重规划 |
| 手动修 | 用户自己改，改完重跑 review |

`auto_mode: true` 时无人可问，取 `partial`：auto 模式下带病继续的风险高于重规划成本。

## summary 合流

`aggregate.py` 对同一 task_id 出现两次直接判 fail（`check_wave_completeness` 的
`duplicates` 检查）。重派后 orchestrator 手里同一 task_id 有两版 summary，传给
aggregate 之前必须先合流：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/review_flow.py" merge --summaries-file /tmp/s.json
```

同 task_id 取**最后一条**（数组靠后 = 更新的那次），新 `files_changed` 覆盖旧值。

## REVIEW.md

落到 `.drive/<plan_dir>/artifacts/<task_id>/REVIEW.md`，白名单 `^artifacts/.+` 已放行。

```markdown
# Review Report: <task_id>

- task_id: <task_id>
- verdict: approve | warning | block
- reviewers: code-reviewer, security-reviewer

## Findings

| severity | file:line | issue | fix |
|---|---|---|---|
| CRITICAL | src/db/user.py:88 | SQL 注入 | 改参数化查询 |

## Stats

| severity | count |
|---|---|
| CRITICAL | 1 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 1 |

## 重做记录

| 轮次 | 剩余 CRITICAL |
|---|---|
| 1 | 1 |
| 2 | 0 |
```

零 finding 时 Findings 表留空、Stats 全 0、`verdict: approve`，仍要写文件 ——"审过且干净"与"没审"是两种不同状态，落盘才能区分。
