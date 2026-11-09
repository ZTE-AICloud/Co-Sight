---
name: drive-cleanup
description: Use when the local .drive/ directory has accumulated too many plan-<ts>-<name>/ sub-directories and needs pruning, when the user asks to clean local drive state, or invokes "/drive-cleanup". Triggers include "清理 .drive/" / "清除 plan 目录" / "/drive-cleanup" / "drive cleanup" / "drive clean plans" / "too many plan dirs" / "clean local drive".
user-invocable: true
allowed-tools: Bash(python3 *clear_plans.py*)
---

# drive-cleanup

清理本地 `.drive/plan-*/` 中过期 plan 目录。

`.drive/` 不提交 git，但需求做多了目录会膨胀（每个 PR 一个 `plan-<UTC-YYYYMMDD-HHMM>-<name>/`，跑完需求后留在本地）。`drive-cleanup` 让 LLM 自动判断何时清理。

## 何时调用

- `.drive/` 下 plan-* 数量超过 10 个（默认清理阈值）
- 用户说"清理 .drive/" / "/drive-cleanup" / "本地太满了" / "清掉旧的 plan"
- LLM 在跑 drive 流程时主动判断"该清理了"

## 行为

调用 `clear_plans.py`（已在 §实现），按字典序（= UTC 时间序）扫描 `.drive/plan-*/`：

- 默认清理**最早的 10 个**（dry-run preview + AskUserQuestion 确认后才执行）
- 可选参数：`--all` / `--keep N` / 指定 plan-dir 全名
- 跳过正在跑的 plan（最近 30 分钟有改动认为在跑）
- 可选 `--tar` 先备份到 `.drive/.cleared/<ts>.tar.gz` 再删
- 保留：`.drive/.cleared/`（备份文件）和 `.drive/.planning-backup-*.tar.gz`（兼容旧数据）

## 调用

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/clear_plans.py" --work-dir <work_dir> [options]
```

返回 Envelope：

```json
{
  "ok": true,
  "data": {
    "cleared": [{"plan": "plan-xxx", "tar_path": null}],
    "skipped_running": []
  }
}
```

或（dry-run 默认）：

```json
{
  "ok": false,
  "reason": "needs_confirmation",
  "would_clear": ["plan-xxx", ...],
  "skipped_running": []
}
```

## 用户体验

drive-cleanup **不**自动执行删除——dry-run preview 后必须经用户确认（默认行为）。除非 `--force` 才跳过确认（CI / batch 用）。

示例：

```
> LLM 看到 .drive/ 里有 15 个 plan：调用 drive-cleanup skill
> clear_plans.py 列出最早的 10 个 + 大小 + mtime
> LLM: "将清理最早 10 个 plan（共 4.2MB）。继续？"
> 用户: "是"
> clear_plans.py --force 跳过确认 + 删除
```

## 实现

`scripts/clear_plans.py` 由该 skill 引入（同 SKILL 包内）。

## 范围

**本 skill 不管**：
- 删 `.drive/` 之外的目录（用户项目根 `/tmp/` 等）
- 自动跑（无用户确认下）
- 删除正在跑的 plan（保护）
- 清理 `.drive/.cleared/` 备份文件（用户手动）