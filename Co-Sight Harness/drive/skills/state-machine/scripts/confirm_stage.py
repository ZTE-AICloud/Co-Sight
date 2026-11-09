"""人工放行某个阶段 —— HITL 的唯一入口。

**本脚本刻意不在任何 skill 的 allowed-tools 内。** 模型执行它时 Claude Code 会
向用户请求授权，那个授权提示就是人工确认本身。这样"人必须点头"由 harness 强制，
不依赖模型自觉。

放行是逐阶段的，不能批量：每个阶段的产出都要人看过。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audit_append import log as audit_log
from envelope import Envelope, REASON_INVALID_ARG
from state_rules import STAGES
from state_write import require_state, update_fields
from workflow_runtime import WorkflowRuntimeError, resolve_active_stages

REASON_ALREADY_CONFIRMED = "already_confirmed"


def confirm_stage(
    planning_dir: Path, stage: str, *, note: str | None = None
) -> Envelope:
    """把 stage 记入 confirmed_stages，清掉待确认标记。

    Args:
        planning_dir: .planning 目录
        stage: 被放行的阶段
        note: 用户的放行说明，写进留痕便于回溯当时为什么放行

    双轨校验：builtin 路径 resolve_active_stages 返 STAGES，用户 yaml 路径返
    parse_user_workflow_phases(planning_dir).stages。argparse help 仍静态用 STAGES
    拼接；用户 yaml 路径下 help 信息不准确是已知 trade-off，运行时校验会精确报错。
    """
    try:
        active_stages, _source = resolve_active_stages(planning_dir)
    except WorkflowRuntimeError as exc:
        return Envelope.fail(REASON_INVALID_ARG, error=str(exc))
    if stage not in active_stages:
        return Envelope.fail(
            REASON_INVALID_ARG, error=f"未知阶段: {stage!r}", valid=sorted(active_stages)
        )

    current = require_state(planning_dir)
    if not current.ok:
        return current

    state = current.data["state"]
    confirmed = list(state.get("confirmed_stages") or [])
    if stage in confirmed:
        return Envelope.fail(
            REASON_ALREADY_CONFIRMED,
            error=f"{stage} 已确认过，无需重复放行",
            confirmed_stages=confirmed,
        )

    confirmed.append(stage)
    pending = state.get("pending_confirmation")
    env = update_fields(
        planning_dir,
        confirmed_stages=confirmed,
        pending_confirmation=None if pending == stage else pending,
    )
    if not env.ok:
        return env

    audit_log(planning_dir, "stage_confirmed", stage=stage, note=note or "")
    return Envelope.ok_envelope(
        stage=stage,
        confirmed_stages=confirmed,
        revision=env.data.get("revision"),
    )


def revoke_stage(planning_dir: Path, stage: str) -> Envelope:
    """撤回某阶段的放行 —— 回退重做后需要重新确认。"""
    current = require_state(planning_dir)
    if not current.ok:
        return current

    confirmed = list(current.data["state"].get("confirmed_stages") or [])
    if stage not in confirmed:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error=f"{stage} 未在已确认列表里",
            confirmed_stages=confirmed,
        )

    confirmed.remove(stage)
    env = update_fields(planning_dir, confirmed_stages=confirmed)
    if not env.ok:
        return env

    audit_log(planning_dir, "stage_confirmation_revoked", stage=stage)
    return Envelope.ok_envelope(stage=stage, confirmed_stages=confirmed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="人工放行一个阶段（HITL 唯一入口）"
    )
    parser.add_argument("--planning-dir", required=True)
    parser.add_argument("--stage", required=True, help=f"可选值: {', '.join(STAGES)}")
    parser.add_argument("--note", default=None, help="放行说明，写进 run-log")
    parser.add_argument(
        "--revoke", action="store_true", help="撤回放行（回退重做后用）"
    )
    args = parser.parse_args(argv)

    planning_dir = Path(args.planning_dir)
    env = (
        revoke_stage(planning_dir, args.stage)
        if args.revoke
        else confirm_stage(planning_dir, args.stage, note=args.note)
    )
    print(env.to_json())
    return env.exit_code()


if __name__ == "__main__":
    sys.exit(main())
