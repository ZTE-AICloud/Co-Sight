"""把一个 wave 的 worker summary 聚合成 state 字段（带 wave barrier 强约束）。

executor 收到主对话传来的 summary 列表后调本脚本。它做三件事：

1. 把 N 条 summary 折成 task_results 与 wave_summaries 两个嵌套 dict
2. 与 waves.yaml 当前 wave 的 expected task 列表比对：缺 / 多 / 重复 即 fail
3. 调 state_cli 写进 executeState.json（先读旧值再合并，避免覆盖前面 wave）

barrier 检查的意义：wave N-1 没跑全、或主对话抢跑推到 wave N+1、或者 worker
被双跑，都会在这一步暴露并 reject。不写 state 不算 barrier 完成，主对话据此
可以决定补派或回退。

不读 taskRecord.yaml、不碰 current_wave（主 agent 的活）、不派 subagent。

用法:
    python3 aggregate.py --planning-dir .drive/<plan_dir> --wave 3 --summaries-file /tmp/s.json
    echo '<json>' | python3 aggregate.py --planning-dir .drive/<plan_dir> --wave 3 --stdin

summaries 是 JSON 数组，每项是 executor 返回的 summary。

缺失 waves.yaml 或该 wave 不在 waves.yaml 里时，barrier 不强制（降级通过），
响应里 `barrier_enforced: false` 标记该路径。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REASON_INVALID_ARG = "invalid_arg"
REASON_EMPTY_SUMMARIES = "empty_summaries"
REASON_WRITEBACK_FAILED = "writeback_failed"
REASON_WAVE_MISMATCH = "wave_mismatch"
REASON_WAVES_FILE_MISSING = "waves_file_missing"
REASON_EMPTY_FSDIFF = "empty_fsdiff"
REASON_SUBPROCESS_TIMEOUT = "subprocess_timeout"

STATUS_DONE = frozenset({"completed", "skipped"})
STATUS_FAIL = frozenset({"partial", "failed"})


@dataclass(frozen=True)
class Envelope:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok_envelope(cls, **data: Any) -> "Envelope":
        return cls(ok=True, data=data)

    @classmethod
    def fail(cls, reason: str, **details: Any) -> "Envelope":
        return cls(ok=False, reason=reason, details=details)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _state_cli_path() -> Path:
    """state_cli.py 的位置。按插件根推导，不硬编码绝对路径。"""
    plugin_root = Path(__file__).resolve().parent.parent.parent.parent
    return plugin_root / "skills" / "state-machine" / "scripts" / "state_cli.py"


def condense(summary: dict[str, Any]) -> dict[str, Any] | None:
    """把一条 worker summary 折成 task_results 的一个条目。

    缺 task_id 的条目无法归属，返回 None 由调用方计入无效。

    files_changed 字段：worker 声明自己写过的文件路径列表，路径必须是仓库内
    相对路径（不是绝对路径）。wave barrier 之外的 fs diff 在主对话层做，
    本脚本只忠实落账 —— 审计要从这里看到 worker 究竟改了什么。
    """
    task_id = str(summary.get("task_id") or "").strip()
    if not task_id:
        return None
    files = summary.get("files_changed") or []
    files_list = files if isinstance(files, list) else []
    attempts_raw = summary.get("attempts")
    try:
        attempts = max(1, int(attempts_raw)) if attempts_raw is not None else 1
    except (TypeError, ValueError):
        attempts = 1
    return {
        "task_id": task_id,
        "entry": {
            "status": str(summary.get("status") or "unknown"),
            "duration_sec": summary.get("duration_sec") or 0,
            "files_count": len(files_list),
            "files_changed": [str(f) for f in files_list if isinstance(f, (str, Path))],
            "attempts": attempts,
        },
    }


def aggregate(wave_n: int, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """折出 task_results 与 wave_summaries 两个嵌套 dict。"""
    task_results: dict[str, Any] = {}
    invalid = 0
    empty_fsdiff: list[str] = []
    for item in summaries:
        condensed = condense(item) if isinstance(item, dict) else None
        if condensed is None:
            invalid += 1
            continue
        # fs diff 强约束：状态为 done 的 summary 必须至少声明一个 files_changed，
        # 否则视为"报完成但 fs 无变化"——这种 fail 模式历史上击穿过 drive 的
        # "main agent 不做业务执行"承诺（详见 drive-issues.md P0 #1）。
        # declared 是 worker 主动声明的，不是 fs 扫描，所以这里不读盘，只验
        # "声明 vs status"的一致性。fs 真实存在与否在主对话层做（更靠近 LLM，
        # 可以修）。
        if (
            condensed["entry"]["status"] in STATUS_DONE
            and condensed["entry"]["files_count"] == 0
        ):
            empty_fsdiff.append(condensed["task_id"])
            continue
        task_results[condensed["task_id"]] = condensed["entry"]

    # 至少有一个 empty_fsdiff → barrier 不通过：让 main agent 重新派工而不是
    # 把"报完成但 fs 空"的状态写进 state。
    barrier_blocked = len(empty_fsdiff) > 0

    statuses = [entry["status"] for entry in task_results.values()]
    success = sum(1 for s in statuses if s in STATUS_DONE)
    failed = sum(1 for s in statuses if s in STATUS_FAIL)
    total_duration = sum(
        entry["duration_sec"] for entry in task_results.values()
        if isinstance(entry["duration_sec"], (int, float))
    )

    wave_summary = {
        "task_count": len(task_results),
        "success_count": success,
        # 无效条目（缺 task_id）也算失败——它们没法证明自己完成了
        "fail_count": failed + invalid + len(empty_fsdiff),
        "total_duration_sec": total_duration,
    }
    return {
        "task_results": task_results,
        "wave_summaries": {str(wave_n): wave_summary},
        "invalid_count": invalid,
        "empty_fsdiff": empty_fsdiff,
        "barrier_blocked": barrier_blocked,
    }


def read_existing(cli: Path, planning_dir: Path) -> dict[str, Any]:
    """读回已有的 task_results / wave_summaries。

    `--set-json` 是整体替换语义，所以必须先读、合并、再写，否则后一个 wave
    会抹掉前面所有 wave 的账。
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(cli), "read", "--planning-dir", str(planning_dir)],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return {}
    # state_cli read 的形状是 {data: {path, state}}，state 在里面一层
    return (payload.get("data") or {}).get("state") or {}


def writeback(planning_dir: Path, aggregated: dict[str, Any]) -> Envelope:
    """委托 state_cli 把两个 dict 写进 executeState.json。

    本脚本不自己碰 state 文件——写入只能走 state-machine skill 的单一通道。
    """
    cli = _state_cli_path()
    if not cli.is_file():
        return Envelope.fail(
            REASON_WRITEBACK_FAILED, error=f"state_cli.py 不存在: {cli}"
        )

    existing = read_existing(cli, planning_dir)
    merged_tasks = {
        **(existing.get("task_results") or {}),
        **aggregated["task_results"],
    }
    merged_waves = {
        **(existing.get("wave_summaries") or {}),
        **aggregated["wave_summaries"],
    }

    argv = [
        sys.executable, str(cli), "update",
        "--planning-dir", str(planning_dir),
        "--set-json", f"task_results={json.dumps(merged_tasks, ensure_ascii=False)}",
        "--set-json", f"wave_summaries={json.dumps(merged_waves, ensure_ascii=False)}",
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return Envelope.fail(
            REASON_SUBPROCESS_TIMEOUT,
            cli=str(cli),
            timeout=30,
            error="state_cli update 超时",
        )
    if proc.returncode != 0:
        detail: dict[str, Any] = {"exit_code": proc.returncode}
        try:
            detail["state_cli"] = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            detail["stdout"] = proc.stdout[:400]
            detail["stderr"] = proc.stderr[:400]
        return Envelope.fail(REASON_WRITEBACK_FAILED, **detail)

    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    return Envelope.ok_envelope(revision=payload.get("data", {}).get("revision"))


def load_summaries(args: argparse.Namespace) -> list[dict[str, Any]] | Envelope:
    """从 stdin 或文件读 summary 数组。"""
    if args.stdin:
        raw = sys.stdin.read()
    elif args.summaries_file:
        path = Path(args.summaries_file)
        if not path.is_file():
            return Envelope.fail(
                REASON_INVALID_ARG, error=f"summaries 文件不存在: {path}"
            )
        raw = path.read_text(encoding="utf-8")
    elif args.summaries:
        raw = args.summaries
    else:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error="需要 --stdin / --summaries-file / --summaries 之一",
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return Envelope.fail(REASON_INVALID_ARG, error=f"summaries 非合法 JSON: {exc}")

    if not isinstance(parsed, list):
        return Envelope.fail(
            REASON_INVALID_ARG, error="summaries 必须是 JSON 数组"
        )
    return parsed


def expected_task_ids(planning_dir: Path, wave_n: int) -> list[str] | None:
    """读 waves.yaml 第 wave_n 波的 task 列表。读不到返回 None。

    None 时调用方要决定是 fail-closed（强制必须有 waves.yaml）还是 degrade-allow。
    barrier 保护下应该 fail-closed：没计划就没有"匹配"可言。
    """
    import yaml
    path = planning_dir / "waves.yaml"
    if not path.is_file():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    for w in doc.get("waves") or []:
        if isinstance(w, dict) and int(w.get("wave", -1)) == wave_n:
            tasks = w.get("tasks") or []
            return [str(t["task_id"]) for t in tasks if isinstance(t, dict) and "task_id" in t]
    return None  # waves 里没有这个 wave 序号 —— 视为不可比较


def check_wave_completeness(expected: list[str] | None, summaries: list[dict]) -> dict:
    """把 expected set 与 summaries 的 task_id 对齐，给出 missing/extras/duplicates。

    expected=None 时不比对（degrade-allow），返回 {'enforced': False}。
    """
    if expected is None:
        return {"enforced": False}

    expected_set = set(expected)
    seen: list[str] = []
    duplicates: list[str] = []
    seen_set: set[str] = set()
    for s in summaries:
        if not isinstance(s, dict):
            continue
        tid = str(s.get("task_id") or "").strip()
        if not tid:
            continue
        seen.append(tid)
        if tid in seen_set:
            duplicates.append(tid)
        seen_set.add(tid)

    seen_set = set(seen)
    missing = sorted(expected_set - seen_set)
    extras = sorted(seen_set - expected_set)
    return {
        "enforced": True,
        "expected_count": len(expected),
        "received_count": len(seen_set),
        "missing": missing,
        "extras": extras,
        "duplicates": sorted(set(duplicates)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="聚合一个 wave 的 worker summary")
    parser.add_argument("--planning-dir", required=True)
    parser.add_argument("--wave", type=int, required=True, help="wave 序号")
    parser.add_argument("--summaries", default=None, help="内联 JSON 数组")
    parser.add_argument("--summaries-file", default=None, help="JSON 数组文件路径")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读 JSON 数组")
    args = parser.parse_args(argv)

    planning_dir = Path(args.planning_dir)
    if not planning_dir.is_dir():
        env = Envelope.fail(
            REASON_INVALID_ARG, planning_dir=str(planning_dir), error="目录不存在"
        )
        print(env.to_json())
        return env.exit_code()

    loaded = load_summaries(args)
    if isinstance(loaded, Envelope):
        print(loaded.to_json())
        return loaded.exit_code()

    if not loaded:
        # 空列表不写 state —— 没有依据的写入比不写更糟
        env = Envelope.fail(
            REASON_EMPTY_SUMMARIES,
            wave=args.wave,
            error="summary 列表为空，不写 state",
        )
        print(env.to_json())
        return env.exit_code()

    # Wave barrier 强约束：传进来的 summaries 必须与 waves.yaml 当前波一致，
    # 否则不写 state。缺任务意味着前置 barrier 没等全，多余意味着 runner 双跑。
    expected = expected_task_ids(planning_dir, args.wave)
    comparison = check_wave_completeness(expected, loaded)

    if comparison.get("enforced") and (
        comparison.get("missing") or comparison.get("extras") or comparison.get("duplicates")
    ):
        env = Envelope.fail(
            REASON_WAVE_MISMATCH,
            wave=args.wave,
            error=(
                f"wave {args.wave} barrier 没对齐: "
                f"缺={comparison['missing']} 多={comparison['extras']} 重复={comparison['duplicates']}"
            ),
            **comparison,
        )
        print(env.to_json())
        return env.exit_code()

    aggregated = aggregate(args.wave, loaded)

    # fs diff barrier：报完成但 fs 无变化的任务不写 state，让主对话层重派。
    # 这是 drive-issues.md P0 #1 的修复点：之前"main agent 兜底补完"是 hit
    # 架构承诺的做法，正确的拦法是 barrier 在这里就把空 output 拒掉。
    if aggregated.get("barrier_blocked"):
        env = Envelope.fail(
            REASON_EMPTY_FSDIFF,
            wave=args.wave,
            writeback_ok=False,
            error=(
                f"wave {args.wave} 里有 {len(aggregated['empty_fsdiff'])} 个 task 报完成但 "
                f"files_changed 为空：{aggregated['empty_fsdiff']}。"
                f"不写 state，请重派这些 task 或确认它们确实不应改文件。"
            ),
            empty_fsdiff=aggregated["empty_fsdiff"],
        )
        print(env.to_json())
        return env.exit_code()

    written = writeback(planning_dir, aggregated)
    if not written.ok:
        env = Envelope.fail(
            written.reason or REASON_WRITEBACK_FAILED,
            wave=args.wave,
            writeback_ok=False,
            **written.details,
        )
        print(env.to_json())
        return env.exit_code()

    wave_summary = aggregated["wave_summaries"][str(args.wave)]
    env = Envelope.ok_envelope(
        wave_n=args.wave,
        writeback_ok=True,
        revision=written.data.get("revision"),
        barrier_enforced=comparison.get("enforced", False),
        **comparison,
        **wave_summary,
    )
    print(env.to_json())
    return env.exit_code()


if __name__ == "__main__":
    sys.exit(main())
