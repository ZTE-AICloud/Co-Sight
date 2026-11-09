"""hook_io.py — hook 脚本共享的输入 / 状态读取工具。

hooks/ 下的守卫脚本被 Claude Code 以独立进程执行（stdin JSON → exit 0/2）。
本模块提供读 stdin、定位当前 plan 目录、读 active_stage 的公共实现。

路径约定（PROP-20260817-001）：
- 工作区根：<work_dir>/.drive/plan-<UTC-YYYYMMDD-HHMM>-<name>/
- hook 通过 .drive/.current-plan 标记或最近 mtime 找到当前活跃 plan
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_LOG_NAME = "run-log.jsonl"
DRIVE_ROOT_NAME = ".drive"
PLAN_DIR_PREFIX = "plan-"
CURRENT_PLAN_MARKER = ".current-plan"


def read_hook_input() -> dict[str, Any]:
    """读 stdin JSON；空 / 非法返回 {}。"""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def _find_drive_root(start: Path | None = None) -> Path | None:
    """从 cwd 向上找最近的 .drive/ 目录。"""
    cwd = start or Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / DRIVE_ROOT_NAME
        if candidate.is_dir():
            return candidate
    return None


def _find_current_plan(drive_root: Path) -> Path | None:
    """在 .drive/ 下找当前活跃 plan 子目录。

    优先级：
    1. .current-plan 标记文件（drive orchestrator 写）
    2. 最新 mtime 的 plan-<ts>-<name>/ 子目录（fallback）
    """
    marker = drive_root / CURRENT_PLAN_MARKER
    if marker.is_file():
        try:
            plan_name = marker.read_text(encoding="utf-8").strip()
        except OSError:
            plan_name = ""
        if plan_name:
            candidate = drive_root / plan_name
            if candidate.is_dir():
                return candidate

    plans = [p for p in drive_root.glob(f"{PLAN_DIR_PREFIX}*") if p.is_dir()]
    if not plans:
        return None
    if len(plans) == 1:
        return plans[0]
    return max(plans, key=lambda p: p.stat().st_mtime)


def find_active_plan_dir(start: Path | None = None) -> Path | None:
    """从 cwd 向上找当前活跃 plan 目录（.drive/<plan_dir>/）。

    PROP-20260817-001：旧 .planning/ 已废弃；hook 自动找 .drive/<plan>/。    """
    drive_root = _find_drive_root(start)
    if drive_root is None:
        return None
    return _find_current_plan(drive_root)


def append_run_log(planning_dir: Path, event: str, **details: Any) -> bool:
    """追加一个事件到 run-log.jsonl；失败返回 False（调用方静默放行）。

    hook 侧只需追加，不需要返回协议。ts 用 UTC ISO8601。
    """
    if not event or not planning_dir.is_dir():
        return False
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **{k: v for k, v in details.items() if k not in ("ts", "event")},
    }
    try:
        with open(planning_dir / RUN_LOG_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        return False
    return True


def read_execute_state(planning_dir: Path | None) -> dict[str, Any] | None:
    """读整份 executeState.json；读不到或损坏返回 None。"""
    if planning_dir is None:
        return None
    path = planning_dir / "executeState.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_state_revision(planning_dir: Path | None) -> int | None:
    """读 executeState.json 的 revision；读不到返回 None。

    revision 单调自增，用于判定"这期间 state 有没有被写过"。
    """
    if planning_dir is None:
        return None
    path = planning_dir / "executeState.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    revision = data.get("revision")
    return revision if isinstance(revision, int) else None


def read_run_log(planning_dir: Path | None) -> list[dict[str, Any]]:
    """读 run-log.jsonl 全部事件；损坏行跳过。"""
    if planning_dir is None:
        return []
    path = planning_dir / RUN_LOG_NAME
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def read_active_stage(planning_dir: Path | None) -> str | None:
    """读当前阶段；读不到返回 None。

    唯一来源：`executeState.json`（state-machine skill 实际写入的地方）。
    """
    if planning_dir is None:
        return None
    return _stage_from_execute_state(planning_dir)


def _stage_from_execute_state(planning_dir: Path) -> str | None:
    path = planning_dir / "executeState.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    stage = data.get("active_stage")
    return str(stage) if isinstance(stage, str) and stage else None


def find_current_plan_dir(start: Path | None = None) -> str | None:
    """PROP-20260817-001 P0-1：返回当前活跃 plan 的目录名（如 'plan-20260817-1530-foo'）。

    复用 find_active_plan_dir 的 .current-plan 标记 + mtime fallback 逻辑，
    但只返回 plan_dir 名字（不是完整 Path），便于传入 hooks_protocol 的
    current_plan_dir 参数。
    """
    plan_path = find_active_plan_dir(start)
    return plan_path.name if plan_path is not None else None
