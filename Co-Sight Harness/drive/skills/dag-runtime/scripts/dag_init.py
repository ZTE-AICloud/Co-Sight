"""dag_init.py —— DAG 模式 plan-waves 初始化入口。

调用：
    python3 dag_init.py plan-waves --workflow <yaml> --planning-dir <dir> --waves-json @<waves>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from envelope import (
    Envelope,
    REASON_INVALID_ARG,
    REASON_SCHEMA_INVALID,
    REASON_SUBPROCESS_TIMEOUT,
    emit,
)

SCRIPT_DIR = Path(__file__).parent
DAG_RUNTIME = SCRIPT_DIR / "dag_runtime.py"


def _run_subprocess(cmd: list[str], input_data: str | None = None, timeout: int = 30) -> dict[str, Any]:
    """调子进程，解析 envelope 协议。"""
    try:
        proc = subprocess.run(
            [sys.executable] + cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return Envelope.fail(
            REASON_SUBPROCESS_TIMEOUT, cmd=cmd, timeout=timeout
        ).to_dict()
    except FileNotFoundError as exc:
        return Envelope.fail(
            "file_not_found", cmd=cmd, error=str(exc)
        ).to_dict()

    if proc.returncode != 0:
        try:
            payload = json.loads(proc.stdout)
            if isinstance(payload, dict) and "ok" in payload:
                return payload
        except json.JSONDecodeError:
            pass
        return Envelope.fail(
            "subprocess_failed",
            cmd=cmd,
            returncode=proc.returncode,
            stderr=proc.stderr[:500],
        ).to_dict()

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return Envelope.fail(
            "subprocess_decode_failed",
            cmd=cmd,
            stdout=proc.stdout[:500],
            error=str(exc),
        ).to_dict()


def plan_waves(
    workflow: Path | dict[str, Any],
    waves: list[list[str]],
    *,
    planning_dir: Path,
) -> dict[str, Any]:
    """一次性初始化 DAG 调度的 wave 划分（caller 算好 waves 传入）。

    `workflow` 可为 workflow.yaml 路径（CLI 路径）或已解析的 spec dict（Python 调用）。

    Returns:
        ok: data={waves, agents_by_id, total_waves, total_agents}
        fail: reason=schema_invalid / subprocess_failed / ...
    """
    if isinstance(workflow, Path):
        if not workflow.is_file():
            return Envelope.fail(
                REASON_INVALID_ARG,
                hint=f"workflow.yaml 不存在: {workflow}",
            ).to_dict()
        try:
            raw = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return Envelope.fail(
                REASON_SCHEMA_INVALID,
                yaml_error=str(exc),
            ).to_dict()
    else:
        raw = workflow

    if not isinstance(raw, dict) or raw.get("mode") != "dag":
        return Envelope.fail(
            REASON_SCHEMA_INVALID,
            hint="workflow 不是 DAG 模式",
        ).to_dict()

    agents = raw.get("agents", [])
    if not agents:
        return Envelope.fail(
            REASON_SCHEMA_INVALID,
            hint="agents 列表为空",
        ).to_dict()

    if not waves:
        return Envelope.fail(
            REASON_SCHEMA_INVALID,
            hint="waves 列表为空",
        ).to_dict()

    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    active_agents_payload: list[dict[str, Any]] = []
    for i, wave in enumerate(waves, start=1):
        for agent_id in wave:
            active_agents_payload.append({
                "id": agent_id,
                "wave": i,
                "status": "pending",
                "started_at": started_at,
            })

    result = _run_subprocess(
        [
            str(DAG_RUNTIME),
            "--planning-dir",
            str(planning_dir),
            "set-active-agents",
            "--json",
            json.dumps(active_agents_payload, ensure_ascii=False),
        ]
    )
    if not result.get("ok"):
        return result

    # 写 waves_total（default_state 给 1，多 wave 时 advance-wave 会因
    # new_wave > waves_total 卡住 wave 1）。dag_runtime 自己写自己的 state 字段。
    result = _run_subprocess(
        [
            str(DAG_RUNTIME),
            "--planning-dir",
            str(planning_dir),
            "set-waves-total",
            "--total",
            str(len(waves)),
        ]
    )
    if not result.get("ok"):
        return result

    return {
        "ok": True,
        "data": {
            "waves": waves,
            "agents_by_id": {a["id"]: a for a in agents},
            "total_waves": len(waves),
            "total_agents": len(agents),
        },
    }


def _load_waves_arg(value: str) -> list[list[str]]:
    """解析 --waves-json：JSON 字符串或 @<file> 路径。"""
    if value.startswith("@"):
        path = Path(value[1:])
        if not path.is_file():
            raise FileNotFoundError(f"waves 文件不存在: {path}")
        raw = path.read_text(encoding="utf-8")
    else:
        raw = value

    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not all(isinstance(w, list) for w in parsed):
        raise ValueError("--waves-json 必须是 [[agent_id, ...], ...] 形式")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dag_init",
        description="DAG 模式 plan-waves 初始化",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser(
        "plan-waves",
        help="用 caller 算好的 waves 初始化 executeState.json",
    )
    p_plan.add_argument("--workflow", type=Path, required=True, help="workflow.yaml 路径")
    p_plan.add_argument("--planning-dir", type=Path, required=True)
    p_plan.add_argument(
        "--waves-json",
        type=str,
        required=True,
        help="JSON 字符串或 @<file> 路径，内容为 [[agent_id, ...], ...]",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.command == "plan-waves":
        try:
            waves = _load_waves_arg(args.waves_json)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            emit(
                Envelope.fail(
                    REASON_INVALID_ARG,
                    flag="--waves-json",
                    error=str(exc),
                )
            )
            return
        result = plan_waves(args.workflow, waves, planning_dir=args.planning_dir)
        emit(result)
        return

    emit(Envelope.fail("unknown_command", command=args.command))


__all__ = ["plan_waves"]


if __name__ == "__main__":
    main(sys.argv[1:])
