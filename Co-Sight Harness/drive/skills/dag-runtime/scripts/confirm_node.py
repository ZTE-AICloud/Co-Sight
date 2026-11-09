"""人工放行某个 DAG 节点 —— DAG 模式 HITL 的唯一入口。

**本脚本刻意不在任何 skill 的 allowed-tools 内。** 模型执行它时 Claude Code 会
向用户请求授权，那个授权提示就是人工确认本身。这样"人必须点头"由 harness 强制，
不依赖模型自觉。

放行是逐节点的，不能批量：每个 agent 节点的产出都要人看过。

DAG 不认 complexity —— 无论 trivial / standard / complex，每个节点都要人点头。
auto_mode 仍然是唯一的全局旁路。

节点 id 合法性对着 active_agents 里的 id 校验，对应 confirm_stage.py 对 STAGES
做的那道校验。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audit_append import log as audit_log
from envelope import (
    REASON_ALREADY_CONFIRMED,
    REASON_INVALID_ARG,
    REASON_UNKNOWN_AGENT,
    Envelope,
)
from state_write import require_state, update_fields


def _active_agent_ids(state: dict) -> list[str]:
    active = state.get("active_agents") or []
    return [str(a["id"]) for a in active if isinstance(a, dict) and a.get("id")]


def confirm_node(
    planning_dir: Path, agent_id: str, *, note: str | None = None
) -> Envelope:
    """把 agent_id 记入 confirmed_nodes。

    Args:
        planning_dir: .drive/<plan_dir>/ 目录
        agent_id: 被放行的节点 id（必须存在于 active_agents 里）
        note: 用户的放行说明，写进留痕便于回溯当时为什么放行
    """
    current = require_state(planning_dir)
    if not current.ok:
        return current

    state = current.data["state"]

    known = _active_agent_ids(state)
    if agent_id not in known:
        return Envelope.fail(
            REASON_UNKNOWN_AGENT,
            error=f"agent_id={agent_id!r} 不在 active_agents 里",
            active_agent_ids=known,
        )

    confirmed = list(state.get("confirmed_nodes") or [])
    if agent_id in confirmed:
        return Envelope.fail(
            REASON_ALREADY_CONFIRMED,
            error=f"{agent_id} 已确认过，无需重复放行",
            confirmed_nodes=confirmed,
        )

    confirmed.append(agent_id)
    env = update_fields(planning_dir, confirmed_nodes=confirmed)
    if not env.ok:
        return env

    audit_log(planning_dir, "node_confirmed", agent_id=agent_id, note=note or "")
    return Envelope.ok_envelope(
        agent_id=agent_id,
        confirmed_nodes=confirmed,
        revision=env.data.get("revision"),
    )


def revoke_node(planning_dir: Path, agent_id: str) -> Envelope:
    """撤回某节点的放行 —— 重做后需要重新确认。"""
    current = require_state(planning_dir)
    if not current.ok:
        return current

    confirmed = list(current.data["state"].get("confirmed_nodes") or [])
    if agent_id not in confirmed:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error=f"{agent_id} 未在已确认列表里",
            confirmed_nodes=confirmed,
        )

    confirmed.remove(agent_id)
    env = update_fields(planning_dir, confirmed_nodes=confirmed)
    if not env.ok:
        return env

    audit_log(planning_dir, "node_confirmation_revoked", agent_id=agent_id)
    return Envelope.ok_envelope(agent_id=agent_id, confirmed_nodes=confirmed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="人工放行一个 DAG 节点（DAG 模式 HITL 唯一入口）"
    )
    parser.add_argument("--planning-dir", required=True)
    parser.add_argument("--agent-id", required=True, help="active_agents 里的节点 id")
    parser.add_argument("--note", default=None, help="放行说明，写进 run-log")
    parser.add_argument(
        "--revoke", action="store_true", help="撤回放行（重做后用）"
    )
    args = parser.parse_args(argv)

    planning_dir = Path(args.planning_dir)
    env = (
        revoke_node(planning_dir, args.agent_id)
        if args.revoke
        else confirm_node(planning_dir, args.agent_id, note=args.note)
    )
    print(env.to_json())
    return env.exit_code()


if __name__ == "__main__":
    sys.exit(main())
