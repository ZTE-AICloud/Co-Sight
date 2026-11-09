#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state.py — agent-eval 编排层状态机。

职责边界（刻意收窄）：

- 只读写 `<run>/.state/state.json` 与 `<run>/.state/events.jsonl`。
- 只按「锚点文件是否存在 / 哈希是否一致」对账，不解析任何业务产物内容。
- 不调用任何上游脚本（generator / runner / evaluator / traceaudit）。

状态取值：pending / running / done / failed。迁移严格线性：

    pending|failed|running --begin--> running --complete--> done
                                            \\--fail-----> failed

产物是真相源：每次进入先 reconcile。running 但锚点已在 → 升级 done
（exit_code 记 null）；done 但锚点缺失或被改写 → 降级 pending，并级联降级
其后所有已完成的段——下游产物是基于旧输入算出来的，不能继续冒充当前结论。

退出码：0 成功；2 守卫拒绝（非法迁移 / 参数错配 / 前置缺失）；1 脚本自身错误。
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path


# ============================== 契约常量 ==============================

SCHEMA_VERSION = 1

STATE_DIRNAME = ".state"
STATE_FILENAME = "state.json"
EVENTS_FILENAME = "events.jsonl"

# 四段的推进顺序；顺序即依赖顺序，也是串接判据的顺序。
STAGES = ("generate", "run", "eval", "trace")

# 每段的对账锚点：一段只认一个语义锚点文件，用于发现「完成之后被删除或改写」。
# trace 段的路径由 traceaudit 自己拼，本工具原样接受，不改上游命名。
STAGE_ANCHORS = {
    "generate": ("generated_datasets", "seed.jsonl"),
    "run": ("run_datasets", "seed.jsonl"),
    "eval": ("eval_datasets", "report.md"),
    "trace": ("eval_trace_results", "batch-summary.json"),
}

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED)

# 续跑时只允许 --concurrency 变化，其余参数冻结。
FROZEN_PARAMS = ("agent", "count", "requirement")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_GUARD = 2

# 事件枚举：固定集合，便于用 jq 过滤与检测写入丢失。
EVENT_INIT = "run.init"
EVENT_BEGIN = "stage.begin"
EVENT_COMPLETE = "stage.complete"
EVENT_FAIL = "stage.fail"
EVENT_PROMOTE = "reconcile.promote"
EVENT_DOWNGRADE = "reconcile.downgrade"
EVENT_PARAMS_UPDATE = "resume.params_update"

NEXT_ACTION_REPORT = "report"
NEXT_ACTION_BLOCKED = "blocked"


# ============================== 错误 ==============================

class StateError(Exception):
    """脚本自身错误（IO / JSON 损坏）：退出码 1。"""


class GuardError(StateError):
    """状态机守卫拒绝（非法迁移 / 参数错配 / 前置缺失）：退出码 2。

    拒绝不是故障，编排层据此停住并转述，不重试。
    """


# ============================== 路径与 IO ==============================

def state_dir_of(run_dir) -> Path:
    return Path(run_dir) / STATE_DIRNAME


def state_path_of(run_dir) -> Path:
    return state_dir_of(run_dir) / STATE_FILENAME


def events_path_of(run_dir) -> Path:
    return state_dir_of(run_dir) / EVENTS_FILENAME


def anchor_path_of(run_dir, stage: str) -> Path:
    return Path(run_dir).joinpath(*STAGE_ANCHORS[stage])


def anchor_rel_of(stage: str) -> str:
    return "/".join(STAGE_ANCHORS[stage])


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def duration_between(started_at, ended_at):
    """两个 ISO 时间戳之间的秒数；任一缺失或格式异常返回 None。"""
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at)
    except ValueError:
        return None
    return round((end - start).total_seconds(), 1)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def write_text_atomic(path: Path, text: str) -> None:
    """原子写入：先写临时文件再替换，避免半截状态文件被读到。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json_atomic(path: Path, payload) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_state(run_dir):
    """读取状态文件；不存在或版本不符都按守卫拒绝（退出码 2）。"""
    path = state_path_of(run_dir)
    if not path.is_file():
        raise GuardError(
            f"本轮没有状态文件：{path}\n"
            f"  状态机只覆盖新轮次；历史目录不支持续跑。请换一条新命令重开一轮。"
        )
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"无法解析状态文件：{path}（{exc}）") from exc
    version = state.get("schema_version")
    if version != SCHEMA_VERSION:
        raise GuardError(
            f"状态文件版本不匹配：{path}（schema_version={version}，"
            f"本工具只接受 {SCHEMA_VERSION}）\n"
            f"  该轮由其他版本创建，请用对应版本续跑，或换一条新命令重开一轮。"
        )
    return state


def save_state(run_dir, state) -> None:
    state["updated_at"] = now_iso()
    write_json_atomic(state_path_of(run_dir), state)


# ============================== 事件流 ==============================

def last_seq_of(run_dir) -> int:
    """读事件流里最大的 seq；坏行跳过——seq 只用于防丢行，不参与状态判定。"""
    path = events_path_of(run_dir)
    if not path.is_file():
        return 0
    last = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("seq"), int):
            last = max(last, obj["seq"])
    return last


def append_event(run_dir, state, event, *, stage=None, from_status=None,
                 to_status=None, exit_code=None, duration_s=None,
                 warnings=None, message=""):
    """追加一条扁平事件；返回该事件。调用方随后负责 save_state。

    seq 取「状态文件记录值」与「事件流实际最大值」的较大者加一：即使上次
    事件写完、状态文件没写成，也不会重号。
    """
    path = events_path_of(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seq": max(state.get("seq", 0), last_seq_of(run_dir)) + 1,
        "ts": now_iso(),
        "event": event,
        "stage": stage,
        "from": from_status,
        "to": to_status,
        "exit_code": exit_code,
        "duration_s": duration_s,
        "warnings": list(warnings or []),
        "message": message,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    state["seq"] = payload["seq"]
    return payload


# ============================== 状态查询 ==============================

def next_action_of(state) -> str:
    """按状态给出下一步：第一个未完成的段；全部 done 则出报告。"""
    for stage in STAGES:
        if state["stages"][stage]["status"] != STATUS_DONE:
            return stage
    return NEXT_ACTION_REPORT


def status_payload(state, *, blocked_reason=None) -> dict:
    next_action = next_action_of(state)
    if blocked_reason is not None:
        next_action = NEXT_ACTION_BLOCKED
    return {
        "ok": True,
        "run_dir": state["run_dir"],
        "schema_version": state["schema_version"],
        "adopted": state["adopted"],
        "next_action": next_action,
        "blocked_reason": blocked_reason,
        "params": state["params"],
        "frozen": state["frozen"],
        "stages": state["stages"],
        "last_event_seq": state.get("seq", 0),
    }


def render_table(payload: dict) -> str:
    lines = [
        f"run_dir:     {payload['run_dir']}",
        f"next_action: {payload['next_action']}",
    ]
    if payload.get("blocked_reason"):
        lines.append(f"blocked:     {payload['blocked_reason']}")
    lines.append("")
    lines.append(f"{'stage':<10}{'status':<10}{'exit':<6}anchor")
    for stage in STAGES:
        meta = payload["stages"][stage]
        exit_code = "-" if meta.get("exit_code") is None else str(meta["exit_code"])
        lines.append(
            f"{stage:<10}{meta['status']:<10}{exit_code:<6}{anchor_rel_of(stage)}"
        )
    return "\n".join(lines)


def emit(payload: dict, fmt: str) -> None:
    if fmt == "table":
        print(render_table(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


# ============================== 守卫 ==============================

def require_stage(stage: str) -> None:
    if stage not in STAGES:
        raise GuardError(
            f"未知阶段：{stage}\n  可选：{' / '.join(STAGES)}"
        )


def guard_linear(state, stage: str) -> None:
    """严格线性：本段之前的所有段必须都是 done。"""
    index = STAGES.index(stage)
    for prev in STAGES[:index]:
        prev_status = state["stages"][prev]["status"]
        if prev_status != STATUS_DONE:
            raise GuardError(
                f"阶段 {stage} 的前序阶段 {prev} 尚未完成（{prev_status}）。\n"
                f"  状态机只允许按 {' → '.join(STAGES)} 的顺序推进。"
            )


def check_resume_params(state, args, run_dir) -> None:
    """续跑参数冻结校验：frozen 参数错配即拒绝；concurrency 允许变化并留痕。"""
    params = state["params"]
    frozen = state.get("frozen", list(FROZEN_PARAMS))
    conflicts = []
    for key in frozen:
        supplied = getattr(args, key, None)
        if supplied is None:
            continue
        if params.get(key) != supplied:
            conflicts.append((key, params.get(key), supplied))
    if conflicts:
        lines = [
            f"参数与首轮不一致：{key}（首轮 {old!r}，本次 {new!r}）"
            for key, old, new in conflicts
        ]
        lines.extend([
            "本轮产物属于上一版输入，混合续跑会得到失真的结果。",
            "  · 想评测新版：去掉 --resume，换一条新命令（会新建 run 目录）",
            "  · 只是想调并发：--concurrency 是唯一允许变化的参数",
        ])
        raise GuardError("\n".join(lines))

    concurrency = getattr(args, "concurrency", None)
    if concurrency is not None and concurrency != params.get("concurrency"):
        old = params.get("concurrency")
        params["concurrency"] = concurrency
        append_event(
            run_dir, state, EVENT_PARAMS_UPDATE,
            message=f"concurrency: {old} -> {concurrency}",
        )


# ============================== 子命令 ==============================

def cmd_init(args) -> int:
    run_dir = Path(args.run_dir).expanduser()
    if not run_dir.is_dir():
        raise GuardError(
            f"run 目录不存在：{run_dir}\n"
            f"  编排层应先 mkdir 再写状态。"
        )
    run_dir = run_dir.resolve()
    if state_path_of(run_dir).exists():
        raise GuardError(
            f"本轮已有状态文件：{state_path_of(run_dir)}\n"
            f"  要续跑请用 --resume <该目录>，不要重复 init。"
        )

    created = now_iso()
    state = {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(run_dir),
        "created_at": created,
        "updated_at": created,
        "adopted": False,
        "params": {
            "agent": args.agent,
            "count": args.count,
            "requirement": args.requirement,
            "output_parent": args.output_parent,
            "concurrency": args.concurrency,
        },
        "frozen": list(FROZEN_PARAMS),
        "seq": 0,
        "stages": {
            stage: {
                "status": STATUS_PENDING,
                "started_at": None,
                "ended_at": None,
                "exit_code": None,
                "anchor": anchor_rel_of(stage),
                "anchor_sha256": None,
                "warnings": [],
                "reason": None,
            }
            for stage in STAGES
        },
    }
    state_dir_of(run_dir).mkdir(parents=True, exist_ok=True)
    append_event(run_dir, state, EVENT_INIT, message=f"created {run_dir.name}")
    save_state(run_dir, state)
    emit(status_payload(state), args.format)
    return EXIT_OK


def cmd_status(args) -> int:
    state = load_state(Path(args.run_dir).expanduser().resolve())
    emit(status_payload(state), args.format)
    return EXIT_OK


def cmd_begin(args) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = load_state(run_dir)
    stage = args.stage
    require_stage(stage)
    guard_linear(state, stage)

    meta = state["stages"][stage]
    if meta["status"] == STATUS_DONE:
        raise GuardError(
            f"阶段 {stage} 已完成，不能直接重开。\n"
            f"  如需重跑：删除锚点产物 {anchor_rel_of(stage)} 后执行 --resume"
            f"（会降级并停住），再执行一次 --resume 才会重跑。"
        )

    if args.input_path:
        input_path = Path(args.input_path).expanduser()
        if not input_path.exists():
            raise GuardError(
                f"阶段 {stage} 的输入路径不存在：{input_path}\n"
                f"  请用同一条命令重开一轮（新建的 run 目录会重新生成输入）。"
            )

    previous = meta["status"]
    meta["status"] = STATUS_RUNNING
    meta["started_at"] = now_iso()
    meta["ended_at"] = None
    meta["exit_code"] = None
    meta["reason"] = None
    append_event(
        run_dir, state, EVENT_BEGIN, stage=stage,
        from_status=previous, to_status=STATUS_RUNNING,
        message="reentry" if previous == STATUS_RUNNING else "",
    )
    save_state(run_dir, state)
    emit(status_payload(state), args.format)
    return EXIT_OK


def cmd_complete(args) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = load_state(run_dir)
    stage = args.stage
    require_stage(stage)

    meta = state["stages"][stage]
    if meta["status"] != STATUS_RUNNING:
        raise GuardError(
            f"阶段 {stage} 当前是 {meta['status']}，只有 running 可以 complete。"
        )

    anchor = anchor_path_of(run_dir, stage)
    if not anchor.is_file():
        raise GuardError(
            f"阶段 {stage} 的锚点产物不存在：{anchor}\n"
            f"  不能标记完成。请检查上游是否真的交付，或改用 fail 记录失败。"
        )

    ended = now_iso()
    meta["status"] = STATUS_DONE
    meta["ended_at"] = ended
    meta["exit_code"] = args.exit_code
    meta["anchor_sha256"] = sha256_of(anchor)
    meta["warnings"] = list(args.warning or [])
    meta["reason"] = None
    append_event(
        run_dir, state, EVENT_COMPLETE, stage=stage,
        from_status=STATUS_RUNNING, to_status=STATUS_DONE,
        exit_code=args.exit_code,
        duration_s=duration_between(meta["started_at"], ended),
        warnings=meta["warnings"],
    )
    save_state(run_dir, state)
    emit(status_payload(state), args.format)
    return EXIT_OK


def cmd_fail(args) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = load_state(run_dir)
    stage = args.stage
    require_stage(stage)

    meta = state["stages"][stage]
    if meta["status"] != STATUS_RUNNING:
        raise GuardError(
            f"阶段 {stage} 当前是 {meta['status']}，只有 running 可以 fail。"
        )

    ended = now_iso()
    meta["status"] = STATUS_FAILED
    meta["ended_at"] = ended
    meta["exit_code"] = args.exit_code
    meta["reason"] = args.reason
    append_event(
        run_dir, state, EVENT_FAIL, stage=stage,
        from_status=STATUS_RUNNING, to_status=STATUS_FAILED,
        exit_code=args.exit_code,
        duration_s=duration_between(meta["started_at"], ended),
        message=args.reason,
    )
    save_state(run_dir, state)
    emit(status_payload(state), args.format)
    return EXIT_OK


def _downgrade(state, stage, reason):
    meta = state["stages"][stage]
    meta["status"] = STATUS_PENDING
    meta["ended_at"] = None
    meta["exit_code"] = None
    meta["anchor_sha256"] = None
    meta["reason"] = None
    return reason


def cmd_reconcile(args) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    state = load_state(run_dir)

    # 第 3 步：参数冻结校验（只允许 concurrency 变化）。
    check_resume_params(state, args, run_dir)

    promoted, downgraded = [], []

    for stage in STAGES:
        meta = state["stages"][stage]
        anchor = anchor_path_of(run_dir, stage)
        status = meta["status"]

        if status == STATUS_DONE:
            if not anchor.is_file():
                downgraded.append((stage, _downgrade(state, stage, "anchor missing")))
            elif meta.get("anchor_sha256") != sha256_of(anchor):
                downgraded.append((stage, _downgrade(state, stage, "anchor changed")))
        elif status == STATUS_RUNNING and anchor.is_file():
            ended = now_iso()
            meta["status"] = STATUS_DONE
            meta["ended_at"] = ended
            meta["exit_code"] = None
            meta["anchor_sha256"] = sha256_of(anchor)
            promoted.append(stage)

    # 级联降级：被降级段之后所有已完成的段，都是基于旧输入算出来的。
    downgraded_stages = {stage for stage, _ in downgraded}
    if downgraded_stages:
        first = min(downgraded_stages, key=STAGES.index)
        for stage in STAGES[STAGES.index(first) + 1:]:
            meta = state["stages"][stage]
            if meta["status"] == STATUS_DONE:
                downgraded.append(
                    (stage, _downgrade(state, stage, f"upstream {first} downgraded"))
                )

    for stage in promoted:
        meta = state["stages"][stage]
        append_event(
            run_dir, state, EVENT_PROMOTE, stage=stage,
            from_status=STATUS_RUNNING, to_status=STATUS_DONE,
            message="anchor present; status inferred",
        )
    for stage, reason in downgraded:
        append_event(
            run_dir, state, EVENT_DOWNGRADE, stage=stage,
            from_status=STATUS_DONE, to_status=STATUS_PENDING,
            message=f"{reason}: {anchor_rel_of(stage)}",
        )

    stop = bool(downgraded)
    blocked_reason = None
    if stop:
        blocked_reason = (
            "本轮有阶段产物被删除或改写，已降级为 pending："
            + "、".join(s for s, _ in downgraded)
            + "。本次调用停在该段之前；确认无误后再执行一次 --resume 才会重跑。"
        )

    save_state(run_dir, state)
    payload = status_payload(state, blocked_reason=blocked_reason)
    payload["promoted"] = promoted
    payload["downgraded"] = [
        {"stage": s, "reason": r} for s, r in downgraded
    ]
    payload["stop"] = stop
    emit(payload, args.format)
    return EXIT_OK


# ============================== CLI ==============================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="state.py",
        description="agent-eval 编排层状态机：init / status / begin / complete / fail / reconcile",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_run_dir(p):
        p.add_argument("--run-dir", required=True, help="本轮 run 目录")

    def add_format(p):
        p.add_argument("--format", choices=("json", "table"), default="json")

    p_init = sub.add_parser("init", help="初始化本轮状态（mkdir 之后立即调用）")
    add_run_dir(p_init)
    add_format(p_init)
    p_init.add_argument("--agent")
    p_init.add_argument("--count", type=int)
    p_init.add_argument("--requirement")
    p_init.add_argument("--output-parent")
    p_init.add_argument("--concurrency", type=int, default=1)
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="只读状态，给出 next_action")
    add_run_dir(p_status)
    add_format(p_status)
    p_status.set_defaults(func=cmd_status)

    p_begin = sub.add_parser("begin", help="进入某一段；线性守卫在此生效")
    add_run_dir(p_begin)
    add_format(p_begin)
    p_begin.add_argument("--stage", required=True, choices=STAGES)
    p_begin.add_argument("--input-path", help="本段所需输入路径；给了就校验存在")
    p_begin.set_defaults(func=cmd_begin)

    p_complete = sub.add_parser("complete", help="标记完成；校验锚点并回写哈希")
    add_run_dir(p_complete)
    add_format(p_complete)
    p_complete.add_argument("--stage", required=True, choices=STAGES)
    p_complete.add_argument("--exit-code", type=int, default=0)
    p_complete.add_argument("--warning", action="append")
    p_complete.set_defaults(func=cmd_complete)

    p_fail = sub.add_parser("fail", help="标记失败（命中串接判据的「停」分支时）")
    add_run_dir(p_fail)
    add_format(p_fail)
    p_fail.add_argument("--stage", required=True, choices=STAGES)
    p_fail.add_argument("--reason", required=True)
    p_fail.add_argument("--exit-code", type=int)
    p_fail.set_defaults(func=cmd_fail)

    p_reconcile = sub.add_parser("reconcile", help="开场对账；续跑时顺带校验冻结参数")
    add_run_dir(p_reconcile)
    add_format(p_reconcile)
    p_reconcile.add_argument("--agent")
    p_reconcile.add_argument("--count", type=int)
    p_reconcile.add_argument("--requirement")
    p_reconcile.add_argument("--concurrency", type=int)
    p_reconcile.set_defaults(func=cmd_reconcile)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except GuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_GUARD
    except StateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"ERROR: 文件操作失败：{exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
