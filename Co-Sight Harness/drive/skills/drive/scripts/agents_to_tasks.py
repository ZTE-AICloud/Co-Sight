"""agents_to_tasks.py — drive 的 AgentSpec → topo tasks 转换。

把 workflow.yaml 的 agents 列表转换成 wave-scheduling 接受的 tasks JSON
（`[{task_id, depends_on}, ...]`）。

调用方流程：

    python3 agents_to_tasks.py --workflow <yaml> \
        | python3 topo_sort.py topo-sort-from-tasks \
        | python3 apply_concurrency_cap.py --max-concurrent N

成功时 stdout 是裸 JSON 数组（直接 pipe 给 topo-sort-from-tasks）；
失败时 stderr 输出 envelope（exit code 1）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from envelope import Envelope, REASON_FILE_MISSING, REASON_INVALID_ARG, REASON_SCHEMA_INVALID


def load_tasks(workflow_path: Path) -> list[dict]:
    """从 workflow.yaml 读 agents → tasks list。"""
    if not workflow_path.is_file():
        raise FileNotFoundError(f"workflow.yaml 不存在: {workflow_path}")

    doc = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("workflow.yaml 顶层必须是 mapping")
    if str(doc.get("mode", "phase")).strip() != "dag":
        raise ValueError("workflow.yaml mode 必须是 'dag'")

    agents = doc.get("agents", [])
    if not isinstance(agents, list):
        raise ValueError("agents 必须是列表")
    if not agents:
        raise ValueError("agents 列表为空")

    tasks: list[dict] = []
    seen: set[str] = set()
    for a in agents:
        if not isinstance(a, dict):
            raise ValueError(f"agent 必须是 mapping: {a!r}")
        tid = str(a.get("id", "")).strip()
        if not tid:
            raise ValueError("agent 缺少 id")
        if tid in seen:
            raise ValueError(f"agent id 重复: {tid!r}")
        seen.add(tid)
        deps = a.get("depends_on") or []
        if not isinstance(deps, list):
            raise ValueError(f"{tid}.depends_on 必须是 list")
        tasks.append({"task_id": tid, "depends_on": [str(d) for d in deps]})

    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="workflow.yaml agents → topo tasks JSON")
    parser.add_argument("--workflow", type=Path, required=True, help="workflow.yaml 路径")
    args = parser.parse_args(argv)

    try:
        tasks = load_tasks(args.workflow)
    except FileNotFoundError as exc:
        env = Envelope.fail(REASON_FILE_MISSING, path=str(args.workflow), error=str(exc))
    except ValueError as exc:
        env = Envelope.fail(REASON_SCHEMA_INVALID, path=str(args.workflow), error=str(exc))
    except Exception as exc:
        env = Envelope.fail(REASON_INVALID_ARG, error=str(exc))
    else:
        print(json.dumps(tasks, ensure_ascii=False), flush=True)
        return 0

    print(env.to_json(), file=sys.stderr, flush=True)
    return env.exit_code()


if __name__ == "__main__":
    sys.exit(main())
