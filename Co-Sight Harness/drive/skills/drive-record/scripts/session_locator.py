"""§5 session 路径定位 —— agent_spawned 事件 → ~/.claude/projects/<hash>/<session>.json。

设计：
- 优先级链：(1) run-log 中 agent_spawned.session_id → 拼 path → (2) 显式 --session override
- 路径 hash：v1 用 sha256(abs_cwd.encode()).hexdigest()[:16] 作为启发式；找不到 silently skip
- 不报错：找不到 session 文件 = §5 整段不出现
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable

from record_reader import LogEvent, Record


_PROJECTS_ROOT = Path(os.path.expanduser("~/.claude/projects"))


def cwd_hash(cwd: str) -> str:
    """Claude Code 用 cwd 的 hash 区分项目；v1 启发式是 sha256 前 16 位。

    这是 best-effort；Claude Code 实际算法未文档化。找不到就 silently skip。
    """
    if not cwd:
        return ""
    return hashlib.sha256(os.path.abspath(cwd).encode("utf-8")).hexdigest()[:16]


def extract_session_id(record: Record) -> str:
    """从 run-log 第一个含 session_id 的 agent_spawned 事件取 session_id。"""
    for ev in record.log_events:
        if ev.event != "agent_spawned":
            continue
        sid = ev.details.get("session_id")
        if isinstance(sid, str) and sid:
            return sid
    return ""


def _candidate_paths(session_id: str, cwd: str | None = None) -> Iterable[Path]:
    """根据 session_id + (可选) cwd 生成候选路径。"""
    if not session_id:
        return
    if cwd:
        h = cwd_hash(cwd)
        if h:
            yield _PROJECTS_ROOT / h / f"{session_id}.json"
    # 无 cwd 或 cwd-hash 没结果时：扫一遍 _PROJECTS_ROOT 下所有 hash 目录
    if _PROJECTS_ROOT.is_dir():
        for child in _PROJECTS_ROOT.iterdir():
            if not child.is_dir():
                continue
            candidate = child / f"{session_id}.json"
            if candidate not in (
                _PROJECTS_ROOT / (cwd_hash(cwd) if cwd else "") / f"{session_id}.json",
            ):
                yield candidate


def locate_session(
    record: Record,
    cwd: str | None = None,
    override: str | None = None,
) -> Path | None:
    """主入口：返回第一个存在的 session json 路径；找不到返回 None。

    参数：
    - record: 已 read 出来的 record
    - cwd: 当前进程 cwd；用于算 cwd-hash
    - override: --session <id> 显式覆盖（v2 用；v1 留接口）

    规则：
    1. override 非空 → 直接用 override 找
    2. 从 run-log 提取 session_id → 按 cwd-hash 找 → 扫所有 hash 目录 fallback
    3. 都找不到 → None
    """
    sid = override.strip() if override else ""
    if not sid:
        sid = extract_session_id(record)
    if not sid:
        return None
    for p in _candidate_paths(sid, cwd):
        if p.is_file():
            return p
    return None


__all__ = [
    "cwd_hash",
    "extract_session_id",
    "locate_session",
    "_PROJECTS_ROOT",
]