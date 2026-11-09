# Wave Barrier 强约束

> 目的：让 wave 间的"等全"和"worker 报完成但 fs 无变化"两类失败在 barrier> 处被拦下，不让错误状态写进 executeState.json。

## 1. task_id 对账 barrier

**执行点**：`skills/wave-barrier/scripts/aggregate.py`

**触发**：每 wave 收尾，main agent 收集所有 worker summary 后调 aggregate。

**机制**：

```text
summaries[i].task_id 集合  ←→  waves.yaml[wave_n].tasks[].task_id 集合
```

不匹配（缺 / 多 / 重复）→ Envelope.fail(REASON_WAVE_MISMATCH) → 不写 state。

**降级**：waves.yaml 缺失或该 wave 不在 waves.yaml 里时，barrier 不强制（返回 `barrier_enforced: false`），aggregate 仍写 state。**降级路径只在旧仓库或手工拼 wave 时出现，正常 drive 流程走不到**。

## 2. fs diff barrier

**执行点**：同上（aggregate.py）

**触发**：状态为 `completed` / `skipped` 的 summary 必须声明
`files_changed: [path, ...]` 非空。

**机制**：

```text
status ∈ {completed, skipped}  AND  files_changed is empty  →  barrier_blocked
```

**为什么不读盘校验文件真存在**：本脚本只忠实落账，fs 真实存在与否由
**主对话层**（main agent）做 —— 那一层离 LLM 更近，可以决策"重派 / 接受 /
跳过"。barrier 这里只验"声明一致性"：worker 说改了什么，跟它说完成没，
二者必须配对。

**失败处理**：

```json
{
  "ok": false,
  "reason": "empty_fsdiff",
  "wave": 3,
  "writeback_ok": false,
  "empty_fsdiff": ["T05", "T07"],
  "error": "wave 3 里有 2 个 task 报完成但 files_changed 为空"
}
```

主对话层收到这个 Envelope 应该：
1. 列出 empty_fsdiff 的 task
2. 决策：补派（最常见）/ 让 worker 改成 status=failed（确实没改文件时）/ 接受（rare，但允许）

**绝不要**直接把 `files_changed=[]` 注入 summary 绕过 —— 那等于取消 barrier。

## 3. 与其他 barrier 的关系

| Barrier | 执行点 | 拦截的失败模式 |
|---------|--------|----------------|
| 1. task_id 对账 | aggregate.py | wave N-1 没跑全 / 主对话抢跑推到 wave N+1 / worker 双跑 |
| 2. fs diff | aggregate.py | worker 报完成但 fs 无变化（驱动层"主 agent 兜底"反模式） |
| 3. state_transition_guard | hooks/ | 阶段流转非法 / 跨阶段产物污染 / verdict 缺失 |
| 4. planning_write_guard | hooks/ | `.drive/<plan_dir>/` 写白名单外路径 / 状态文件被直写 |
| 5. stage confirmation | hooks/ + confirm_stage.py | HITL 流程被绕过 / confirmed_stages 被改写 |

barrier 1、2 在 worker 完成时即时拦；barrier 3-5 在工具调用时拦。两层互补：worker 层的 barrier 拦"业务结果"对账，hook 层的 barrier 拦"流程行为"违规。

## 4. 调试

aggregate 失败时 stdout 是 Envelope JSON，看 `reason` 字段定类别：

| reason | 含义 | 下一步 |
|--------|------|--------|
| `wave_mismatch` | 缺 / 多 / 重复 task | 检查 worker 派发数 vs waves.yaml |
| `empty_fsdiff` | 报完成但无 files_changed | 补派或接受 |
| `writeback_failed` | state_cli 调用失败 | 看 stderr 的 state_cli Envelope |
| `empty_summaries` | summary 列表为空 | 检查 wave 是否被误跳过 |
| `invalid_arg` | CLI 参数错 | 看 error 字段 |
