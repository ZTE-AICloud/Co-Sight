"""executeState.json schema 校验。

drive-2.3 runtime 只产出 executeState.json（JSON object）。本文件是该对象的
结构性 / 语义性校验；持久化与 revision 锁由 state_write.py 负责。

校验分两档：
- validate_execute_state(state): 顶层字段与 active_stage 取值
- validate_dag_state(state):     DAG mode 额外字段（active_agents / current_wave / mode）
"""
from __future__ import annotations

from typing import Any

from state_rules import STAGES, TERMINAL_STAGE  # noqa: F401
from workflow_runtime import WorkflowRuntimeError, resolve_active_stages

# executeState.json 顶层合法字段。`default_state()` 默认写入的全部 + 可选 verdict。
# 任何不在此列表的顶层 key 一律视为 schema 漂移信号。
COMMON_FIELDS: frozenset[str] = frozenset({
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
    "confirmed_nodes",
    "pending_confirmation",
    "verdict",
    "custom_agents",
    "active_agents",
    "mode",
    "agent_invocations",
    "created_at",
    "updated_at",
})

VALID_VERDICTS: frozenset[str] = frozenset({"pass", "fail", "partial"})

DAG_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "mode",
    "active_agents",
    "current_wave",
})

DAG_VALID_AGENT_STATUSES: frozenset[str] = frozenset({
    "running", "completed", "failed", "skipped",
})

AGENT_INVOCATION_STATUSES: frozenset[str] = DAG_VALID_AGENT_STATUSES

VALID_REVIEWER_VERDICTS: frozenset[str] = frozenset({
    "approve", "warning", "block",
})


def validate_execute_state(
    state: Any,
    planning_dir: Path | None = None,
) -> tuple[bool, str]:
    """校验 executeState.json 的顶层结构。

    检查项：
    - state 必须是 dict
    - active_stage 必须是 STAGES 之一
    - revision 必须是 int（>= 0）
    - 顶层字段名必须在 COMMON_FIELDS 内（schema 漂移检测）

    planning_dir 可选：
    - 不传 → 走 builtin STAGES（向后兼容；旧调用方行为零变化）
    - 传 → 走 resolve_active_stages(planning_dir) 双轨

    Returns:
        (ok, reason) — ok=True 表示通过
    """
    if not isinstance(state, dict):
        return False, f"state 必须是 dict, 收到 {type(state).__name__}"

    # 双轨：planning_dir 决定 STAGES 来源
    if planning_dir is not None:
        try:
            active_stages, _source = resolve_active_stages(planning_dir)
        except WorkflowRuntimeError as exc:
            return False, f"active_stage 校验前置失败: {exc}"
    else:
        active_stages = STAGES

    active = state.get("active_stage")
    if active not in active_stages:
        return False, (
            f"active_stage {active!r} 非法；合法值: {sorted(active_stages)}"
        )

    revision = state.get("revision")
    if revision is not None and not isinstance(revision, int):
        return False, f"revision 必须是 int, 收到 {type(revision).__name__}"

    verdict = state.get("verdict")
    if verdict is not None and verdict not in VALID_VERDICTS:
        return False, (
            f"verdict {verdict!r} 非法；合法值: {sorted(VALID_VERDICTS)}"
        )

    unknown = set(state.keys()) - COMMON_FIELDS
    if unknown:
        return False, f"未知顶层字段 (schema 漂移): {sorted(unknown)}"

    # agent_invocations optional 字段：只在存在时校验（向后兼容旧 state 文件）
    invocations = state.get("agent_invocations")
    if invocations is not None:
        ok, reason = validate_agent_invocations(invocations)
        if not ok:
            return False, reason

    return True, ""


def validate_dag_state(state: dict[str, Any]) -> tuple[bool, str]:
    """校验 executeState.json 的 DAG 模式字段。

    DAG mode 在 executeState.json 用 mode='dag' 标识，agent 进度走
    active_agents 列表而非 STAGES 流转。

    Args:
        state: executeState.json dict（含 mode / active_agents / current_wave）

    Returns:
        (ok, reason)
    """
    if not isinstance(state, dict):
        return False, f"state 必须是 dict, 收到 {type(state).__name__}"

    if state.get("mode") != "dag":
        return False, "validate_dag_state 要求 mode=='dag'"

    missing = DAG_REQUIRED_FIELDS - set(state.keys())
    if missing:
        return False, f"DAG state 缺少必填字段: {sorted(missing)}"

    if not isinstance(state.get("current_wave"), int):
        return False, "current_wave 必须是整数"

    active_agents = state.get("active_agents", [])
    if not isinstance(active_agents, list):
        return False, "active_agents 必须是列表"

    seen_ids: set[str] = set()
    for i, a in enumerate(active_agents):
        if not isinstance(a, dict):
            return False, f"active_agents[{i}] 必须是 dict"
        if not a.get("id"):
            return False, f"active_agents[{i}] 缺少 id"
        if a["id"] in seen_ids:
            return False, f"active_agents[{i}] id 重复: {a['id']!r}"
        seen_ids.add(a["id"])
        status = a.get("status")
        if status is not None and status not in DAG_VALID_AGENT_STATUSES:
            return False, (
                f"active_agents[{i}].status {status!r} 非法；"
                f"必须是 {sorted(DAG_VALID_AGENT_STATUSES)} 之一"
            )

    return True, ""


def validate_agent_invocations(invocations: Any) -> tuple[bool, str]:
    """校验 agent_invocations 嵌套结构（phase mode reviewer 调用记录）。

    形状：
        {<task_id>: {<reviewer_name>: {
            status, started_at, finished_at, duration_sec, verdict,
            findings, attempt
        }}}

    字段约束：
    - status: 必填；AGENT_INVOCATION_STATUSES 之一
    - verdict: 可选（未完成时 None）；VALID_REVIEWER_VERDICTS 之一
    - findings: 可选；dict 含 {critical, high, medium, low} 全非负 int
    - attempt: 可选；≥1 的 int
    - duration_sec: 可选；数字

    Args:
        invocations: state["agent_invocations"] 的值

    Returns:
        (ok, reason)
    """
    if not isinstance(invocations, dict):
        return False, (
            f"agent_invocations 必须是 dict, 收到 {type(invocations).__name__}"
        )

    for task_id, reviewers in invocations.items():
        if not isinstance(reviewers, dict):
            return False, (
                f"agent_invocations[{task_id!r}] 必须是 dict, "
                f"收到 {type(reviewers).__name__}"
            )
        for reviewer_name, inv in reviewers.items():
            if not isinstance(inv, dict):
                return False, (
                    f"agent_invocations[{task_id!r}][{reviewer_name!r}] 必须是 dict, "
                    f"收到 {type(inv).__name__}"
                )

            status = inv.get("status")
            if status not in AGENT_INVOCATION_STATUSES:
                return False, (
                    f"agent_invocations[{task_id!r}][{reviewer_name!r}].status "
                    f"{status!r} 非法；合法值: {sorted(AGENT_INVOCATION_STATUSES)}"
                )

            verdict = inv.get("verdict")
            if verdict is not None and verdict not in VALID_REVIEWER_VERDICTS:
                return False, (
                    f"agent_invocations[{task_id!r}][{reviewer_name!r}].verdict "
                    f"{verdict!r} 非法；合法值: {sorted(VALID_REVIEWER_VERDICTS)}"
                )

            findings = inv.get("findings")
            if findings is not None:
                if not isinstance(findings, dict):
                    return False, (
                        f"agent_invocations[{task_id!r}][{reviewer_name!r}]"
                        f".findings 必须是 dict"
                    )
                required = {"critical", "high", "medium", "low"}
                missing = required - set(findings.keys())
                if missing:
                    return False, (
                        f"agent_invocations[{task_id!r}][{reviewer_name!r}]"
                        f".findings 缺字段: {sorted(missing)}"
                    )
                for k, v in findings.items():
                    if not isinstance(v, int) or v < 0:
                        return False, (
                            f"agent_invocations[{task_id!r}][{reviewer_name!r}]"
                            f".findings[{k!r}] {v!r} 必须是非负整数"
                        )

            attempt = inv.get("attempt")
            if attempt is not None and (
                not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1
            ):
                return False, (
                    f"agent_invocations[{task_id!r}][{reviewer_name!r}].attempt "
                    f"{attempt!r} 必须是 ≥1 的整数"
                )

            duration = inv.get("duration_sec")
            if duration is not None and not isinstance(duration, (int, float)):
                return False, (
                    f"agent_invocations[{task_id!r}][{reviewer_name!r}]"
                    f".duration_sec {duration!r} 必须是数字"
                )

    return True, ""


__all__ = [
    "STAGES",
    "TERMINAL_STAGE",
    "COMMON_FIELDS",
    "VALID_VERDICTS",
    "DAG_REQUIRED_FIELDS",
    "DAG_VALID_AGENT_STATUSES",
    "AGENT_INVOCATION_STATUSES",
    "VALID_REVIEWER_VERDICTS",
    "validate_execute_state",
    "validate_dag_state",
    "validate_agent_invocations",
]