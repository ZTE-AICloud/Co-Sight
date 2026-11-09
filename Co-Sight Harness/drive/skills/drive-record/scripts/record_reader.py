"""读取 `.drive/<plan_dir>/` 下的 9 个 runtime record 文件。

按写入方分两组：

- Runtime SDK 通道（6 个，drive runtime 保证一定有，除非 runtime 中断）：
  - run-meta.json / intent.md（init_planning.py 写）
  - executeState.json（state_write.py 写）
  - run-log.jsonl（audit_append.py hook 写）
  - waves.yaml / topo-state.json（topo_sort.py 写）

- LLM 契约（3 个，靠 agent 自觉写）：
  - manifest.md（analyzer agent）
  - taskRecord.yaml（planner agent）
  - evaluation/verification-report.md（evaluator agent）

外加每 task 一份的 artifacts/<task_id>/SUMMARY.md（executor agent，N 份按 task 数）。

返回 dataclass 集合（含容错：缺文件 → None / 缺字段 → default）。调用方拿到
统一的 Record 对象，按需取字段即可。不抛异常。

设计原则：
- 不修改任何文件（drive-record 是只读 skill）
- 不依赖 drive runtime 任何 CLI（只读文件）
- 缺文件/坏 JSON 不报错，返回 None / 部分字段
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# 6 个 Runtime SDK 通道产物（drive-2.3 schema）
RUN_META = "run-meta.json"
INTENT = "intent.md"
EXECUTE_STATE = "executeState.json"
RUN_LOG = "run-log.jsonl"
WAVES = "waves.yaml"
TOPO_STATE = "topo-state.json"

# 3 个 LLM 契约产物
MANIFEST = "manifest.md"
TASK_RECORD = "taskRecord.yaml"
EVALUATION_REPORT = "evaluation/verification-report.md"

# artifacts/<task_id>/SUMMARY.md 是目录，不是单文件，单独处理
ARTIFACTS = "artifacts"

CORE_FILES: tuple[str, ...] = (
    RUN_META,
    INTENT,
    MANIFEST,
    TASK_RECORD,
    WAVES,
    TOPO_STATE,
    EXECUTE_STATE,
    RUN_LOG,
    EVALUATION_REPORT,
)

# 按写入方分组的子集，方便 gap detector 与 build_report 区分缺失严重度
RUNTIME_FILES: tuple[str, ...] = (
    RUN_META,
    INTENT,
    EXECUTE_STATE,
    RUN_LOG,
    WAVES,
    TOPO_STATE,
)

LLM_CONTRACT_FILES: tuple[str, ...] = (
    MANIFEST,
    TASK_RECORD,
    EVALUATION_REPORT,
)

# YAML 解析：优先用 PyYAML，缺失则用最简手写解析（只支持嵌套 dict + 列表）
try:
    import yaml as _yaml  # type: ignore[import-untyped]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


@dataclass(frozen=True)
class RunMeta:
    plan_name: str = ""
    plan_dir: str = ""
    git_head: str = ""
    git_branch: str = ""
    workflow_hash: str = ""
    started_at: str = ""
    worktree: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecuteState:
    schema_version: str = ""
    revision: int = 0
    active_stage: str = ""
    status: str = ""
    current_wave: int = 0
    waves_total: int = 0
    next_action: str | None = None
    confirmed_stages: tuple[str, ...] = ()
    pending_confirmation: str | None = None
    verdict: str = ""
    created_at: str = ""
    updated_at: str = ""
    task_results: dict[str, Any] = field(default_factory=dict)
    wave_summaries: dict[str, Any] = field(default_factory=dict)
    active_agents: tuple[dict[str, Any], ...] = ()
    mode: str = "phase"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskRecord:
    plan_id: str = ""
    tasks: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Waves:
    plan_id: str = ""
    waves: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopoState:
    plan_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LogEvent:
    ts: str
    event: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Record:
    plan_dir: Path
    run_meta: RunMeta | None = None
    intent: str = ""
    manifest: str = ""
    task_record: TaskRecord | None = None
    waves: Waves | None = None
    topo_state: TopoState | None = None
    execute_state: ExecuteState | None = None
    log_events: tuple[LogEvent, ...] = ()
    evaluation_report: str = ""
    artifacts: dict[str, Path] = field(default_factory=dict)
    missing_files: tuple[str, ...] = ()


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _read_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if _HAS_YAML:
        try:
            data = _yaml.safe_load(text)
        except _yaml.YAMLError:
            return None
        return data if isinstance(data, dict) else None
    return _minimal_yaml_load(text)


def _minimal_yaml_load(text: str) -> dict[str, Any] | None:
    """极简 YAML loader：plan_id / waves 形状够用即可。

    支持：
    - top-level scalar: `key: value`
    - nested list of dicts under one key: `waves:\\n  - wave: 1\\n    tasks: [...]`
    """
    result: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[dict[str, Any]] | None = None
    current_item: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.lstrip()

        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            value = value.strip()
            if value == "":
                current_key = key.strip()
                current_list = []
                result[current_key] = current_list
                current_item = None
            else:
                current_key = key.strip()
                current_list = None
                current_item = None
                coerced = _coerce_scalar(value)
                result[current_key] = coerced
        elif indent > 0 and stripped.startswith("- "):
            if current_list is None:
                continue
            current_item = {}
            current_list.append(current_item)
            rest = stripped[2:]
            if ":" in rest:
                k, _, v = rest.partition(":")
                current_item[k.strip()] = _coerce_scalar(v.strip())
        elif indent > 0 and current_item is not None and ":" in stripped:
            k, _, v = stripped.partition(":")
            current_item[k.strip()] = _coerce_scalar(v.strip())

    return result


def _coerce_scalar(value: str) -> Any:
    if value == "":
        return ""
    if value in ("null", "~"):
        return None
    if value in ("true", "True", "yes"):
        return True
    if value in ("false", "False", "no"):
        return False
    if (value.startswith("[") and value.endswith("]")) or (
        value.startswith("{") and value.endswith("}")
    ):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    try:
        return int(value)
    except ValueError:
        pass
    return value


def parse_run_meta(data: dict[str, Any] | None) -> RunMeta:
    if not data:
        return RunMeta()
    return RunMeta(
        plan_name=str(data.get("plan_name", "")),
        plan_dir=str(data.get("plan_dir", "")),
        git_head=str(data.get("git_head", "")),
        git_branch=str(data.get("git_branch", "")),
        workflow_hash=str(data.get("workflow_hash", "")),
        started_at=str(data.get("started_at", "")),
        worktree=str(data.get("worktree", "")),
        raw=data,
    )


def parse_execute_state(data: dict[str, Any] | None) -> ExecuteState | None:
    if not data:
        return None
    task_results_raw = data.get("task_results", {}) or {}
    wave_summaries_raw = data.get("wave_summaries", {}) or {}
    confirmed = tuple(data.get("confirmed_stages", []) or ())
    return ExecuteState(
        schema_version=str(data.get("schema_version", "")),
        revision=int(data.get("revision", 0) or 0),
        active_stage=str(data.get("active_stage", "")),
        status=str(data.get("status", "")),
        current_wave=int(data.get("current_wave", 0) or 0),
        waves_total=int(data.get("waves_total", 0) or 0),
        next_action=data.get("next_action"),
        confirmed_stages=confirmed,
        pending_confirmation=data.get("pending_confirmation"),
        verdict=str(data.get("verdict", "")),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
        task_results=dict(task_results_raw),
        wave_summaries=dict(wave_summaries_raw),
        active_agents=tuple(data.get("active_agents") or ()),
        mode=str(data.get("mode", "phase")),
        raw=data,
    )


def parse_task_record(data: dict[str, Any] | None) -> TaskRecord | None:
    if not data:
        return None
    tasks_raw = data.get("tasks", []) or []
    return TaskRecord(
        plan_id=str(data.get("plan_id", "")),
        tasks=tuple(tasks_raw if isinstance(tasks_raw, list) else ()),
        raw=data,
    )


def parse_waves(data: dict[str, Any] | None) -> Waves | None:
    if not data:
        return None
    waves_raw = data.get("waves", []) or []
    return Waves(
        plan_id=str(data.get("plan_id", "")),
        waves=tuple(waves_raw if isinstance(waves_raw, list) else ()),
        raw=data,
    )


def parse_topo_state(data: dict[str, Any] | None) -> TopoState | None:
    if not data:
        return None
    return TopoState(
        plan_id=str(data.get("plan_id", "")),
        raw=data,
    )


def parse_log_events(text: str) -> tuple[LogEvent, ...]:
    events: list[LogEvent] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        ts = str(obj.get("ts", ""))
        event = str(obj.get("event", ""))
        if not event:
            continue
        details = {k: v for k, v in obj.items() if k not in ("ts", "event")}
        events.append(LogEvent(ts=ts, event=event, details=details))
    return tuple(events)


def read_artifacts(plan_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    artifacts_dir = plan_dir / ARTIFACTS
    if not artifacts_dir.is_dir():
        return out
    for child in artifacts_dir.iterdir():
        if not child.is_dir():
            continue
        summary = child / "SUMMARY.md"
        if summary.is_file():
            out[child.name] = summary
    return out


def read_record(plan_dir: Path | str) -> Record:
    """读整个 plan_dir 的所有 record 文件。

    缺文件 / 损坏 JSON / 缺字段 全部容错，调用方拿到部分填充的 Record。
    """
    p = Path(plan_dir)
    if not p.is_dir():
        raise ValueError(f"plan_dir 不存在或不是目录: {p}")

    missing: list[str] = []
    for name in CORE_FILES:
        if not (p / name).exists():
            missing.append(name)

    run_meta = parse_run_meta(_read_json(p / RUN_META))
    intent = _read_text(p / INTENT)
    manifest = _read_text(p / MANIFEST)
    task_record = parse_task_record(_read_yaml(p / TASK_RECORD))
    waves = parse_waves(_read_yaml(p / WAVES))
    topo_state = parse_topo_state(_read_json(p / TOPO_STATE))
    execute_state = parse_execute_state(_read_json(p / EXECUTE_STATE))
    log_events = parse_log_events(_read_text(p / RUN_LOG))
    evaluation_report = _read_text(p / EVALUATION_REPORT)
    artifacts = read_artifacts(p)

    return Record(
        plan_dir=p,
        run_meta=run_meta,
        intent=intent,
        manifest=manifest,
        task_record=task_record,
        waves=waves,
        topo_state=topo_state,
        execute_state=execute_state,
        log_events=log_events,
        evaluation_report=evaluation_report,
        artifacts=artifacts,
        missing_files=tuple(missing),
    )


__all__ = [
    "Record",
    "RunMeta",
    "ExecuteState",
    "TaskRecord",
    "Waves",
    "TopoState",
    "LogEvent",
    "CORE_FILES",
    "RUNTIME_FILES",
    "LLM_CONTRACT_FILES",
    "RUN_META",
    "EXECUTE_STATE",
    "TASK_RECORD",
    "WAVES",
    "TOPO_STATE",
    "RUN_LOG",
    "INTENT",
    "MANIFEST",
    "EVALUATION_REPORT",
    "ARTIFACTS",
    "parse_run_meta",
    "parse_execute_state",
    "parse_task_record",
    "parse_waves",
    "parse_topo_state",
    "parse_log_events",
    "read_record",
]