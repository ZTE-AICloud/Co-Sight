"""workflow_runtime —— phase 模式 stage 集合的解析与运行时分发。

双轨设计：
- builtin 路径：项目无 workflow.yaml 时，从 `state_rules` 模块常量取（权威）。
- user_yaml 路径：项目有 workflow.yaml 时，从 yaml 解析出合法 stage 集合。

本模块是单副本，hook 链通过 `sys.path` 共享导入。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from state_rules import (
    STAGES as BUILTIN_STAGES,
    VALID_TRANSITIONS as BUILTIN_VALID_TRANSITIONS,
    VERDICT_REQUIRED_TARGETS as BUILTIN_VERDICT_REQUIRED_TARGETS,
)


# ---- constants ----

WORKFLOW_FILENAMES: tuple[str, ...] = ("workflow.yaml", "workflow.yml")
SOURCE_BUILTIN = "builtin"
SOURCE_USER_YAML = "user_yaml"


class WorkflowRuntimeError(Exception):
    """workflow 解析/校验失败。统一入口 fail-closed 用。

    支持 details kwargs（与 read_workflow.SchemaError / YamlParseError 模式一致），
    供调用方做结构化错误日志。
    """

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


@dataclass(frozen=True)
class WorkflowPhases:
    """用户 workflow.yaml 解析出的 phase 模式契约（frozen / immutable）。

    - stages: 合法 stage 名（按 phases 顺序）
    - valid_transitions: from_stage -> 合法目标 frozenset
    - terminal_stages: 终态 stage frozenset（进得去出不来）
    - phase_agents: phases[i].agent 名集合（hooks subagent_report_guard
      用此判定哪些 agent 持有阶段）
    """
    stages: tuple[str, ...]
    valid_transitions: dict[str, frozenset[str]]
    terminal_stages: frozenset[str]
    phase_agents: frozenset[str] = frozenset()


# ---- helpers ----

def _find_user_workflow_yaml(planning_dir: Path) -> Optional[Path]:
    """反查 planning_dir 上两级目录里的 workflow.yaml/.yml。

    planning_dir = .drive/<plan_dir>/，父级 = .drive/，再父级 = <project>（work_dir）。
    找路径（与 state_cli.py:170 `read_phase_skip_git` 同款模式）。
    """
    workflow_dir = Path(planning_dir).parent.parent
    for name in WORKFLOW_FILENAMES:
        candidate = workflow_dir / name
        if candidate.is_file():
            return candidate
    return None


def is_user_workflow_defined(planning_dir: Path) -> bool:
    """检查用户项目下是否存在 workflow.yaml。

    不读 yaml 内容，只判文件存在性（PROP §方案 §3）。
    """
    return _find_user_workflow_yaml(planning_dir) is not None


def parse_user_workflow_phases_from_dict(doc: dict) -> WorkflowPhases:
    """从 yaml 解析出的 dict 推出 WorkflowPhases。

    接受 phase 模式（mode=phase 或 mode 缺省）。
    DAG 模式抛 WorkflowRuntimeError（不是 phase 模式的合法输入；DAG 走 dag-runtime skill）。
    """
    mode = str(doc.get("mode", "phase")).strip() or "phase"
    if mode != "phase":
        raise WorkflowRuntimeError(
            f"workflow_runtime 仅支持 phase 模式；当前 mode={mode!r}。"
            f"DAG 模式请走 /dag-runtime skill。",
            mode=mode,
        )

    phases_raw = doc.get("phases")
    if not isinstance(phases_raw, list) or not phases_raw:
        raise WorkflowRuntimeError("phases 字段必须是非空列表")

    # ---- 校验 + 收集 stages ----
    seen: set[str] = set()
    stages: list[str] = []
    for i, p in enumerate(phases_raw):
        if not isinstance(p, dict):
            raise WorkflowRuntimeError(f"phases[{i}] 必须是 mapping")
        stage = p.get("stage")
        if not isinstance(stage, str) or not stage:
            raise WorkflowRuntimeError(f"phases[{i}].stage 必须是字符串")
        if stage in seen:
            raise WorkflowRuntimeError(f"phases[{i}].stage 重复: {stage!r}")
        seen.add(stage)
        stages.append(stage)

    # ---- valid_transitions：前向 + 后向跳转 ----
    allowed_back_jumps_raw = doc.get("allowed_back_jumps") or {}
    if not isinstance(allowed_back_jumps_raw, dict):
        raise WorkflowRuntimeError("allowed_back_jumps 必须是 mapping")

    valid_transitions: dict[str, frozenset[str]] = {}
    for i, stage in enumerate(stages):
        allowed: set[str] = set()
        # 前向：stage[i] -> stage[i+1]
        if i + 1 < len(stages):
            allowed.add(stages[i + 1])
        # 后向：allowed_back_jumps[stage] 列出的目标（必须是 backward）
        targets = allowed_back_jumps_raw.get(stage, [])
        if not isinstance(targets, list):
            raise WorkflowRuntimeError(
                f"allowed_back_jumps[{stage!r}] 必须是列表"
            )
        for t in targets:
            if t not in stages:
                raise WorkflowRuntimeError(
                    f"allowed_back_jumps[{stage!r}] 引用未知 stage: {t!r}"
                )
            if stages.index(t) >= i:
                raise WorkflowRuntimeError(
                    f"allowed_back_jumps[{stage!r}] 目标 {t!r} 不是 backward"
                )
            allowed.add(t)
        valid_transitions[stage] = frozenset(allowed)

    # ---- terminal_stages：phases[*].terminal_stage=true ----
    terminal_stages: set[str] = set()
    for p in phases_raw:
        if p.get("terminal_stage"):
            terminal_stages.add(str(p["stage"]))

    return WorkflowPhases(
        stages=tuple(stages),
        valid_transitions=valid_transitions,
        terminal_stages=frozenset(terminal_stages),
        phase_agents=frozenset(
            str(p["agent"]).strip()
            for p in phases_raw
            if isinstance(p, dict) and p.get("agent")
        ),
    )


def parse_user_workflow_phases(planning_dir: Path) -> WorkflowPhases:
    """反查 planning_dir → 用户 yaml → WorkflowPhases。

    前置：调用方应先用 `is_user_workflow_defined(planning_dir)` 拦截；本函数在 yaml
    缺失时也抛 WorkflowRuntimeError（防御性设计，避免下游 NoneType 错）。
    yaml 损坏或 schema 非法 → WorkflowRuntimeError，错误消息含恢复建议。
    """
    path = _find_user_workflow_yaml(planning_dir)
    if path is None:
        raise WorkflowRuntimeError(
            f"用户 workflow.yaml 不存在（planning_dir={planning_dir}）。"
            f"调用方应先用 is_user_workflow_defined 拦截。"
        )
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkflowRuntimeError(
            f"用户 workflow.yaml 损坏或非法: {exc}\n"
            f"修 yaml 后重试,或删除 yaml 走 builtin 默认。",
            path=str(path),
        ) from exc
    except OSError as exc:
        raise WorkflowRuntimeError(
            f"用户 workflow.yaml 读取失败: {exc}\n"
            f"修 yaml 后重试,或删除 yaml 走 builtin 默认。",
            path=str(path),
        ) from exc

    if not isinstance(doc, dict):
        raise WorkflowRuntimeError(
            f"workflow.yaml 顶层必须是 mapping（{path}）",
            path=str(path),
        )

    try:
        return parse_user_workflow_phases_from_dict(doc)
    except WorkflowRuntimeError as exc:
        # 加来源 prefix，让调用方与用户清楚是用户 yaml 失败不是 builtin 失败
        raise WorkflowRuntimeError(
            f"用户 workflow.yaml 损坏或非法: {exc}\n"
            f"修 yaml 后重试,或删除 yaml 走 builtin 默认。"
        ) from exc


def resolve_active_stages(planning_dir: Path) -> tuple[tuple[str, ...], str]:
    """统一入口：返回 (合法 stage 顺序列表, 来源标识 'builtin' | 'user_yaml')。

    builtin：返回 (BUILTIN_STAGES 元组, SOURCE_BUILTIN)。
    user_yaml：返回 (parse_user_workflow_phases(planning_dir).stages 元组, SOURCE_USER_YAML)。
    yaml 损坏 → WorkflowRuntimeError（让调用方决定 fail-closed）。

    注：返 ordered tuple 而非 frozenset 是为了支持 state_cli.py L261 的回退切片
    `ordered[ordered.index(args.to):]`；调用方需要 set 语义时用 frozenset(stages)。
    PROP §方案 §3 "集合" 语义不变；这是实现层面的选择。
    """
    if is_user_workflow_defined(planning_dir):
        phases = parse_user_workflow_phases(planning_dir)
        return phases.stages, SOURCE_USER_YAML
    return BUILTIN_STAGES, SOURCE_BUILTIN


def resolve_workflow_phases(planning_dir: Path) -> tuple[WorkflowPhases, str]:
    """返回 (WorkflowPhases, source)。含 valid_transitions + terminal_stages 的全量契约。

    builtin：从 state_rules.STAGES / VALID_TRANSITIONS / TERMINAL_STAGE 派生 WorkflowPhases。
    user_yaml：从 yaml 解析。
    yaml 损坏 → WorkflowRuntimeError。

    state_cli.cmd_transition 的 forward validation + rollback 检测用它。
    hooks_protocol._validate_transition_user 是同款逻辑（duck typing）。
    """
    if is_user_workflow_defined(planning_dir):
        return parse_user_workflow_phases(planning_dir), SOURCE_USER_YAML
    from state_rules import TERMINAL_STAGE
    return (
        WorkflowPhases(
            stages=BUILTIN_STAGES,
            valid_transitions=BUILTIN_VALID_TRANSITIONS,
            terminal_stages=frozenset({TERMINAL_STAGE}),
            phase_agents=frozenset(),  # builtin 路径 phase_agents 不可用，hooks 回退 DEFAULT
        ),
        SOURCE_BUILTIN,
    )


def validate_transition_in_phases(
    from_stage: str, to_stage: str, phases: WorkflowPhases
) -> tuple[bool, str]:
    """校验 from → to 是否在 phases.valid_transitions 内（hooks_protocol._validate_transition_user 同款）。

    与 state_rules.validate_transition 行为对偶 —— builtin 时调用方走 state_rules，
    user_yaml 时调本函数。返回 (ok, reason) 与 state_rules.validate_transition 同型。
    """
    stages = frozenset(phases.stages)
    if from_stage not in stages:
        return False, (
            f"unknown from_stage: {from_stage!r}。"
            f"合法值: {sorted(phases.stages)}"
        )
    if to_stage not in stages:
        return False, (
            f"unknown to_stage: {to_stage!r}。合法值: {sorted(phases.stages)}"
        )
    allowed = phases.valid_transitions.get(from_stage, frozenset())
    if to_stage not in allowed:
        return False, (
            f"非法流转: {from_stage} → {to_stage}。"
            f"允许: {from_stage} → {sorted(allowed) if allowed else '(终态)'}"
        )
    return True, ""


def is_rollback_in_phases(
    from_stage: str, to_stage: str, phases: WorkflowPhases
) -> bool:
    """user_yaml 模式下的回退判定：to 在 stages 顺序里位于 from 之前。

    builtin 路径仍走 state_rules.is_rollback（"plan" + from∈{execute,evaluate}）。
    本函数仅 user_yaml 路径使用；接受任意 WorkflowPhases，按 ordered stages 判定。
    """
    if from_stage not in phases.stages or to_stage not in phases.stages:
        return False
    return phases.stages.index(to_stage) < phases.stages.index(from_stage)


__all__ = [
    "WORKFLOW_FILENAMES",
    "SOURCE_BUILTIN",
    "SOURCE_USER_YAML",
    "WorkflowRuntimeError",
    "WorkflowPhases",
    "is_user_workflow_defined",
    "parse_user_workflow_phases",
    "parse_user_workflow_phases_from_dict",
    "resolve_active_stages",
    "resolve_workflow_phases",
    "validate_transition_in_phases",
    "is_rollback_in_phases",
    # builtin 重新导出（供调用方使用一致接口）
    "BUILTIN_STAGES",
    "BUILTIN_VALID_TRANSITIONS",
    "BUILTIN_VERDICT_REQUIRED_TARGETS",
]