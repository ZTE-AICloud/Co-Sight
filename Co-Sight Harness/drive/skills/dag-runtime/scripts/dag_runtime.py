"""dag_runtime：DAG 模式专属 state 读写入口。

DAG 模式的 agent 状态读写统一走本 CLI。依赖最小化（仅 stdlib + 同目录
envelope.py / state_write.py / audit_append.py）。

用法：
    python3 dag_runtime.py set-active-agents --planning-dir .drive/<plan_dir> --json '[{"id":"a","status":"running"}]'
    python3 dag_runtime.py mark-completed --planning-dir .drive/<plan_dir> --agent-id impl-auth
    python3 dag_runtime.py mark-failed    --planning-dir .drive/<plan_dir> --agent-id impl-auth
    python3 dag_runtime.py mark-skipped   --planning-dir .drive/<plan_dir> --agent-id impl-api
    python3 dag_runtime.py advance-wave   --planning-dir .drive/<plan_dir>
    python3 dag_runtime.py read-active-agents --planning-dir .drive/<plan_dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from envelope import (
    REASON_CONFIRMATION_REQUIRED,
    REASON_INVALID_AGENT,
    REASON_INVALID_ARG,
    REASON_RETRY_BUDGET_EXCEEDED,
    REASON_UNKNOWN_AGENT,
    REASON_VERDICT_NOT_PASS,
    REASON_WAVE_BARRIER_NOT_READY,
    Envelope,
    emit,
)
from audit_append import log as audit_log
from state_write import update_fields, read_state

VALID_STATUSES = frozenset(["pending", "running", "completed", "failed", "skipped"])
DEFAULT_MAX_RETRIES = 3


def _now_iso() -> str:
    """ISO8601 时间戳（带时区）。"""
    return datetime.now(timezone.utc).isoformat()


def _validate_status(status: str) -> str | None:
    """校验 status 合法；非法返回 hint。"""
    if status not in VALID_STATUSES:
        return f"status 必须是 {sorted(VALID_STATUSES)} 之一，收到 {status!r}"
    return None


# === 命令 ===

def cmd_set_active_agents(args: argparse.Namespace) -> Envelope:
    """设置 active_agents 列表（覆盖式）。

    输入 JSON 形如 [{"id": "...", "wave": N, "status": "...", "started_at": "..."}, ...]
    """
    try:
        agents = json.loads(args.json)
    except json.JSONDecodeError as exc:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error=f"--json 解析失败: {exc}",
            raw=args.json[:100],
        )

    if not isinstance(agents, list):
        return Envelope.fail(
            REASON_INVALID_ARG,
            error="--json 必须是 JSON 数组",
            got=type(agents).__name__,
        )

    # 校验每个 agent 字段
    for i, a in enumerate(agents):
        if not isinstance(a, dict):
            return Envelope.fail(
                REASON_INVALID_ARG,
                error=f"agents[{i}] 必须是 object",
                index=i,
            )
        if not a.get("id"):
            return Envelope.fail(
                REASON_INVALID_ARG,
                error=f"agents[{i}] 缺少 id",
                index=i,
            )
        status = a.get("status", "pending")
        err = _validate_status(status)
        if err:
            return Envelope.fail(
                REASON_INVALID_ARG,
                error=f"agents[{i}]: {err}",
                index=i,
            )

    # 节点重派为 running 时，撤销之前的人工确认。
    fields: dict[str, Any] = {"active_agents": agents}
    re_dispatched = [a["id"] for a in agents if a.get("status") == "running"]
    if re_dispatched:
        state = read_state(args.planning_dir)
        if state.ok:
            inner = state.data.get("state", state.data)
            confirmed = list(inner.get("confirmed_nodes") or [])
            pruned = [n for n in confirmed if n not in set(re_dispatched)]
            if len(pruned) != len(confirmed):
                fields["confirmed_nodes"] = pruned
                audit_log(
                    args.planning_dir,
                    "node_confirmations_revoked_on_redispatch",
                    revoked=[n for n in confirmed if n in set(re_dispatched)],
                    reason="节点重派为 running，旧确认失效",
                )
    return update_fields(args.planning_dir, **fields)


def cmd_mark_status(args: argparse.Namespace) -> Envelope:
    """mark-completed / mark-failed / mark-skipped 的共享逻辑。

    把 agent 的 active_agents 状态字段更新；其他 agent 的状态保留。

    mark-completed 是"产出可进下游"的宣告，default-deny：必须已确认。mark-failed /
    mark-skipped 不设门，cascade skip 必须能走。
    """
    status = args.status_value  # 由 subparser 设置
    agent_id = args.agent_id

    # 读当前 active_agents，找这个 agent
    state = read_state(args.planning_dir)
    if not state.ok:
        return state

    inner = state.data.get("state", state.data)
    active_agents = inner.get("active_agents", [])
    found = False
    for a in active_agents:
        if a.get("id") == agent_id:
            a["status"] = status
            a["updated_at"] = _now_iso()
            found = True
            break

    if not found:
        return Envelope.fail(
            REASON_INVALID_AGENT,
            error=f"active_agents 中找不到 agent_id={agent_id!r}",
            active_agent_ids=[a.get("id") for a in active_agents],
        )

    fields: dict[str, Any] = {"active_agents": active_agents}

    # mark-completed 必须经人工确认；mark-failed / mark-skipped 不设门。
    if status == "completed":
        gate = _gate_node_completed(inner, agent_id)
        if not gate.ok:
            return gate

    return update_fields(args.planning_dir, **fields)


def _gate_node_completed(state: dict, agent_id: str) -> Envelope:
    """完成态 gate 检查：读 `confirmed_nodes` 与 `auto_mode`，不放行则拒绝。"""
    if bool(state.get("auto_mode", False)):
        return Envelope.ok_envelope(gate="skipped", reason_skipped="auto_mode")

    confirmed = list(state.get("confirmed_nodes") or [])
    if agent_id in confirmed:
        return Envelope.ok_envelope(gate="cleared", agent_id=agent_id)

    return Envelope.fail(
        REASON_CONFIRMATION_REQUIRED,
        error=f"节点 {agent_id} 尚未经人工确认，不能标 completed",
        agent_id=agent_id,
        confirmed_nodes=confirmed,
        how_to_clear=(
            "把该节点产出讲给用户，等其明确放行后跑 "
            "confirm_node.py --planning-dir <dir> --agent-id " + agent_id
        ),
        note="该命令不在 skill 的 allowed-tools 内，执行时会向用户请求授权",
    )


def cmd_advance_wave(args: argparse.Namespace) -> Envelope:
    """把 current_wave 加 1；超最后一个 wave 时返回 fail。

    wave barrier fail-closed：current_wave 内仍有非终态节点（pending / running）
    时拒绝 advance，返回 REASON_WAVE_BARRIER_NOT_READY（非终态节点 id 列表）。
    """
    state = read_state(args.planning_dir)
    if not state.ok:
        return state

    inner = state.data.get("state", state.data)
    current_wave = inner.get("current_wave", 1)
    active_agents = inner.get("active_agents") or []
    non_terminal_in_current = [
        a.get("id") for a in active_agents
        if a.get("wave") == current_wave and a.get("status") in {"pending", "running"}
    ]
    if non_terminal_in_current:
        return Envelope.fail(
            REASON_WAVE_BARRIER_NOT_READY,
            error=f"current_wave {current_wave} 仍有 {len(non_terminal_in_current)} 个非终态节点，需全部 mark-* 才可 advance",
            current_wave=current_wave,
            non_terminal_ids=non_terminal_in_current,
        )

    new_wave = current_wave + 1

    waves_total = inner.get("waves_total")
    if waves_total is None:
        waves_path = Path(args.planning_dir) / "waves.yaml"
        if waves_path.is_file():
            try:
                import yaml  # noqa: PLC0415

                doc = yaml.safe_load(waves_path.read_text(encoding="utf-8"))
            except (ImportError, OSError):
                doc = None
            if isinstance(doc, dict):
                waves = doc.get("waves")
                if isinstance(waves, list) and waves:
                    waves_total = len(waves)
    if waves_total is not None and new_wave > waves_total:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error=f"current_wave 已达最大（{waves_total}），不可再 advance",
            current_wave=current_wave,
            waves_total=waves_total,
        )

    return update_fields(args.planning_dir, current_wave=new_wave)


def cmd_read_active_agents(args: argparse.Namespace) -> Envelope:
    """读 active_agents 列表。

    read_state 的 data 结构是 {"state": {...}, "path": "..."}，
    所以读嵌套字段：state.data["state"]["active_agents"]。
    """
    state = read_state(args.planning_dir)
    if not state.ok:
        return state
    inner = state.data.get("state", state.data)
    return Envelope.ok_envelope(
        active_agents=inner.get("active_agents", []),
        current_wave=inner.get("current_wave", 1),
    )


def cmd_set_waves_total(args: argparse.Namespace) -> Envelope:
    """写 state.waves_total。dag_init.plan_waves 在 set-active-agents 之后调。

    waves_total 与 active_agents[]、current_wave 同属 dag-runtime 的 state 字段。
    """
    return update_fields(args.planning_dir, waves_total=args.total)


def cmd_check_terminal_verdict(args: argparse.Namespace) -> Envelope:
    """检查 verdict_required agents 是否全部 state.verdicts[id] == pass。

    DAG 模式 verdict_required=true 表示该 terminal agent 完成前必须先有 verdict=pass。
    extract_verdict.py 把每个 verdict_required agent 自己的 verdict 写到
    state.verdicts[agent_id]，本函数读 map 做 AND。

    无 verdict_required agent → 直接 ok。
    任一 verdict_required agent 没有 verdict entry → fail（不是 pass）。
    任一 verdict_required agent verdict != pass → fail。
    """
    try:
        agent_ids = json.loads(args.verdict_required_agents)
    except json.JSONDecodeError as exc:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error=f"--verdict-required-agents 解析失败: {exc}",
            raw=args.verdict_required_agents[:100],
        )

    if not isinstance(agent_ids, list) or not all(isinstance(a, str) for a in agent_ids):
        return Envelope.fail(
            REASON_INVALID_ARG,
            error="--verdict-required-agents 必须是 JSON 字符串数组",
            got_type=type(agent_ids).__name__,
        )

    state = read_state(args.planning_dir)
    if not state.ok:
        return state

    inner = state.data.get("state", state.data)
    verdicts_map = inner.get("verdicts") or {}

    if not agent_ids:
        return Envelope.ok_envelope(
            required_count=0,
            check="no_agents_require_verdict",
        )

    failed: list[str] = []
    missing: list[str] = []
    for aid in agent_ids:
        v = verdicts_map.get(aid)
        if v is None:
            missing.append(aid)
        elif v != "pass":
            failed.append(f"{aid}={v}")

    if missing or failed:
        return Envelope.fail(
            REASON_VERDICT_NOT_PASS,
            error=(
                f"verdict_required agents: {agent_ids}，"
                f"missing=[{missing}], non-pass=[{failed}]。"
                f"每个 verdict_required agent 必须有 verdict=pass 才能收工。"
            ),
            required_agents=agent_ids,
            missing=missing,
            non_pass=failed,
        )

    return Envelope.ok_envelope(
        required_count=len(agent_ids),
        all_verdicts=verdicts_map,
        check="all_pass",
    )


def cmd_mark_retry_attempted(args: argparse.Namespace) -> Envelope:
    """记录一次 retry 尝试。

    - 累加 active_agents[id].retry_count
    - 写 last_retry_at + last_retry_reason
    - 清除 state.verdicts[id]
    - run-log append `node_retry_attempted` 事件（agent_id / retry_count / reason）
    - 不改 status
    - 不触碰人工确认记录
    - retry_count 当前值 >= max_retries（默认 3）时返回 REASON_RETRY_BUDGET_EXCEEDED
    """
    agent_id = args.agent_id
    if not agent_id:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error="--agent-id 必填",
        )

    max_retries = getattr(args, "max_retries", None)
    if max_retries is None:
        max_retries = DEFAULT_MAX_RETRIES
    if max_retries < 0:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error="--max-retries 不能为负",
        )

    state_resp = read_state(args.planning_dir)
    if not state_resp.ok:
        return state_resp
    inner = state_resp.data.get("state", state_resp.data)

    active_agents = list(inner.get("active_agents") or [])
    found = False
    current_retry_count = 0
    for a in active_agents:
        if a.get("id") == agent_id:
            current_retry_count = int(a.get("retry_count") or 0)
            if current_retry_count >= max_retries:
                return Envelope.fail(
                    REASON_RETRY_BUDGET_EXCEEDED,
                    error=f"agent_id={agent_id!r} 已 retry {current_retry_count} 次，达到上限 {max_retries}",
                    agent_id=agent_id,
                    retry_count=current_retry_count,
                    max_retries=max_retries,
                    active_agent_ids=[a.get("id") for a in active_agents],
                )
            new_count = current_retry_count + 1
            a["retry_count"] = new_count
            a["last_retry_at"] = _now_iso()
            if getattr(args, "reason", None):
                a["last_retry_reason"] = args.reason
            found = True
            break

    if not found:
        return Envelope.fail(
            REASON_UNKNOWN_AGENT,
            error=f"active_agents 中找不到 agent_id={agent_id!r}",
            active_agent_ids=[a.get("id") for a in active_agents],
        )

    fields: dict[str, Any] = {"active_agents": active_agents}

    verdicts = dict(inner.get("verdicts") or {})
    if agent_id in verdicts:
        verdicts.pop(agent_id)
        fields["verdicts"] = verdicts

    audit_log(
        args.planning_dir,
        "node_retry_attempted",
        agent_id=agent_id,
        retry_count=new_count,
        reason=getattr(args, "reason", None),
    )

    return update_fields(args.planning_dir, **fields)


# === CLI ===

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dag_runtime",
        description="DAG 模式 executeState.json 读写入口（仅 stdlib + 同目录 envelope/state_write）",
    )
    parser.add_argument(
        "--planning-dir",
        type=Path,
        required=True,
        help="规划目录（含 executeState.json）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set-active-agents", help="设置 active_agents 列表（覆盖）")
    p_set.add_argument("--json", required=True, help="agents JSON 数组")

    # mark-* 共享一个 factory
    for status in ("completed", "failed", "skipped"):
        p = sub.add_parser(f"mark-{status}", help=f"标记 agent 为 {status}")
        p.add_argument("--agent-id", required=True, help="要标记的 agent id")
        p.set_defaults(status_value=status)

    sub.add_parser("advance-wave", help="current_wave += 1")

    p_total = sub.add_parser("set-waves-total", help="写 state.waves_total（dag_init 初始化时调）")
    p_total.add_argument("--total", type=int, required=True, help="总 wave 数")

    sub.add_parser("read-active-agents", help="读 active_agents 列表")

    p_check = sub.add_parser(
        "check-terminal-verdict",
        help="检查 verdict_required agent 是否全部 state.verdicts[id] == pass",
    )
    p_check.add_argument(
        "--verdict-required-agents",
        required=True,
        help='verdict_required=true 的 agent id JSON 数组，形如 \'["evaluator"]\'',
    )

    p_retry = sub.add_parser(
        "mark-retry-attempted",
        help="记录一次 retry 尝试（累加 retry_count / 清 verdict / 写 audit）",
    )
    p_retry.add_argument("--agent-id", required=True, help="要记录 retry 的 agent id")
    p_retry.add_argument("--reason", default=None, help="retry 原因（写入 last_retry_reason 与 audit）")
    p_retry.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="retry 上限；不传则用默认 3。retry_count 已达上限时拒绝本次重试",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.command == "set-active-agents":
        emit(cmd_set_active_agents(args))
        return

    if args.command in ("mark-completed", "mark-failed", "mark-skipped"):
        emit(cmd_mark_status(args))
        return

    if args.command == "advance-wave":
        emit(cmd_advance_wave(args))
        return

    if args.command == "set-waves-total":
        emit(cmd_set_waves_total(args))
        return

    if args.command == "read-active-agents":
        emit(cmd_read_active_agents(args))
        return

    if args.command == "check-terminal-verdict":
        emit(cmd_check_terminal_verdict(args))
        return

    if args.command == "mark-retry-attempted":
        emit(cmd_mark_retry_attempted(args))
        return


__all__ = [
    "cmd_set_active_agents",
    "cmd_mark_status",
    "cmd_advance_wave",
    "cmd_set_waves_total",
    "cmd_read_active_agents",
    "cmd_check_terminal_verdict",
    "cmd_mark_retry_attempted",
    "VALID_STATUSES",
]


if __name__ == "__main__":
    main(sys.argv[1:])