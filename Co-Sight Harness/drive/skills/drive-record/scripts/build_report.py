"""§0–§5 + §B REPORT 拼装。

主入口：`build_report(plan_dir, cwd=None, session_override=None, worktree=None)`
返回 dict：`{ "plan_dir": Path, "report_md": str, "summary": dict, "session_path": Path|None }`

调用者（cli.py / 测试）负责落盘到 plan_dir。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gaps_detector import Gap, SEVERITY_CRITICAL, SEVERITY_HIGH, detect_gaps, summarize
from record_reader import (
    LLM_CONTRACT_FILES,
    RUNTIME_FILES,
    ExecuteState,
    Record,
    read_record,
)
from session_locator import locate_session
from timeline_builder import build_timeline


# ---------- 内部 helper ----------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stage_name(es: ExecuteState) -> str:
    return es.active_stage or es.status or "unknown"


def _task_status_counts(es: ExecuteState) -> dict[str, int]:
    counts = {"ok": 0, "fail": 0, "skipped": 0, "other": 0}
    for info in es.task_results.values():
        s = str(info.get("status") or "other")
        if s not in counts:
            counts["other"] += 1
        else:
            counts[s] += 1
    return counts


# ---------- section renderers ----------


def _render_meta(record: Record) -> str:
    lines = ["## §0 元信息", ""]
    rm = record.run_meta
    if rm is not None:
        lines.append(f"- plan_name: `{rm.plan_name}`")
        lines.append(f"- plan_dir: `{rm.plan_dir}`")
        lines.append(f"- started_at: {rm.started_at or '(未知)'}")
        lines.append(f"- git_head: `{rm.git_head or '(未知)'}`")
        lines.append(f"- git_branch: `{rm.git_branch or '(未知)'}`")
        if rm.workflow_hash:
            lines.append(f"- workflow_hash: `{rm.workflow_hash}`")
        if rm.worktree:
            lines.append(f"- worktree: `{rm.worktree}`")
    else:
        lines.append("- run-meta.json: 缺失")
    missing_runtime = [n for n in record.missing_files if n in RUNTIME_FILES]
    missing_llm = [n for n in record.missing_files if n in LLM_CONTRACT_FILES]
    lines.append(f"- 核心文件缺失: Runtime {len(missing_runtime)}/{len(RUNTIME_FILES)} "
                 f"+ LLM 契约 {len(missing_llm)}/{len(LLM_CONTRACT_FILES)}")
    if record.missing_files:
        for name in record.missing_files:
            tag = "Runtime" if name in RUNTIME_FILES else (
                "LLM" if name in LLM_CONTRACT_FILES else "?"
            )
            lines.append(f"  - `{name}` ({tag})")
    lines.append("")
    return "\n".join(lines)


def _render_completeness(record: Record, gaps: tuple[Gap, ...],
                        summary: dict[str, int]) -> str:
    lines = ["## §0.1 完整度自检", ""]
    runtime_missing = [n for n in record.missing_files if n in RUNTIME_FILES]
    llm_missing = [n for n in record.missing_files if n in LLM_CONTRACT_FILES]
    runtime_present = len(RUNTIME_FILES) - len(runtime_missing)
    llm_present = len(LLM_CONTRACT_FILES) - len(llm_missing)
    total_core = len(RUNTIME_FILES) + len(LLM_CONTRACT_FILES)
    total_present = runtime_present + llm_present
    completeness = round(total_present / total_core, 4) if total_core else 0
    lines.append(
        f"- Runtime SDK 通道: {runtime_present}/{len(RUNTIME_FILES)} = "
        f"{runtime_present/len(RUNTIME_FILES):.0%}（缺失 {len(runtime_missing)} 个）"
    )
    lines.append(
        f"- LLM 契约产物: {llm_present}/{len(LLM_CONTRACT_FILES)} = "
        f"{llm_present/len(LLM_CONTRACT_FILES):.0%}（缺失 {len(llm_missing)} 个）"
    )
    lines.append(f"- 总体完整度: {total_present}/{total_core} = {completeness:.1%}")
    if record.execute_state and record.execute_state.task_results:
        counts = _task_status_counts(record.execute_state)
        total_tasks = sum(counts.values())
        artifact_total = len(record.artifacts)
        lines.append(
            f"- task_results: total={total_tasks} ok={counts['ok']} "
            f"fail={counts['fail']} skipped={counts['skipped']} other={counts['other']}"
        )
        lines.append(f"- artifacts/<id>/SUMMARY.md: {artifact_total} 个")
    if record.execute_state and record.execute_state.mode:
        lines.append(f"- 模式: `{record.execute_state.mode}`（DAG 模式独立处理 waves）")
    lines.append(f"- gap: total={summary['total']} "
                 f"critical={summary['critical']} high={summary['high']} "
                 f"medium={summary['medium']} low={summary['low']}")
    if gaps and gaps[0].severity in (SEVERITY_CRITICAL, SEVERITY_HIGH):
        lines.append("")
        lines.append("⚠️ 存在高严重度 gap，建议先修（详见 §B）")
    lines.append("")
    return "\n".join(lines)


def _render_timeline(timeline_lines: list[str]) -> str:
    lines = ["## §1 时间线", ""]
    if not timeline_lines:
        lines.append("(无事件)")
        return "\n".join(lines) + "\n"
    lines.append("```")
    lines.extend(timeline_lines)
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _render_stage_summaries(record: Record) -> str:
    lines = ["## §2 阶段产物摘要", ""]
    es = record.execute_state
    if es is not None and es.confirmed_stages:
        lines.append(f"- 已确认阶段: {' → '.join(es.confirmed_stages)}")
    if es is not None and es.wave_summaries:
        lines.append(f"- wave_summaries: {len(es.wave_summaries)} 项")
        for idx, info in es.wave_summaries.items():
            status = info.get("status") if isinstance(info, dict) else "?"
            lines.append(f"  - wave {idx}: status={status}")
    intent_summary = (record.intent or "").strip().splitlines()
    if intent_summary:
        lines.append("- intent.md 首行: " + intent_summary[0][:120])
    manifest_lines = (record.manifest or "").strip().splitlines()
    if manifest_lines:
        lines.append("- manifest.md 首行: " + manifest_lines[0][:120])
    task_count = len(record.task_record.tasks) if record.task_record else 0
    lines.append(f"- taskRecord.yaml: {task_count} 个 task")
    wave_count = len(record.waves.waves) if record.waves else 0
    lines.append(f"- waves.yaml: {wave_count} 个 wave")
    lines.append("")
    return "\n".join(lines)


def _render_code_changes(record: Record, worktree: Path | None) -> str:
    lines = ["## §3 代码改动", ""]
    es = record.execute_state
    if es is None or not es.task_results:
        lines.append("(无 task_results)")
        return "\n".join(lines) + "\n"
    has_changes = any(info.get("files_changed") for info in es.task_results.values())
    if not has_changes:
        lines.append("(task_results 中无 files_changed)")
        return "\n".join(lines) + "\n"
    for tid, info in es.task_results.items():
        files = info.get("files_changed") or []
        st = str(info.get("status") or "unknown")
        if not files:
            continue
        files_str = ", ".join(f"`{f}`" for f in files)
        lines.append(f"- `{tid}` (status={st}): {len(files)} 个文件 — {files_str}")
    lines.append("")
    return "\n".join(lines)


def _render_current_state(record: Record) -> str:
    lines = ["## §4 当前状态", ""]
    es = record.execute_state
    if es is None:
        lines.append("- executeState.json: 缺失")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"- active_stage: **{_stage_name(es)}**")
    lines.append(f"- status: `{es.status}`")
    if es.current_wave is not None:
        lines.append(f"- current_wave: {es.current_wave}/{es.waves_total}")
    lines.append(f"- revision: {es.revision}")
    if es.verdict:
        lines.append(f"- verdict: `{es.verdict}`")
    if es.pending_confirmation:
        lines.append(f"- pending_confirmation: `{es.pending_confirmation}` ⚠️")
    if es.next_action:
        lines.append(f"- next_action: {es.next_action[:120]}")
    if es.active_agents:
        running = [a for a in es.active_agents
                   if a.get("status") not in ("completed", "failed", "skipped")]
        lines.append(f"- active_agents: {len(running)} running, "
                     f"{len(es.active_agents) - len(running)} done")
    lines.append("")
    return "\n".join(lines)


def _render_session(record: Record, session_path: Path | None) -> str:
    lines = ["## §5 session 路径", ""]
    if session_path is None:
        lines.append("(未关联 session — silently skipped)")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"- path: `{session_path}`")
    try:
        size = session_path.stat().st_size
        lines.append(f"- size: {size} bytes")
    except OSError:
        pass
    lines.append("")
    return "\n".join(lines)


def _render_gaps(gaps: tuple[Gap, ...], summary: dict[str, int]) -> str:
    lines = ["## §B 完整性 + 一致性 gap", ""]
    lines.append(f"总计 **{summary['total']}** 项："
                 f"CRITICAL={summary['critical']} HIGH={summary['high']} "
                 f"MEDIUM={summary['medium']} LOW={summary['low']}")
    lines.append("")
    lines.append("> 以下 gap 不一定代表 bug；它们是 record 完整度/一致性的信号。"
                 "drive 开发者按 related_runtime 字段定位修复点。")
    lines.append("")
    if not gaps:
        lines.append("✅ 未检测到 gap")
        lines.append("")
        return "\n".join(lines)
    for g in gaps:
        lines.append(f"### {g.type} ({g.severity})")
        lines.append(f"- location: `{g.location}`")
        lines.append(f"- description: {g.description}")
        lines.append(f"- fix_suggestion: {g.fix_suggestion}")
        if g.related_runtime:
            lines.append(f"- related_runtime: `{g.related_runtime}`")
        lines.append("")
    return "\n".join(lines)


# ---------- 主入口 ----------


def assemble_report(sections: dict[str, str]) -> str:
    """按 §0/§0.1/§1/§2/§3/§4/§5/§B 顺序合成完整 REPORT.md。"""
    order = ["§0", "§0.1", "§1", "§2", "§3", "§4", "§5", "§B"]
    header = ["# /drive-record REPORT", "", f"_生成于: {_now_iso()}_", ""]
    body = [sections[k] for k in order if k in sections]
    return "\n".join(header + body)


def build_report(
    plan_dir: Path,
    cwd: str | None = None,
    session_override: str | None = None,
    worktree: Path | None = None,
) -> dict[str, Any]:
    """主入口：从 plan_dir 读取 record → 检测 gap → 拼 REPORT.md。

    返回 envelope.data 用字段：
    - plan_name: str（run-meta.plan_name；缺时 fallback plan_dir 目录名）
    - mode: "phase" | "dag"（executeState.mode）
    - completeness: dict{runtime_present, runtime_total, llm_present, llm_total}
    - report_md: str
    - session_path: Path | None
    - summary: {total, critical, high, medium, low}
    """
    record = read_record(plan_dir)
    gaps = detect_gaps(record)
    summary = summarize(gaps)
    timeline_lines = build_timeline(record, worktree=worktree)
    session_path = locate_session(record, cwd=cwd, override=session_override)

    sections: dict[str, str] = {
        "§0": _render_meta(record),
        "§0.1": _render_completeness(record, gaps, summary),
        "§1": _render_timeline(timeline_lines),
        "§2": _render_stage_summaries(record),
        "§3": _render_code_changes(record, worktree),
        "§4": _render_current_state(record),
        "§5": _render_session(record, session_path),
        "§B": _render_gaps(gaps, summary),
    }

    # 完整度：Runtime SDK / LLM 契约分别计数
    runtime_missing = [n for n in record.missing_files if n in RUNTIME_FILES]
    llm_missing = [n for n in record.missing_files if n in LLM_CONTRACT_FILES]
    completeness = {
        "runtime_present": len(RUNTIME_FILES) - len(runtime_missing),
        "runtime_total": len(RUNTIME_FILES),
        "llm_present": len(LLM_CONTRACT_FILES) - len(llm_missing),
        "llm_total": len(LLM_CONTRACT_FILES),
    }

    plan_name = (
        record.run_meta.plan_name
        if record.run_meta and record.run_meta.plan_name
        else plan_dir.name
    )
    mode = (
        record.execute_state.mode
        if record.execute_state and record.execute_state.mode
        else "phase"
    )

    return {
        "plan_name": plan_name,
        "mode": mode,
        "completeness": completeness,
        "report_md": assemble_report(sections),
        "summary": summary,
        "session_path": session_path,
    }


def write_report(
    plan_dir: Path,
    cwd: str | None = None,
    session_override: str | None = None,
    worktree: Path | None = None,
) -> dict[str, Any]:
    """build_report + 落盘 REPORT.md 到 plan_dir。"""
    result = build_report(
        plan_dir, cwd=cwd, session_override=session_override, worktree=worktree
    )
    (plan_dir / "REPORT.md").write_text(result["report_md"], encoding="utf-8")
    return result


__all__ = [
    "build_report",
    "write_report",
    "assemble_report",
]