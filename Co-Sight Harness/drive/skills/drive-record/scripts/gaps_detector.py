"""§B 完整性 + 一致性 gap 检测 —— 8 类。

每类 gap：
- `type`: 短横线 code（drive 修复时用作 ID）
- `severity`: CRITICAL / HIGH / MEDIUM / LOW
- `location`: 文件:字段 路径
- `description`: 发生了什么
- `fix_suggestion`: 修复建议
- `related_runtime`: drive runtime 的修复位置（相对路径:行号）

按写入方区分缺失严重度：
- Runtime SDK 产物缺失 → HIGH（runtime 中断或异常）
- LLM 契约产物缺失 → LOW（agent 没写，可补）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from record_reader import LLM_CONTRACT_FILES, RUNTIME_FILES, Record


SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

SEVERITY_ORDER: dict[str, int] = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_HIGH: 1,
    SEVERITY_MEDIUM: 2,
    SEVERITY_LOW: 3,
}

# executeState.json 中 drive-2.3 已知字段（含 DAG 模式）。多出来的 = schema drift 信号
KNOWN_STATE_FIELDS: frozenset[str] = frozenset({
    "schema_version",
    "revision",
    "active_stage",
    "status",
    "current_wave",
    "waves_total",
    "task_results",
    "wave_summaries",
    "next_action",
    "confirmed_stages",
    "pending_confirmation",
    "created_at",
    "updated_at",
    "verdict",
    "active_agents",
    "mode",
    "agent_invocations",
})

# reviewer 卡死阈值（agent_invocations 中 status=running 超过此时间视为 stale）
# HITL 暴露，不自动改 state
STALE_RUNNING_AGENT_SECONDS: int = 30 * 60

# 关键事件类型（缺失 = HIGH/MEDIUM，按严重度区分）
KEY_EVENT_TYPES: frozenset[str] = frozenset({
    "drive_startup",
    "stage_advanced",
    "drive_completed",
})

# 阶段总数（plan-review-gate 不算 stage，但 stage_advanced 至少发生 4 次）
STAGE_ADVANCED_EXPECTED: int = 4


@dataclass(frozen=True)
class Gap:
    type: str
    severity: str
    location: str
    description: str
    fix_suggestion: str
    related_runtime: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    cleaned = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _detect_missing_files(record: Record) -> Iterable[Gap]:
    """区分 Runtime SDK 通道产物（HIGH）与 LLM 契约产物（LOW）。

    Runtime 缺失 = drive runtime 中断 / 异常；用户可见，记录不完整。
    LLM 缺失 = agent 没自觉写；不是 bug，但「完整过程」少一块。
    """
    for name in record.missing_files:
        if name in RUNTIME_FILES:
            severity = SEVERITY_HIGH
            fix = (
                "检查 drive runtime 启动是否中断 / workflow.yaml 是否声明了对应产物"
            )
            related = "skills/state-machine/scripts/state_write.py"
        elif name in LLM_CONTRACT_FILES:
            severity = SEVERITY_LOW
            if name.endswith("manifest.md"):
                who = "analyzer agent"
            elif name.endswith("taskRecord.yaml"):
                who = "planner agent"
            elif name.endswith("verification-report.md"):
                who = "evaluator agent"
            else:
                who = "对应 LLM agent"
            fix = f"{who} 协议要求写 {name}；检查对应 agent .md 是否漏写"
            related = f"agents/{who.replace(' agent', '')}.md"
        else:
            severity = SEVERITY_MEDIUM
            fix = "未知文件类型；检查 record_reader.py:CORE_FILES 是否需要更新"
            related = "skills/drive-record/scripts/record_reader.py"
        yield Gap(
            type="missing_file",
            severity=severity,
            location=f"{record.plan_dir.name}/{name}",
            description=f"文件缺失: {name}（{'Runtime SDK' if name in RUNTIME_FILES else 'LLM 契约' if name in LLM_CONTRACT_FILES else '未分类'}）",
            fix_suggestion=fix,
            related_runtime=related,
        )


def _detect_missing_events(record: Record) -> Iterable[Gap]:
    seen = {e.event for e in record.log_events}
    for evt in sorted(KEY_EVENT_TYPES):
        if evt not in seen:
            yield Gap(
                type="missing_event",
                severity=SEVERITY_HIGH,
                location=f"{record.plan_dir.name}/run-log.jsonl",
                description=f"关键事件缺失: {evt}",
                fix_suggestion=(
                    f"检查 state_cli.py:{evt} 调用点是否漏写"
                ),
                related_runtime="skills/state-machine/scripts/audit_append.py",
            )

    stage_advanced = [e for e in record.log_events if e.event == "stage_advanced"]
    expected = STAGE_ADVANCED_EXPECTED
    if len(stage_advanced) < expected:
        yield Gap(
            type="missing_event",
            severity=SEVERITY_MEDIUM,
            location=f"{record.plan_dir.name}/run-log.jsonl",
            description=(
                f"stage_advanced 次数 {len(stage_advanced)} 少于预期 {expected}（含回滚场景）"
            ),
            fix_suggestion=(
                "检查 evaluator 失败回滚或 pause/resume 是否漏写 stage_advanced"
            ),
        )


def _detect_missing_summary(record: Record) -> Iterable[Gap]:
    state = record.execute_state
    if state is None:
        return
    for task_id, info in state.task_results.items():
        status = str(info.get("status") or "")
        if status != "completed":
            continue
        if task_id not in record.artifacts:
            yield Gap(
                type="missing_summary",
                severity=SEVERITY_MEDIUM,
                location=f"{record.plan_dir.name}/artifacts/{task_id}/SUMMARY.md",
                description=f"task {task_id} 标 ok 但 SUMMARY.md 不存在",
                fix_suggestion=(
                    "executor 协议要求 ok 路径必须写 SUMMARY.md；检查 executor.md §回报"
                ),
                related_runtime="agents/executor.md",
            )


def _detect_revision_gap(record: Record) -> Iterable[Gap]:
    state = record.execute_state
    if state is None:
        return
    expected = state.revision
    spawn_revs: list[tuple[str, int]] = []
    for ev in record.log_events:
        if ev.event != "agent_spawned":
            continue
        rev = ev.details.get("state_revision_at_spawn")
        if isinstance(rev, int):
            spawn_revs.append((ev.ts, rev))
    if not spawn_revs:
        return
    max_seen = max(r for _, r in spawn_revs)
    if max_seen > expected:
        yield Gap(
            type="revision_gap",
            severity=SEVERITY_CRITICAL,
            location=f"{record.plan_dir.name}/executeState.json:revision={expected}",
            description=(
                f"run-log 记录 agent_spawned 时 revision={max_seen}，"
                f"executeState.json 当前 revision={expected}（应为 ≥ {max_seen}）"
            ),
            fix_suggestion=(
                "检查 state_write.py 的文件锁在并发场景下是否真持锁；"
                "可能某个 update 失败被吞了"
            ),
            related_runtime="skills/state-machine/scripts/state_write.py:158-174",
        )


def _detect_timestamp_anomaly(record: Record) -> Iterable[Gap]:
    ts_list = [_parse_ts(e.ts) for e in record.log_events]
    ts_list = [t for t in ts_list if t is not None]
    for prev, curr in zip(ts_list, ts_list[1:]):
        if curr < prev:
            yield Gap(
                type="timestamp_anomaly",
                severity=SEVERITY_MEDIUM,
                location=f"{record.plan_dir.name}/run-log.jsonl",
                description="事件时间戳出现倒序（违反 append-only 单调）",
                fix_suggestion=(
                    "检查 audit_append.py 的时钟源；NTP 跳变 / 跨时区进程并发可能造成"
                ),
                related_runtime="skills/state-machine/scripts/audit_append.py:29-31",
            )
            return


def _detect_pending_confirmation_stuck(record: Record) -> Iterable[Gap]:
    state = record.execute_state
    if state is None:
        return
    if not state.pending_confirmation:
        return
    updated = _parse_ts(state.updated_at)
    if updated is None:
        return
    elapsed = (_now() - updated).total_seconds()
    if elapsed > 3600:
        yield Gap(
            type="pending_confirmation_stuck",
            severity=SEVERITY_HIGH,
            location=f"{record.plan_dir.name}/executeState.json:pending_confirmation",
            description=(
                f"pending_confirmation={state.pending_confirmation!r} 已超过 1 小时未推进"
            ),
            fix_suggestion=(
                "drive 应该 /  超时 1 小时 自动 报警或升级；检查调度逻辑"
            ),
            related_runtime="skills/drive/scripts/dag_flow.py",
        )


def _detect_unknown_state_fields(record: Record) -> Iterable[Gap]:
    state = record.execute_state
    if state is None:
        return
    unknown = sorted(set(state.raw.keys()) - KNOWN_STATE_FIELDS)
    for name in unknown:
        yield Gap(
            type="unmapped_state_field",
            severity=SEVERITY_LOW,
            location=f"{record.plan_dir.name}/executeState.json:{name}",
            description=(
                f"未知字段 {name!r}（drive-2.3 schema 未声明；可能是 schema drift 早期信号）"
            ),
            fix_suggestion=(
                "检查 schema 是否新增字段未同步到 KNOWN_STATE_FIELDS；"
                "若是合法新字段，更新 gaps_detector.py"
            ),
            related_runtime="skills/drive-record/scripts/gaps_detector.py:KNOWN_STATE_FIELDS",
        )


def _detect_stale_running_agents(record: Record) -> Iterable[Gap]:
    """检测 agent_invocations 中 status=running 但 started_at > 30min 的 reviewer。

    reviewer 被 kill / 卡死会留 running 永久。HITL 暴露（用户在 REPORT.md §B 看到
    后决定补审 / 接受 / 手动标 failed），不自动改 state。

    PROP-20260820-001 §影响面 · reviewer 卡死处理。
    """
    state = record.execute_state
    if state is None:
        return
    invocations = state.raw.get("agent_invocations") or {}
    if not isinstance(invocations, dict):
        return
    now = _now()
    for task_id, reviewers in invocations.items():
        if not isinstance(reviewers, dict):
            continue
        for reviewer_name, inv in reviewers.items():
            if not isinstance(inv, dict):
                continue
            if inv.get("status") != "running":
                continue
            started = _parse_ts(inv.get("started_at") or "")
            if started is None:
                continue
            elapsed = (now - started).total_seconds()
            if elapsed > STALE_RUNNING_AGENT_SECONDS:
                yield Gap(
                    type="stale_running_agent",
                    severity=SEVERITY_HIGH,
                    location=(
                        f"{record.plan_dir.name}/executeState.json:"
                        f"agent_invocations.{task_id}.{reviewer_name}"
                    ),
                    description=(
                        f"{reviewer_name} 审 {task_id} 已 running "
                        f"{int(elapsed // 60)}min（阈值 {STALE_RUNNING_AGENT_SECONDS // 60}min）；"
                        f"reviewer 可能被 kill 或卡死"
                    ),
                    fix_suggestion=(
                        "用户决定：补审 / 接受现状 / 手动标 failed。"
                        "不自动改 state，保持 drive contract（state 只能走 SDK + audit）"
                    ),
                    related_runtime="skills/drive-record/scripts/gaps_detector.py:_detect_stale_running_agents",
                )


def detect_gaps(record: Record) -> tuple[Gap, ...]:
    gaps: list[Gap] = []
    gaps.extend(_detect_missing_files(record))
    gaps.extend(_detect_missing_events(record))
    gaps.extend(_detect_missing_summary(record))
    gaps.extend(_detect_revision_gap(record))
    gaps.extend(_detect_timestamp_anomaly(record))
    gaps.extend(_detect_pending_confirmation_stuck(record))
    gaps.extend(_detect_unknown_state_fields(record))
    gaps.extend(_detect_stale_running_agents(record))
    return tuple(
        sorted(gaps, key=lambda g: (SEVERITY_ORDER.get(g.severity, 99), g.type))
    )


def summarize(gaps: tuple[Gap, ...]) -> dict[str, Any]:
    by_sev: dict[str, int] = {SEVERITY_CRITICAL: 0, SEVERITY_HIGH: 0,
                               SEVERITY_MEDIUM: 0, SEVERITY_LOW: 0}
    for g in gaps:
        by_sev[g.severity] = by_sev.get(g.severity, 0) + 1
    total = len(gaps)
    return {
        "total": total,
        "critical": by_sev[SEVERITY_CRITICAL],
        "high": by_sev[SEVERITY_HIGH],
        "medium": by_sev[SEVERITY_MEDIUM],
        "low": by_sev[SEVERITY_LOW],
    }


__all__ = [
    "Gap",
    "SEVERITY_CRITICAL",
    "SEVERITY_HIGH",
    "SEVERITY_MEDIUM",
    "SEVERITY_LOW",
    "SEVERITY_ORDER",
    "KNOWN_STATE_FIELDS",
    "detect_gaps",
    "summarize",
]