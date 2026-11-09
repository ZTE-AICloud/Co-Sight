"""state 读写的命令行入口 —— 跨岗位调用本 skill 的唯一方式。

其他 skill / agent 需要读写 state 时走本 CLI（Bash 调用），不 import 本目录的
模块 —— 各岗位脚本相互独立，通过进程边界组合。

用法:
    python3 state_cli.py read      --planning-dir .drive/plan-<UTC-YYYYMMDD-HHMM>-<name>
    python3 state_cli.py require   --planning-dir .drive/plan-<UTC-YYYYMMDD-HHMM>-<name>
    python3 state_cli.py update    --planning-dir .drive/plan-<UTC-YYYYMMDD-HHMM>-<name> --set active_stage=analyze
    python3 state_cli.py update    --planning-dir .drive/plan-<UTC-YYYYMMDD-HHMM>-<name> --set-json pause_checkpoint='{"at":"..."}'
    python3 state_cli.py transition --planning-dir .drive/plan-<UTC-YYYYMMDD-HHMM>-<name> --to analyze
    python3 state_cli.py request-confirmation --planning-dir .drive/plan-<UTC-YYYYMMDD-HHMM>-<name> --stage plan
    python3 state_cli.py log       --planning-dir .drive/plan-<UTC-YYYYMMDD-HHMM>-<name> --event stage_advanced --field to=analyze

流转默认要求人工确认：阶段不在 confirmed_stages 里就拒绝推进。放行只能靠
confirm_stage.py，该脚本刻意不在任何 skill 的 allowed-tools 内。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from audit_append import log as audit_log
from envelope import (
    Envelope,
    REASON_INVALID_ARG,
    REASON_INVALID_TRANSITION,
    emit,
)
from state_rules import (
    STAGES,
    is_rollback,
    requires_verdict,
    validate_transition,
    validate_verdict,
)
from state_write import read_state, require_state, root_segment, update_fields
from workflow_runtime import (
    SOURCE_BUILTIN,
    SOURCE_USER_YAML,
    WorkflowRuntimeError,
    is_rollback_in_phases,
    resolve_active_stages,
    resolve_workflow_phases,
    validate_transition_in_phases,
)

# 阶段未经人工确认。default-deny 的拒绝码。
REASON_CONFIRMATION_REQUIRED = "confirmation_required"

# 试图改只能由 confirm_stage.py 写的字段。
REASON_PROTECTED_FIELD = "protected_field"

# 质检未出 pass 就想宣布完工。
REASON_VERDICT_NOT_PASS = "verdict_not_pass"
REASON_TRUST_GATE_VIOLATION = "trust_gate_violation"


def _parse_pairs(pairs: list[str] | None, flag: str) -> dict[str, str] | Envelope:
    """把 key=value 列表解析成 dict。"""
    result: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            return Envelope.fail(
                REASON_INVALID_ARG,
                error=f"{flag} 需要 key=value 形式，收到: {item!r}",
            )
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            return Envelope.fail(REASON_INVALID_ARG, error=f"{flag} 缺少 key: {item!r}")
        result[key] = value
    return result


def _coerce(value: str) -> object:
    """把命令行字符串还原成 JSON 友好的标量。"""
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none", ""):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def cmd_read(args: argparse.Namespace) -> Envelope:
    return read_state(Path(args.planning_dir))


def cmd_require(args: argparse.Namespace) -> Envelope:
    return require_state(Path(args.planning_dir))


# 只能由 confirm_stage.py / confirm_node.py 写的字段。放在这里能被 update 改的话，
# 模型就能自己给自己签字，整套 HITL 退化为空。confirmed_stages 是 phase 模式阶段
# 确认；confirmed_nodes 是 DAG 模式节点确认，对应 confirm_node.py。
PROTECTED_FIELDS: frozenset[str] = frozenset({"confirmed_stages", "confirmed_nodes"})


def cmd_update(args: argparse.Namespace) -> Envelope:
    scalars = _parse_pairs(args.set, "--set")
    if isinstance(scalars, Envelope):
        return scalars
    structured = _parse_pairs(args.set_json, "--set-json")
    if isinstance(structured, Envelope):
        return structured
    if not scalars and not structured:
        return Envelope.fail(
            REASON_INVALID_ARG, error="至少给一个 --set 或 --set-json"
        )

    # 比根段而非整串：点号是路径分隔符，`confirmed_stages.0` 会写进受保护结构里。
    touched = {
        key for key in (set(scalars) | set(structured))
        if root_segment(key) in PROTECTED_FIELDS
    }
    if touched:
        return Envelope.fail(
            REASON_PROTECTED_FIELD,
            error=f"{sorted(touched)} 不能用 update 修改",
            fields=sorted(touched),
            reason_why="人工确认记录只能由 confirm_stage.py 写入，否则等于自己签字",
        )

    fields: dict[str, object] = {k: _coerce(v) for k, v in scalars.items()}
    for key, raw in structured.items():
        try:
            fields[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            return Envelope.fail(
                REASON_INVALID_ARG,
                error=f"--set-json {key} 的值不是合法 JSON: {exc}",
                value=raw,
            )
    return update_fields(Path(args.planning_dir), **fields)


def count_waves(planning_dir: Path) -> int | None:
    """从 waves.yaml 数出计划的 wave 数。读不到或数不出返回 None。

    返回 None 时调用方保留原值 —— 宁可留着默认值，也不写一个猜出来的数进状态。
    yaml 解析失败不能让 transition 整体失效：状态写入是唯一通道，
    它必须比一个进度字段更可靠。
    """
    waves_path = Path(planning_dir) / "waves.yaml"
    if not waves_path.is_file():
        return None
    try:
        text = waves_path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        import yaml
    except ImportError:
        return None

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None

    if not isinstance(doc, dict):
        return None
    waves = doc.get("waves")
    if not isinstance(waves, list) or not waves:
        return None
    return len(waves)


def read_phase_skip_git(planning_dir: Path, stage: str) -> bool | None:
    """读 workflow.yaml 里某 phase 的 skip_git 声明。读不到返回 None。

    要落进 state 才能被强制：hook 只用 stdlib、不解析 yaml，但它必须能拦住
    git 命令——否则 skip_git 只是一句注释。
    """
    # planning_dir 是 .drive/<plan_dir>/，其父级 .drive/，再上一级才是项目根（work_dir）。
    workflow_dir = Path(planning_dir).parent.parent
    for name in ("workflow.yaml", "workflow.yml"):
        path = workflow_dir / name
        if not path.is_file():
            continue
        try:
            import yaml
        except ImportError:
            return None
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            return None
        if not isinstance(doc, dict):
            return None
        for item in doc.get("phases") or []:
            if isinstance(item, dict) and str(item.get("stage", "")) == stage:
                return bool(item.get("skip_git", False))
        return None
    return None


def cmd_transition(args: argparse.Namespace) -> Envelope:
    """校验流转合法 + 人工已确认，才写 active_stage。两项都不落盘失败。"""
    if os.environ.get("DRIVE_TRUSTED") != "1":
        return Envelope.fail(
            REASON_TRUST_GATE_VIOLATION,
            error="调用方必须设置 DRIVE_TRUSTED=1 环境变量前缀",
            hint=f"DRIVE_TRUSTED=1 python3 state_cli.py transition --to <stage>",
        )
    planning_dir = Path(args.planning_dir)
    current = require_state(planning_dir)
    if not current.ok:
        return current

    state = current.data["state"]
    from_stage = str(state.get("active_stage", "") or "start")

    # 双轨 forward validation：
    # builtin 路径走 state_rules.validate_transition；user_yaml 路径走
    # workflow_runtime.validate_transition_in_phases（与 hooks_protocol
    # _validate_transition_user 同款逻辑）。
    try:
        phases, _source = resolve_workflow_phases(planning_dir)
    except WorkflowRuntimeError as exc:
        return Envelope.fail(REASON_INVALID_ARG, error=str(exc))
    if _source == SOURCE_USER_YAML:
        ok, reason = validate_transition_in_phases(from_stage, args.to, phases)
    else:
        ok, reason = validate_transition(from_stage, args.to)
    if not ok:
        return Envelope.fail(
            REASON_INVALID_TRANSITION,
            error=reason,
            from_stage=from_stage,
            to_stage=args.to,
        )

    verdict = state.get("verdict")
    ok, reason = validate_verdict(args.to, verdict if verdict is None else str(verdict))
    if not ok:
        return Envelope.fail(
            REASON_VERDICT_NOT_PASS,
            error=reason,
            from_stage=from_stage,
            to_stage=args.to,
            verdict=verdict,
        )

    gate = check_stage_confirmed(state, from_stage)
    if not gate.ok:
        return gate

    fields: dict[str, object] = {
        "active_stage": args.to,
        "pending_confirmation": None,
    }

    # pending_plan_review 是 plan 阶段特有的等待标记。一旦流转出 plan，
    # 它再为 true 就是过期数据，会让后续阶段误判"还在等人审计划"。
    if from_stage == "plan" and state.get("pending_plan_review"):
        fields["pending_plan_review"] = False

    # 进 execute 时把 waves_total 对齐真实计划。默认值 1 会让进度显示始终是
    # "wave 1/1"，多波计划看起来永远只剩一波。在这里统一填，写状态的各方
    # 就不必各自重复读 waves.yaml。
    if args.to == "execute":
        total = count_waves(planning_dir)
        if total is not None:
            fields["waves_total"] = total

    # 把目标阶段的 skip_git 声明落进 state，供 hook 强制。声明缺失时按 False
    # 落地——git 默认可用，只有明确声明才禁。
    skip_git = read_phase_skip_git(planning_dir, args.to)
    fields["skip_git"] = bool(skip_git)

    # 回退意味着要重做：目标阶段及其下游的旧确认全部失效。人当初点头的是旧产出，
    # 重做后的新产出没人看过，不能沿用那次放行。
    revoked: list[str] = []
    # 双轨 rollback 判定：builtin 走 state_rules.is_rollback
    # （"plan" + from∈{execute,evaluate}）；user_yaml 走 is_rollback_in_phases（to 在
    # stages 顺序里位于 from 之前）。
    if _source == SOURCE_USER_YAML:
        rollback = is_rollback_in_phases(from_stage, args.to, phases)
    else:
        rollback = is_rollback(from_stage, args.to)
    if rollback:
        confirmed = list(state.get("confirmed_stages") or [])
        # 双轨 stale 切片：builtin 与原 STAGES[STAGES.index(args.to):] 等价；
        # user_yaml 按 phases 顺序定义"目标阶段及其下游"。
        ordered_stages = phases.stages
        stale = (
            set(ordered_stages[ordered_stages.index(args.to):])
            if args.to in ordered_stages
            else set()
        )
        revoked = [s for s in confirmed if s in stale]
        if revoked:
            fields["confirmed_stages"] = [s for s in confirmed if s not in stale]

    env = update_fields(planning_dir, **fields)
    if env.ok:
        audit_log(planning_dir, "stage_advanced", **{"from": from_stage, "to": args.to})
        if requires_verdict(args.to):
            audit_log(
                planning_dir,
                "transition_with_verdict",
                **{"from": from_stage, "to": args.to, "verdict": verdict},
            )
        if revoked:
            audit_log(
                planning_dir,
                "confirmations_revoked_on_rollback",
                revoked=revoked,
                reason="回退重做，旧确认失效",
            )
    return env


def check_stage_confirmed(state: dict, stage: str) -> Envelope:
    """判定某阶段是否已被人工放行。default-deny。

    不用"有没有待确认标记"判断 —— 那可以靠不设标记绕过。改为要求阶段必须
    出现在 confirmed_stages 里，漏掉确认这一步就走不了。
    """
    if bool(state.get("auto_mode", False)):
        return Envelope.ok_envelope(gate="skipped", reason_skipped="auto_mode")

    # "start" 是隐式 entry state（default_state() 落盘 active_stage=None，cmd_transition
    # 在 line 216 把 None 归一化为 "start" 走 VALID_TRANSITIONS），没有产物可审——自动放行
    if stage == "start":
        return Envelope.ok_envelope(gate="skipped", reason_skipped="implicit_entry_stage")

    confirmed = state.get("confirmed_stages") or []
    if stage in confirmed:
        return Envelope.ok_envelope(gate="cleared", stage=stage)

    return Envelope.fail(
        REASON_CONFIRMATION_REQUIRED,
        error=f"{stage} 阶段尚未经人工确认，不能流转",
        stage=stage,
        confirmed_stages=list(confirmed),
        how_to_clear=(
            "把本阶段产出讲给用户，等其明确放行后跑 "
            "confirm_stage.py --planning-dir <dir> --stage " + stage
        ),
        note="该命令不在 skill 的 allowed-tools 内，执行时会向用户请求授权",
    )


def cmd_request_confirmation(args: argparse.Namespace) -> Envelope:
    """标记某阶段待人工确认。只是记录待办，不构成放行。"""
    planning_dir = Path(args.planning_dir)
    current = require_state(planning_dir)
    if not current.ok:
        return current

    stage = args.stage or str(current.data["state"].get("active_stage", ""))
    # 双轨：builtin 走 STAGES；用户 yaml 走 parse_user_workflow_phases(planning_dir).stages
    try:
        active_stages, _source = resolve_active_stages(planning_dir)
    except WorkflowRuntimeError as exc:
        return Envelope.fail(REASON_INVALID_ARG, error=str(exc))
    if stage not in active_stages:
        return Envelope.fail(
            REASON_INVALID_ARG, error=f"未知阶段: {stage!r}", valid=sorted(active_stages)
        )

    env = update_fields(planning_dir, pending_confirmation=stage)
    if env.ok:
        audit_log(planning_dir, "confirmation_requested", stage=stage)
    return env


def cmd_log(args: argparse.Namespace) -> Envelope:
    parsed = _parse_pairs(args.field, "--field")
    if isinstance(parsed, Envelope):
        return parsed
    details = {k: _coerce(v) for k, v in parsed.items()}
    return audit_log(Path(args.planning_dir), args.event, **details)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="drive state 读写入口")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("read", "读 state（不存在返回默认值）"),
        ("require", "读 state（不存在则失败）"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--planning-dir", required=True)

    p_update = sub.add_parser("update", help="部分字段更新（加锁 + revision 自增）")
    p_update.add_argument("--planning-dir", required=True)
    p_update.add_argument("--set", action="append", metavar="KEY=VALUE")
    p_update.add_argument(
        "--set-json", action="append", metavar="KEY=JSON",
        help="写嵌套结构，值按 JSON 解析",
    )

    p_trans = sub.add_parser("transition", help="校验并推进 active_stage")
    p_trans.add_argument("--planning-dir", required=True)
    p_trans.add_argument("--to", required=True)

    p_req = sub.add_parser(
        "request-confirmation", help="标记当前阶段待人工确认（不构成放行）"
    )
    p_req.add_argument("--planning-dir", required=True)
    p_req.add_argument("--stage", default=None, help="缺省取当前 active_stage")

    p_log = sub.add_parser("log", help="追加一条 run-log 事件")
    p_log.add_argument("--planning-dir", required=True)
    p_log.add_argument("--event", required=True)
    p_log.add_argument("--field", action="append", metavar="KEY=VALUE")

    return parser


_HANDLERS = {
    "read": cmd_read,
    "require": cmd_require,
    "update": cmd_update,
    "transition": cmd_transition,
    "request-confirmation": cmd_request_confirmation,
    "log": cmd_log,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    emit(_HANDLERS[args.command](args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
