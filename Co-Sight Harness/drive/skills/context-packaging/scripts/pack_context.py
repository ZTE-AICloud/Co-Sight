"""context_pack — plan 阶段预打包每个 task 的上下文快照。

planner 在 schedule-waves 之后调用本脚本，为每个 task 生成
.drive/<plan_dir>/context_pack/<task_id>.json，减少 executor 的冷启动
IO：读全量 taskRecord + manifest 从 3-5m 降到 <1m（digest 命中时）。

worker 启动时优先读 context_pack/<task_id>.json；文件不存在或 digest
不匹配（taskRecord 在 plan 后被改过）时自动降级为全量读取。

用法：
    python3 pack_context.py --planning-dir <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


CONTEXT_PACK_SUBDIR = "context_pack"


def _sha256(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def pack_context(planning_dir: Path) -> dict[str, Any]:
    """为 planning_dir 下每个 task 生成 context_pack/<task_id>.json。

    返回 Envelope-compatible dict（ok / reason / data / details）。
    """
    taskrecord_path = planning_dir / "taskRecord.yaml"
    manifest_path = planning_dir / "manifest.md"

    if not taskrecord_path.is_file():
        return {
            "ok": False,
            "reason": "file_missing",
            "details": {"path": str(taskrecord_path)},
        }
    if not manifest_path.is_file():
        return {
            "ok": False,
            "reason": "file_missing",
            "details": {"path": str(manifest_path)},
        }

    taskrecord_text = taskrecord_path.read_text(encoding="utf-8")
    manifest_text = manifest_path.read_text(encoding="utf-8")

    try:
        taskrecord = yaml.safe_load(taskrecord_text)
    except yaml.YAMLError as exc:
        return {"ok": False, "reason": "schema_invalid", "details": {"error": str(exc)}}

    if not isinstance(taskrecord, dict) or "tasks" not in taskrecord:
        return {
            "ok": False,
            "reason": "schema_invalid",
            "details": {"error": "taskRecord.yaml 缺少 'tasks' 字段"},
        }

    tasks = taskrecord.get("tasks") or []
    if not isinstance(tasks, list):
        return {
            "ok": False,
            "reason": "schema_invalid",
            "details": {"error": "'tasks' 必须是列表"},
        }

    taskrecord_digest = _sha256(taskrecord_text)
    manifest_digest = _sha256(manifest_text)

    out_dir = planning_dir / CONTEXT_PACK_SUBDIR
    out_dir.mkdir(exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    packed = 0

    for task in tasks:
        if not isinstance(task, dict) or "task_id" not in task:
            continue
        task_id = str(task["task_id"])
        depends_on: list[str] = [str(d) for d in (task.get("depends_on") or [])]
        upstream_artifact_paths = [
            f".drive/<plan_dir>/artifacts/{dep}/" for dep in depends_on
        ]
        pack = {
            "task_id": task_id,
            "generated_at": generated_at,
            "taskrecord_digest": taskrecord_digest,
            "manifest_digest": manifest_digest,
            "task": task,
            "depends_on": depends_on,
            "upstream_artifact_paths": upstream_artifact_paths,
        }
        out_path = out_dir / f"{task_id}.json"
        out_path.write_text(
            json.dumps(pack, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        packed += 1

    return {
        "ok": True,
        "data": {"tasks_packed": packed, "context_pack_dir": str(out_dir)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预打包每个 task 的上下文快照")
    parser.add_argument("--planning-dir", required=True, help=".drive/<plan_dir>/ 目录路径")
    args = parser.parse_args(argv)

    result = pack_context(Path(args.planning_dir))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
