"""§1 时间线构建 —— 把 run-log 事件 + git commits 合并成 `HH:MM:SS [tag] desc` 行。

设计：
- 纯只读：不调 drive runtime，只读 record + 调 git log
- phase / DAG mode 区别处理 reviewer 行：
  - phase mode: reviewer 行从 `executeState.agent_invocations` 读（single source
    of truth），同时过滤 run-log 里 code-reviewer / security-reviewer 的
    agent_spawned / agent_completed 事件避免重复
  - DAG mode: 维持原行为（读 run-log；DAG mode 没有 agent_invocations）
- tag ∈ {startup, stage, agent, gate, commit, verdict, end}
- 无 tag 的事件跳过（如 drive_completed 已 verdict / end 覆盖）
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from record_reader import LogEvent, Record


@dataclass(frozen=True)
class TimelineEntry:
    ts: str
    text: str


@dataclass(frozen=True)
class GitCommit:
    short_hash: str
    subject: str
    iso_ts: str


_EVENT_TAG_MAP: dict[str, str] = {
    "drive_startup": "startup",
    "stage_advanced": "stage",
    "agent_spawned": "agent",
    "agent_completed": "agent",
    "gate_triggered": "gate",
    "gate_resolved": "gate",
    "transition_with_verdict": "verdict",
    "drive_completed": "end",
}

# phase mode 下 reviewer 行从 agent_invocations 读，过滤这些 subagent_type 的
# run-log 事件避免重复
_REVIEWER_AGENT_TYPES: frozenset[str] = frozenset({
    "code-reviewer",
    "security-reviewer",
})


def _format_ts(ts: str) -> str:
    """ISO 字符串 → HH:MM:SS。失败原样返回。"""
    if not ts:
        return "??:??:??"
    cleaned = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return ts.split("T", 1)[-1][:8] if "T" in ts else ts[:8]
    return dt.strftime("%H:%M:%S")


def _format_event(event: LogEvent) -> TimelineEntry | None:
    tag = _EVENT_TAG_MAP.get(event.event)
    if tag is None:
        return None
    text = _describe(event)
    if text is None:
        return None
    return TimelineEntry(ts=event.ts, text=f"{_format_ts(event.ts)} [{tag}] {text}")


def _describe(event: LogEvent) -> str | None:
    details = event.details
    if event.event == "drive_startup":
        name = str(details.get("plan_name") or "")
        return f"drive 启动 plan={name}" if name else "drive 启动"
    if event.event == "stage_advanced":
        src = str(details.get("from") or "?")
        dst = str(details.get("to") or "?")
        return f"{src} → {dst}"
    if event.event == "agent_spawned":
        sub = str(details.get("subagent_type") or "agent")
        desc = str(details.get("description") or "")
        return f"spawn {sub}{(': ' + desc) if desc else ''}"
    if event.event == "agent_completed":
        sub = str(details.get("subagent_type") or "agent")
        return f"complete {sub}"
    if event.event == "gate_triggered":
        gate = str(details.get("gate") or details.get("name") or "gate")
        return f"trigger {gate}"
    if event.event == "gate_resolved":
        gate = str(details.get("gate") or details.get("name") or "gate")
        decision = str(details.get("decision") or details.get("response") or "")
        suffix = f" → {decision}" if decision else ""
        return f"resolve {gate}{suffix}"
    if event.event == "transition_with_verdict":
        src = str(details.get("from") or "?")
        dst = str(details.get("to") or "?")
        verdict = str(details.get("verdict") or "")
        suffix = f" verdict={verdict}" if verdict else ""
        return f"{src} → {dst}{suffix}"
    if event.event == "drive_completed":
        verdict = str(details.get("verdict") or "")
        return f"完成 verdict={verdict}" if verdict else "完成"
    return None


def _git_log(worktree: Path, since: str) -> list[GitCommit]:
    """调 git log --since=<started_at>，返回短 hash + subject + ISO ts 列表。

    git 失败 / 非 git repo / since 为空 → 返回空列表（不报错）。
    """
    if not worktree.is_dir():
        return []
    cmd = ["git", "-C", str(worktree), "log", "--pretty=format:%h|%ai|%s"]
    if since:
        cmd.extend(["--since", since])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=30
        )
    except (subprocess.SubprocessError, OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    commits: list[GitCommit] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        commits.append(GitCommit(
            short_hash=parts[0],
            iso_ts=parts[1].strip(),
            subject=parts[2],
        ))
    return commits


def _format_commit(commit: GitCommit) -> TimelineEntry:
    text = f"{_format_ts(commit.iso_ts)} [commit] {commit.short_hash} {commit.subject}"
    return TimelineEntry(ts=commit.iso_ts, text=text)


def _merge_timeline(
    event_entries: list[TimelineEntry],
    commit_entries: list[TimelineEntry],
) -> list[str]:
    combined = sorted(event_entries + commit_entries, key=_sort_key)
    return [e.text for e in combined]


def _sort_key(entry: TimelineEntry) -> str:
    return entry.ts or ""


def _is_phase_mode(record: Record) -> bool:
    """executeState 无 mode 字段或 mode != 'dag' 视为 phase mode。

    DAG mode 显式用 active_agents 承载 per-agent 状态，不引入 agent_invocations。
    """
    state = record.execute_state
    if state is None:
        return True
    return state.raw.get("mode") != "dag"


def _format_findings(findings: Any) -> str:
    """findings dict → 'c:0/h:1/m:2/l:3'。格式不合法返回空串。"""
    if not isinstance(findings, dict):
        return ""
    try:
        return (
            f"c:{int(findings.get('critical', 0))}"
            f"/h:{int(findings.get('high', 0))}"
            f"/m:{int(findings.get('medium', 0))}"
            f"/l:{int(findings.get('low', 0))}"
        )
    except (TypeError, ValueError):
        return ""


def _invocation_to_entries(
    task_id: str, reviewer_name: str, inv: dict[str, Any]
) -> list[TimelineEntry]:
    """单条 agent_invocations 条目 → 时间线行。

    至少产生 spawn 行（用 started_at）；completed / failed 时再加 complete / fail 行。
    """
    entries: list[TimelineEntry] = []
    started_at = inv.get("started_at")
    finished_at = inv.get("finished_at")
    status = inv.get("status")
    verdict = inv.get("verdict")
    findings = inv.get("findings")
    duration = inv.get("duration_sec")
    attempt = inv.get("attempt", 1)

    if started_at:
        entries.append(TimelineEntry(
            ts=str(started_at),
            text=(
                f"{_format_ts(str(started_at))} [agent] spawn {reviewer_name}: "
                f"{task_id} attempt={attempt}"
            ),
        ))

    if finished_at and status in ("completed", "failed"):
        suffix_parts: list[str] = []
        if verdict:
            suffix_parts.append(f"verdict={verdict}")
        f_summary = _format_findings(findings)
        if f_summary:
            suffix_parts.append(f"findings={f_summary}")
        if isinstance(duration, (int, float)):
            suffix_parts.append(f"dur={int(duration)}s")
        suffix_parts.append(f"attempt={attempt}")
        suffix = " " + " ".join(suffix_parts)
        verb = "complete" if status == "completed" else "fail"
        entries.append(TimelineEntry(
            ts=str(finished_at),
            text=(
                f"{_format_ts(str(finished_at))} [agent] {verb} {reviewer_name}: "
                f"{task_id}{suffix}"
            ),
        ))

    return entries


def _format_agent_invocations(record: Record) -> list[TimelineEntry]:
    """executeState.agent_invocations → reviewer 时间线行（phase mode only）。

    真实顺序按 started_at 排序；同一 task 内多个 reviewer 顺序由 dict iteration order
    决定（Python 3.7+ 保证插入顺序，但 orchestrator spawn 顺序在写入时已隐含）。
    """
    state = record.execute_state
    if state is None:
        return []
    invocations = state.raw.get("agent_invocations") or {}
    if not isinstance(invocations, dict):
        return []

    entries: list[TimelineEntry] = []
    for task_id, reviewers in invocations.items():
        if not isinstance(reviewers, dict):
            continue
        for reviewer_name, inv in reviewers.items():
            if isinstance(inv, dict):
                entries.extend(_invocation_to_entries(task_id, reviewer_name, inv))
    return entries


def build_timeline(
    record: Record,
    worktree: Path | None = None,
) -> list[str]:
    """主入口：record + (可选) worktree → 排序后的时间线行。

    worktree 为空 / 非 git repo / git 失败 → 不插入 commit 行。

    Phase mode: reviewer 行改读 executeState.agent_invocations，过滤 run-log
    里 code-reviewer / security-reviewer 的 agent_spawned / agent_completed 事件。
    DAG mode: 维持原行为（run-log 全量读）。
    """
    is_phase = _is_phase_mode(record)

    event_entries: list[TimelineEntry] = []
    for ev in record.log_events:
        # Phase mode: 跳过 reviewer spawn / complete（agent_invocations 替代）
        if (
            is_phase
            and ev.event in ("agent_spawned", "agent_completed")
            and str(ev.details.get("subagent_type") or "") in _REVIEWER_AGENT_TYPES
        ):
            continue
        formatted = _format_event(ev)
        if formatted is not None:
            event_entries.append(formatted)

    # Phase mode: 注入 reviewer 行（来自 agent_invocations）
    if is_phase:
        event_entries.extend(_format_agent_invocations(record))

    commit_entries: list[TimelineEntry] = []
    if worktree is not None:
        since = record.run_meta.started_at if record.run_meta else ""
        for commit in _git_log(worktree, since):
            commit_entries.append(_format_commit(commit))

    return _merge_timeline(event_entries, commit_entries)


__all__ = [
    "TimelineEntry",
    "GitCommit",
    "build_timeline",
    "_format_ts",
    "_format_event",
    "_format_agent_invocations",
    "_git_log",
]