# 校验工作流配置

> 自包含校验脚本：`scripts/validate_workflow.py`，**不依赖** drive 的 read_workflow.py。

## 校验命令

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_workflow.py" \
  /path/to/workflow.yaml \
  [--plugin-root /path/to/plugin/root]
```

退出码：
- `0` = 通过
- `1` = 失败

## 输出格式

成功：
```json
{
  "ok": true,
  "data": {"phases": [...], "complexity_rules": {...}},
  "details": {}
}
```

失败：
```json
{
  "ok": false,
  "reason": "schema_invalid",
  "details": {
    "message": "phases[0] 缺少 name; phases[1]...",
    "errors": ["phases[0] 缺少 name", "phases[1]..."]
  }
}
```

## 校验项

| 项 | 错误信息 | 原因 |
|---|---------|------|
| phase 必填字段 | `phases[N] 缺少 name/stage/agent` | 缺少必填字段 |
| stage 重复 | `phases 中 stage 名称重复: 'xxx'` | 同一个 stage 出现多次 |
| start 禁用 | `phases[N]: stage='start' 已废弃` | start 阶段由 drive 内部处理 |
| gate 类型 | `phases[N].gate.type 未知: 'xxx'` | gate.type 必须是 human_review / artifact_check / input_check |
| enforced_by 必填 | `phases[N].gate 缺少 enforced_by` | 没有 hook |
| enforced_by 路径 | `phases[N].gate.enforced_by 指向的 hook 不存在: 'xxx'` | hook 文件不在 plugin_root 下 |
| mode 校验 | `phases[N].mode 未知: 'xxx'` | mode 必须是 code 或 analysis |
| terminal 唯一 | `terminal_stage 只能有一个，当前有 N 个` | 多个 phase 有 terminal_stage: true |
| terminal 位置 | `terminal_stage 必须是最后一个 phase` | terminal_stage 不在末尾 |
| 回跳源存在 | `allowed_back_jumps 中的源 stage 不存在: 'xxx'` | 回跳源 stage 没在 phases |
| 回跳目标存在 | `allowed_back_jumps[N] 中的目标 stage 不存在: 'xxx'` | 回跳目标 stage 没在 phases |
| 回跳方向 | `不在当前 stage 之前` | 回跳目标是后面的 stage（不合法） |
| complexity tier | `complexity_rules 未知 tier: 'xxx'` | tier 必须是 trivial/standard/complex |
| complexity 字段 | `含未知字段: [...]` | 只允许 skip_phases 和 evaluate_levels |
| evaluate_levels 值 | `含非法值: 'xxx'` | 必须是 L0/L1/L2 |

## 设计说明

### 为什么自包含？

workflow-builder 是一个独立的 capability skill，**不应该**依赖其他 skill 的脚本。
即使 drive 提供了 `read_workflow.py`，workflow-builder 也应该有自己的轻量校验器。

### 与 drive read_workflow.py 的关系

- `validate_workflow.py`（workflow-builder 自带）：轻量校验，覆盖 schema 规则
- `read_workflow.py`（drive 提供）：完整校验，还包括 phase 推断、allowed_back_jumps 推断等

**两个工具互补**，不重复。用户在生成/编辑阶段用 validate_workflow.py，最终交付前可以再用 drive 的 read_workflow.py 做一次完整校验。

### `--plugin-root` 参数的作用

校验 `gate.enforced_by` 指向的 hook 是否真实存在时，需要知道插件根目录的绝对路径。
不传 `--plugin-root` 时，跳过 enforced_by 路径检查（只做 schema 检查）。