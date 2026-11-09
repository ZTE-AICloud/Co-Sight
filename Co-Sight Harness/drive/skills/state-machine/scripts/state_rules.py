"""状态机流转规则 — 本 skill 的权威定义。

流转表的语义定义见 SKILL.md，本文件是其可执行形式。
只提供判定，不写状态、不做编排决策。

hooks/state_rules.py 持有一份用于不变量强制的独立副本，两者
由 tests/skills/state_machine/test_state_rules_sync.py 校验一致。
"""
from __future__ import annotations

STAGES: tuple[str, ...] = (
    "start", "analyze", "plan", "execute", "evaluate", "completed",
)

# completed 是终态：进得去，出不来。回退只能从 evaluate 走。
TERMINAL_STAGE = "completed"

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "start":     frozenset({"analyze"}),
    "analyze":   frozenset({"plan"}),
    "plan":      frozenset({"execute"}),
    "execute":   frozenset({"evaluate", "plan"}),
    "evaluate":  frozenset({"plan", "completed"}),
    "completed": frozenset(),
}

# 进入这些阶段前要求 verdict == "pass"
VERDICT_REQUIRED_TARGETS: frozenset[str] = frozenset({"completed"})
VERDICT_PASS = "pass"


def validate_transition(from_stage: str, to_stage: str) -> tuple[bool, str]:
    """校验 5 阶段流转是否合法。

    Returns:
        (ok, reason) — ok=True 合法；ok=False 时 reason 说明原因
    """
    if from_stage not in VALID_TRANSITIONS:
        return False, (
            f"unknown from_stage: {from_stage!r}。"
            f"合法值: {sorted(VALID_TRANSITIONS.keys())}"
        )
    if to_stage not in STAGES:
        return False, f"unknown to_stage: {to_stage!r}。合法值: {sorted(STAGES)}"
    allowed = VALID_TRANSITIONS[from_stage]
    if to_stage not in allowed:
        return False, (
            f"非法流转: {from_stage} → {to_stage}。"
            f"允许: {from_stage} → {sorted(allowed) if allowed else '(终态)'}"
        )
    return True, ""


def allowed_targets(from_stage: str) -> frozenset[str]:
    """返回某阶段的合法目标集合；未知阶段返回空集。"""
    return VALID_TRANSITIONS.get(from_stage, frozenset())


def is_rollback(from_stage: str, to_stage: str) -> bool:
    """判定是否为回退。回退走 baseline 版本化，不覆盖同一 baseline。"""
    return to_stage == "plan" and from_stage in ("execute", "evaluate")


def requires_verdict(to_stage: str) -> bool:
    """进入 to_stage 是否要求 verdict == pass。"""
    return to_stage in VERDICT_REQUIRED_TARGETS


def validate_verdict(to_stage: str, verdict: str | None) -> tuple[bool, str]:
    """校验目标阶段所需的 verdict 前置条件。

    质检没出 pass 就不能宣布完工——这是"完成"的定义，不是建议。
    """
    if not requires_verdict(to_stage):
        return True, ""
    if verdict is None or verdict == "":
        return False, (
            f"进入 {to_stage} 要求 verdict={VERDICT_PASS!r}，当前 state 无 verdict。"
            f"先让 evaluator 出 verdict。"
        )
    if verdict != VERDICT_PASS:
        return False, (
            f"进入 {to_stage} 要求 verdict={VERDICT_PASS!r}，当前为 {verdict!r}。"
        )
    return True, ""


__all__ = [
    "STAGES",
    "TERMINAL_STAGE",
    "VALID_TRANSITIONS",
    "VERDICT_REQUIRED_TARGETS",
    "VERDICT_PASS",
    "validate_transition",
    "allowed_targets",
    "is_rollback",
    "requires_verdict",
    "validate_verdict",
]
