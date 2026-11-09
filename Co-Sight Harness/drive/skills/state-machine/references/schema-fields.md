# executeState.json 字段表

`.drive/<plan_dir>/executeState.json` 默认值见 `scripts/state_write.py::default_state()`。校验在 `scripts/state_schema.py` 强制（顶层字段 + 已知保留字段）。

字段值是否真存在以 `state_schema.py:COMMON_FIELDS` 为准（schema 漂移检测）——本文档按该列表列字段。

## 默认值（state_write.default_state() 写入）

| 字段 | 类型 | 默认值 | 来源 |
|------|------|------|------|
| `schema_version` | str | `"drive.runtime.state.v1"` | default_state |
| `revision` | int | `0` | 单调自增，每次 `update` +1 |
| `active_stage` | enum | `None` | — |
| `status` | str | `"executing"` | default_state |
| `current_wave` | int | `1` | DAG 模式用，phase 模式可空 |
| `waves_total` | int | `1` | DAG 模式用，`dag_init.set-waves-total` 推 |
| `task_results` | object | `{}` | dag-runtime 写 |
| `wave_summaries` | object | `{}` | dag-runtime 写 |
| `next_action` | str / null | `None` | drive orchestrator 自己读 |
| `confirmed_stages` | list[str] | `[]` | phase 模式 HITL 证据 |
| `confirmed_nodes` | list[str] | `[]` | DAG 模式 HITL 证据 |
| `pending_confirmation` | str / null | `None` | 当前在等谁签字 |
| `verdict` | str | `None` | extract_verdict.py 写 |
| `custom_agents.<name>.status` | str | — | agent 上报（mandatory） |
| `custom_agents.<name>.output_path` | str | — | agent 上报（mandatory） |
| `custom_agents.<name>.current_stage` | str | — | agent 上报（推荐） |
| `active_agents` | list[obj] | — | dag-runtime `set-active-agents` 写（DAG 模式专用） |
| `agent_invocations` | object | — | phase 模式记录 agent 调用结果 |
| `created_at` | timestamp | now | default_state |
| `updated_at` | timestamp | now | 每次 update 刷新 |

## HITL 字段写入规则

- `confirmed_stages` / `confirmed_nodes` —— 只能由 `confirm_stage.py` / `confirm_node.py` 写，`update --set` 在 CLI 层禁写
- 这两个脚本**故意不在任何 skill 的 allowed-tools 内**，执行时 harness 弹权限请求即人工确认本身
- `auto_mode=true` 是唯一全局旁路

## 字段过期清理

- `pending_plan_review` 由 `state_cli.cmd_transition` 在流转出 plan 时手动清 `False`
- 其他字段过期后随 state 保留到下一次 `update`

## custom_agents 命名空间

一个 agent 只写自己名下的子树：

```bash
SC="${CLAUDE_SKILL_DIR}/scripts/state_cli.py"

python3 "$SC" update --planning-dir <dir> \
  --set custom_agents.<agent-name>.status=running
python3 "$SC" update --planning-dir <dir> \
  --set custom_agents.<agent-name>.status=completed \
  --set custom_agents.<agent-name>.output_path=<path>
```

领域特有字段放 `custom_agents.<name>.metadata.<field>` 下，不往命名空间根上加。

## Gotchas

- **点号是路径分隔符，不能作字面量 key**：`--set foo.bar=1` 落成嵌套 `{"foo": {"bar": 1}}`，拿不到名为 `foo.bar` 的键
- **路径中途撞标量会被拒**：若 `custom_agents.a` 已是字符串，再写 `custom_agents.a.status` 返回 `schema_invalid` 且整次写入不落盘
- **别写 `confirmed_stages` / `confirmed_nodes`**：只能由 `confirm_stage.py` / `confirm_node.py` 写，`update --set` 在 CLI 层拒
- **`status` 拼错不报错**：写成 `state` 或 `Status` 都写得进去，但编排层读不到，本阶段永远不算完成
- **只写自己的命名空间**：写别的 agent 名下的字段不会报错，但会让那个 agent 的状态失真

## 自检

- [ ] `status` 开工写 `running`，收工写 `completed`
- [ ] 失败路径写 `status=failed`
- [ ] `output_path` 与实际产出文件路径一致
- [ ] agent 名与 workflow.yaml `phases[].agent` 一致
- [ ] 领域字段放 `metadata` 下，没往命名空间根上加
