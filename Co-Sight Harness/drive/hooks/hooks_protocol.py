"""Hook 调用约定与核心防护决策逻辑 — Layer 4 hooks 的单一真相源。

两类消费者共享本模块，避免决策规则在 hook 脚本与测试之间漂移：
  1. hooks/ 下的 CLI 脚本（stdin JSON → exit 0/2）
  2. invoke_hook(hook_name, tool_name, tool_input) 编程接口（供 runtime 内部 / 测试调用）

决策规则:
  - planning_write_guard: 默认拒绝直接 Write/Edit `.drive/<plan_dir>/`，命中白名单才放行。
    白名单 = 叙事/人类可编辑文档 + 输入 + worker 产物；状态文件
    (executeState.json / run-log.jsonl) 不在白名单，强制走 SDK 通道。
  - state_transition_guard: 解析 Bash 里的 transition 调用，用状态机合法流转表
    校验 (from → to)；非法流转拒绝。跨阶段产物污染（execute 阶段写 plan 产物）拒绝。

阶段流转合法性委托给 state_rules.validate_transition。
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import hook_io
from state_rules import (
    STAGES,
    requires_verdict,
    validate_transition,
    validate_verdict,
)

if TYPE_CHECKING:
    # workflow_runtime 单副本位于 skills/state-machine/scripts/；
    # hook 链通过 sys.path 共享（state_transition_guard.py inline yaml 解析时
    # 注入）。本文件只在类型注解上引用 WorkflowPhases，避免模块加载时强依赖。
    from workflow_runtime import SOURCE_BUILTIN, WorkflowPhases


HookAction = Literal["allow", "deny"]


@dataclass(frozen=True)
class HookResult:
    """hook 决策结果。action=deny 时 message 必含拒绝原因（回显给 LLM）。"""

    action: HookAction
    message: str | None = None

    @classmethod
    def allow(cls, message: str | None = None) -> "HookResult":
        return cls(action="allow", message=message)

    @classmethod
    def deny(cls, message: str) -> "HookResult":
        return cls(action="deny", message=message)

    @property
    def is_denied(self) -> bool:
        return self.action == "deny"

    def exit_code(self) -> int:
        """deny → 2（Claude Code 回显 stderr 给 LLM），allow → 0。"""
        return 2 if self.is_denied else 0


# === planning_write_guard 白名单（匹配 .drive/<plan_dir>/ 之后的 subpath）===
# 按"约定"放行，不按"已知路径名"枚举：drive 流程会自然产生 artifacts/、tasks/、
# bootstrap/ 之类的子目录，把每个具体子目录名写进白名单是错的。规则应是：
#   1. 已知顶层文档（按名字 + .md/.yaml 灵活后缀）
#   2. 三个递归子目录（worker 产物、taskRecord、流程自身子目录）
# 状态文件（executeState.json / run-log.jsonl）刻意不在此列 → 强制走 SDK。
WRITE_WHITELIST_PATTERNS: tuple[str, ...] = (
    # 流程产物 —— 已知名字，按名字 + .md/.yaml 灵活后缀
    r"^continue-here\.(md|yaml)$",
    r"^summary\.(md|yaml)$",
    r"^plan-summary\.(md|yaml)$",
    r"^manifest\.(md|yaml)$",
    r"^verification(-report)?\.(md|yaml)$",     # evaluate 阶段产物
    # 流程子目录 —— 任意子目录都放行
    r"^artifacts/.+",                          # worker 产物：SUMMARY.md / resumption.log / 分析文件
    r"^taskRecord\.yaml$",                  # planner 写顶层 taskRecord.yaml
    r"^tasks/.+\.yaml$",                       # accountant 写细粒度 tasks/<plan>-Txx.yaml
    r"^bootstrap/.+",                          # drive 流程自身加的子目录
    # 用户输入
    r"^inputs/.+",
    # executor 冷启动缓存（pack_context.py 在 plan 末尾写入）
    r"^context_pack/.+",
    # 流程暂停标记位
    r"^\.pause$",
    # evaluator 产出的活动 report
    r"^evaluation/.+\.md$",
)

# 强制走 SDK 的状态文件（即使有人误加进白名单也不放行）——用于给出更明确的拒绝提示。
SDK_MANAGED_SUBPATHS: frozenset[str] = frozenset({
    "executeState.json",
    "run-log.jsonl",
})


def planning_subpath(file_path: str) -> str | None:
    """返回 .drive/<plan_dir>/ 之后的相对 subpath；非该路径返回 None。

    路径前缀为 .drive/plan-<UTC-YYYYMMDD-HHMM>-<name>/。
    探测逻辑：在路径 parts 中找 .drive/ 后紧跟的 plan- 前缀段，取其后的 subpath。

    注：本函数不限定具体 plan_dir——跨 plan 写过滤由调用方 check_planning_write
    顶层的 _match_other_plan_dir 单独处理。
    """
    if not file_path:
        return None
    parts = Path(file_path).parts
    for i, part in enumerate(parts):
        if part.startswith("plan-") and i > 0 and parts[i - 1] == ".drive":
            subpath = "/".join(parts[i + 1 :])
            return subpath or None
    return None


def is_write_whitelisted(subpath: str) -> bool:
    """.drive/<plan_dir>/ 之后的 subpath 是否命中写白名单。

    跨 plan 写过滤由 check_planning_write 顶层处理，
    本函数只看 subpath 内容是否符合白名单。
    """
    return any(re.search(pat, subpath) for pat in WRITE_WHITELIST_PATTERNS)


def check_planning_write(
    tool_name: str,
    tool_input: dict[str, Any],
    current_plan_dir: str | None = None,
) -> HookResult:
    """PreToolUse: 拦截对 .drive/<plan_dir>/ 非白名单路径的直接 Write/Edit/MultiEdit。

    跨 plan 写拦截——写别的 plan 路径会被 deny。

    - 非写类工具 → allow
    - 非 plan 路径 → allow
    - 在 current_plan_dir 内的白名单 subpath → allow
    - 在 current_plan_dir 内的 SDK 托管文件 → deny，提示走 SDK
    - 跨 plan 写（subpath 在别的 plan- 目录）→ deny
    - 当前 plan 内非白名单 → deny
    """
    if tool_name not in {"Write", "Edit", "MultiEdit"}:
        return HookResult.allow()

    file_path = (tool_input or {}).get("file_path", "")

    # 跨 plan 写拦截：先检测是否在别的 plan_dir 下
    if current_plan_dir:
        other_plan_match = _match_other_plan_dir(file_path, current_plan_dir)
        if other_plan_match:
            return HookResult.deny(
                f"BLOCKED: {tool_name} 跨 plan 写拦截违规: {file_path}\n"
                f"当前 plan 是 {current_plan_dir}，但目标在另一 plan 子目录 "
                f"{other_plan_match}。\n"
                f"drive 工作单元约定：每个 agent 在自己的 plan-dir 下工作。"
                f"如需跨 plan 通信：写禁止，读允许（用 Read/Glob）。"
            )

    subpath = planning_subpath(file_path)
    if subpath is None:
        return HookResult.allow()  # 非 plan 路径放行

    if subpath in SDK_MANAGED_SUBPATHS:
        return HookResult.deny(
            f"BLOCKED: {tool_name} 直接写状态文件 .drive/{current_plan_dir}/{subpath} 违规。\n"
            f"状态文件由 SDK 托管，只能用 Bash 调 SDK 写入 "
            f"(state-machine skill 的 state_cli.py)。"
        )

    if is_write_whitelisted(subpath):
        return HookResult.allow()

    return HookResult.deny(
        f"BLOCKED: {tool_name} 直接写 .drive/{current_plan_dir}/ 非白名单路径违规: {file_path}\n"
        f"工具即能力边界: 状态由 SDK 写入 (state-machine skill 的 state_cli.py)。"
        f"白名单 (continue-here/summary/inputs/artifacts...) 才允许直接写。"
    )


def _match_other_plan_dir(file_path: str, current_plan_dir: str) -> str | None:
    """检测 file_path 是否在别的 plan-<ts>-<name>/ 子目录下（跨 plan 写拦截）。

    返回值：其他 plan_dir 名（不在 current_plan_dir 时）；否则 None。
    """
    parts = Path(file_path).parts
    for i, part in enumerate(parts):
        if not part.startswith("plan-"):
            continue
        if i == 0 or parts[i - 1] != ".drive":
            continue
        if part != current_plan_dir:
            return part
    return None


# === state_transition_guard 跨阶段产物归属 ===
# 每个阶段只允许写自己产出的子树。归属明确的路径由非归属阶段写入 → 拒绝。
# 键为正则（匹配 .drive/<plan_dir>/ 之后的 subpath），值为拥有该产物的阶段。
ARTIFACT_OWNER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^plan-summary\.md$", "plan"),
    (r"^evaluation/.+\.md$", "evaluate"),
)


def artifact_owner(subpath: str) -> str | None:
    """返回该产物 subpath 归属的阶段；无明确归属返回 None。"""
    for pat, owner in ARTIFACT_OWNER_PATTERNS:
        if re.search(pat, subpath):
            return owner
    return None


# transition 命令里承载值的 flag（其余 flag 视为 bool，不吞下一个 token）。
# --planning-dir 是 state_cli.py 所有子命令的公共参数，必须包含，否则 parser
# 会把路径当成 from_stage。
_TRANSITION_VALUE_FLAGS: frozenset[str] = frozenset({"--from", "--to", "--planning-dir"})


# shell 控制 / 重定向 token：parser 一旦遇到就停止——后续是 pipe / redirect /
# post-pipe 命令的一部分，不属于 state_cli.py 调用本身。漏处理会让
# `transition --planning-dir /path --to Y 2>&1 | tail` 这种命令把
# `/path` 当 from_stage、`2>&1` 当 to_stage 误判。
_SHELL_CONTROL_TOKENS: frozenset[str] = frozenset({
    "2>&1", "1>&2", "&>", "2>", "1>", ">", ">>", "<", "<<", "<&", ">&",
    "|", "||", "&&", ";", "&",
})


def _is_value_flag(tok: str, value_flags: frozenset[str]) -> bool:
    """判断 token 是否为已知 value flag（含 `--flag=value` 紧凑形式）。

    shlex 把 `--git-dir=/p` 当单 token，原 set 仅匹配 `--git-dir`。
    """
    if tok in value_flags:
        return True
    return any(tok.startswith(vf + "=") for vf in value_flags)


def parse_transition_command(command: str) -> tuple[str | None, str, bool] | None:
    """从 Bash 命令串解析 state_cli.py transition 调用。

    返回 (from_stage, to_stage, is_trusted) 或 None。
    None = 不是 state_cli.py transition 调用（heredoc body / bash -c / python -c 嵌套）。
    is_trusted=False = 调用存在但缺 DRIVE_TRUSTED=1 前缀。
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None

    env_tokens: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if "=" in tok and not tok.startswith("--") and tok and tok[0].isalpha():
            if tok.split("=", 1)[0].isidentifier():
                env_tokens.append(tok)
                i += 1
                continue
        break
    cmd_tokens = tokens[i:]

    transition_idx = -1
    for j in range(len(cmd_tokens) - 1):
        t = cmd_tokens[j]
        if t == "state_cli.py" or t.endswith("/state_cli.py"):
            if cmd_tokens[j + 1] == "transition":
                transition_idx = j + 1
                break
    if transition_idx == -1:
        return None

    from_stage: str | None = None
    to_stage: str | None = None
    positional: list[str] = []
    j = transition_idx + 1
    while j < len(cmd_tokens):
        tok = cmd_tokens[j]
        if tok.startswith("--from="):
            from_stage = tok[len("--from="):]
            j += 1
            continue
        if tok.startswith("--to="):
            to_stage = tok[len("--to="):]
            j += 1
            continue
        if tok == "--from" and j + 1 < len(cmd_tokens):
            from_stage = cmd_tokens[j + 1]
            j += 2
            continue
        if tok == "--to" and j + 1 < len(cmd_tokens):
            to_stage = cmd_tokens[j + 1]
            j += 2
            continue
        if tok in _SHELL_CONTROL_TOKENS:
            break
        if tok.startswith("--"):
            if "=" in tok:
                j += 1
            elif _is_value_flag(tok, _TRANSITION_VALUE_FLAGS) and j + 1 < len(cmd_tokens):
                j += 2
            else:
                j += 1
            continue
        positional.append(tok)
        j += 1

    if from_stage is None and len(positional) >= 2:
        from_stage, to_stage = positional[0], positional[1]
    elif from_stage is not None and to_stage is None and positional:
        to_stage = positional[0]
    if to_stage is None:
        return None

    is_trusted = any(t == "DRIVE_TRUSTED=1" for t in env_tokens)
    return from_stage, to_stage, is_trusted


# 人工确认记录只能由 confirm_stage.py / confirm_node.py 写。任何别的路径改它都是
# 自己给自己签字。confirmed_stages 是 phase 模式的阶段确认，confirmed_nodes 是 DAG
# 模式的节点确认。
_CONFIRMED_FIELD = "confirmed_stages"
_CONFIRMED_NODES_FIELD = "confirmed_nodes"
_PROTECTED_CONFIRMATION_FIELDS: tuple[str, ...] = (
    _CONFIRMED_FIELD,
    _CONFIRMED_NODES_FIELD,
)
_CONFIRM_ENTRYPOINTS: tuple[str, ...] = ("confirm_stage.py", "confirm_node.py")


def check_confirmation_tampering(command: str) -> HookResult:
    """拦截绕过人工确认的尝试。

    state_cli 的 update 已在 CLI 层拒写这些字段，本检查是 harness 层的第二道：
    覆盖改写脚本、换路径调用、直接 jq/sed 编辑状态文件等绕法。
    """
    hit = [f for f in _PROTECTED_CONFIRMATION_FIELDS if f in command]
    if not hit:
        return HookResult.allow()

    # 读取类命令放行（查看当前确认了哪些阶段 / 节点是正当需求）。
    lowered = command.lower()
    reads_only = any(
        token in lowered
        for token in ("state_cli.py read", "state_cli.py require", "cat ", "grep ")
    )
    writes = any(
        token in command
        for token in ("--set", "--set-json", ">", ">>", "sed ", "jq ", "python3 -c")
    )
    if reads_only and not writes:
        return HookResult.allow()

    if any(entry in command for entry in _CONFIRM_ENTRYPOINTS):
        return HookResult.allow()  # 正规入口，其自身需用户授权

    return HookResult.deny(
        f"BLOCKED: 试图改写 {', '.join(hit)}。\n"
        f"人工确认记录只能由 {' / '.join(_CONFIRM_ENTRYPOINTS)} 写入 —— "
        f"从别处改它等于替用户签字。\n"
        f"要放行某阶段，把产出讲给用户，等其同意后跑 confirm_stage.py --stage <阶段>；"
        f"DAG 节点用 confirm_node.py --agent-id <节点 id>。"
    )


# trivial 任务跳 HITL 的阶段集合。evaluate 不在此列 —— 质检门禁对任何复杂度都强制。
_TRIVIAL_SKIP_STAGES: frozenset[str] = frozenset({"analyze", "plan", "execute"})


def check_stage_confirmation(from_stage: str) -> HookResult:
    """流出某阶段前，该阶段必须已被人工放行。default-deny。

    与 state_cli 的同名检查是两道独立的门：CLI 那道可能被绕过（模型换别的方式
    写状态），本道由 harness 强制，模型无法跳过。
    """
    planning_dir = hook_io.find_active_plan_dir()
    if planning_dir is None:
        return HookResult.allow()  # 无 .drive/<plan_dir>/ 时不归本 guard 管

    state = hook_io.read_execute_state(planning_dir)
    if state is None:
        return HookResult.allow()  # 读不到状态，无从判定，交由 CLI 自校验

    if bool(state.get("auto_mode", False)):
        return HookResult.allow()

    # trivial 任务：analyze / plan / execute gate 自动放行，evaluate 始终强制 HITL
    if state.get("complexity") == "trivial" and from_stage in _TRIVIAL_SKIP_STAGES:
        return HookResult.allow()

    confirmed = state.get("confirmed_stages")
    if not isinstance(confirmed, list):
        return HookResult.allow()  # 旧版状态无此字段，不倒查历史项目

    if from_stage in confirmed:
        return HookResult.allow()

    return HookResult.deny(
        f"BLOCKED: {from_stage} 阶段尚未经人工确认，不能流转。\n"
        f"已确认: {confirmed or '（无）'}\n"
        f"把本阶段产出讲给用户，等其明确放行后再跑 confirm_stage.py "
        f"--stage {from_stage}。该命令会向用户请求授权 —— 那个授权即人工确认。\n"
        f"不要替用户确认，也不要改 confirmed_stages 绕过。"
    )


# mark-completed 承载 --agent-id 的两种形态由解析器直接处理，其余 flag 里只有
# --planning-dir 会吃值，需声明以免把路径当成 agent id。
_MARK_COMPLETED_SUBCOMMAND = "mark-completed"
_MARK_VALUE_FLAGS: frozenset[str] = frozenset({"--planning-dir", "--agent-id", "--json"})


def parse_mark_completed_command(command: str) -> str | None:
    """从 Bash 命令串里解析 dag_runtime mark-completed 的 --agent-id。

    只认 mark-completed —— mark-failed / mark-skipped 不是推进，不归本 guard 管。
    解析不出 agent id → 返回 None。
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if _MARK_COMPLETED_SUBCOMMAND not in tokens:
        return None

    i = tokens.index(_MARK_COMPLETED_SUBCOMMAND) + 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--agent-id="):
            return tok[len("--agent-id="):] or None
        if tok == "--agent-id" and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok in _SHELL_CONTROL_TOKENS:
            break
        if tok.startswith("--") and "=" not in tok and _is_value_flag(
            tok, _MARK_VALUE_FLAGS
        ):
            i += 2
            continue
        i += 1
    return None


def check_dag_node_confirmation(command: str) -> HookResult:
    """DAG 模式推进一个节点前，该节点必须已被人工放行。default-deny。

    与 check_stage_confirmation 同构：phase 模式流出一个阶段要人点头，DAG 模式把一个
    节点标 completed 就是宣告其产出可进下游，同样要人点头。auto_mode 是唯一旁路 ——
    DAG 不认 complexity，trivial 不减门。

    PreToolUse 触发时机说明：hook 在外层 Bash 命令**开始时**校验命令字符串。
    若外层 bash 用 `&&` 串联 `confirm-node` 与 `mark-completed`，hook 看到
    的是一次 bash 调用，但内层 confirm-node 还没写 confirmed_nodes —— 会误判为
    "未确认就标 completed" 并 block。**正确做法是分两次独立 bash 调用**，详见
    skills/dag-runtime/SKILL.md "confirm-node + mark-completed 必须分两次调用" 章节。
    """
    agent_id = parse_mark_completed_command(command)
    if agent_id is None:
        return HookResult.allow()  # 非 mark-completed 调用，不归本 guard 管

    planning_dir = hook_io.find_active_plan_dir()
    if planning_dir is None:
        return HookResult.allow()  # 无 .drive/<plan_dir>/ 时不归本 guard 管

    state = hook_io.read_execute_state(planning_dir)
    if state is None:
        return HookResult.allow()  # 读不到状态，无从判定，交由 CLI 自校验

    if bool(state.get("auto_mode", False)):
        return HookResult.allow()

    confirmed = state.get(_CONFIRMED_NODES_FIELD)
    if not isinstance(confirmed, list):
        return HookResult.allow()  # 旧版状态无此字段，不倒查历史项目

    if agent_id in confirmed:
        return HookResult.allow()

    return HookResult.deny(
        f"BLOCKED: 节点 {agent_id} 尚未经人工确认，不能标 completed。\n"
        f"已确认: {confirmed or '（无）'}\n"
        f"把该节点产出讲给用户，等其明确放行后再跑 confirm_node.py "
        f"--agent-id {agent_id}。该命令会向用户请求授权 —— 那个授权即人工确认。\n"
        f"不要替用户确认，也不要改 {_CONFIRMED_NODES_FIELD} 绕过。\n"
        f"节点失败或需 cascade skip 时用 mark-failed / mark-skipped，那两条不设门。"
    )


def check_verdict_gate(to_stage: str) -> HookResult:
    """进入终态前，质检必须已出 pass。

    与 state_cli 的同名检查是两道独立的门，各自读一次 state，互不依赖。
    """
    if not requires_verdict(to_stage):
        return HookResult.allow()

    planning_dir = hook_io.find_active_plan_dir()
    if planning_dir is None:
        return HookResult.allow()

    state = hook_io.read_execute_state(planning_dir)
    if state is None:
        return HookResult.allow()  # 读不到状态，交由 CLI 自校验

    verdict = state.get("verdict")
    ok, reason = validate_verdict(to_stage, None if verdict is None else str(verdict))
    if ok:
        return HookResult.allow()

    return HookResult.deny(
        f"BLOCKED: 不能进入 {to_stage}。\n{reason}\n"
        f"先让 evaluator 完成质检并写 verdict，verdict=pass 才能收工。\n"
        f"不要手改 verdict 绕过——那是伪造质检结论。"
    )


def _validate_transition_user(
    from_stage: str, to_stage: str, phases: "WorkflowPhases"
) -> tuple[bool, str]:
    """用户 yaml 模式下的流转校验。

    等价于 state_rules.validate_transition 但用 WorkflowPhases.valid_transitions。
    phases 仅做 duck typing（属性访问 .stages / .valid_transitions），不强制 import 类型。
    """
    stages = frozenset(phases.stages)
    if from_stage not in stages:
        return False, (
            f"unknown from_stage: {from_stage!r}。"
            f"合法值: {sorted(phases.stages)}"
        )
    if to_stage not in stages:
        return False, f"unknown to_stage: {to_stage!r}。合法值: {sorted(phases.stages)}"
    allowed = phases.valid_transitions.get(from_stage, frozenset())
    if to_stage not in allowed:
        return False, (
            f"非法流转: {from_stage} → {to_stage}。"
            f"允许: {from_stage} → {sorted(allowed) if allowed else '(终态)'}"
        )
    return True, ""


def check_state_transition(
    tool_name: str,
    tool_input: dict[str, Any],
    active_stage: str | None = None,
    plan_dir: str | None = None,
    workflow_phases: "WorkflowPhases | None" = None,
    workflow_source: str = "builtin",
) -> HookResult:
    """守卫阶段流转与跨阶段产物污染。

    - Bash 调用 transition：解析 (from, to)，用状态机流转表校验，非法 → deny。
    - Write/Edit/MultiEdit：若目标是归属其它阶段的产物且当前阶段不匹配 → deny。
    - 其它情况 → allow。

    双轨：
    - workflow_source == "builtin"：用 state_rules.validate_transition + STAGES
    - workflow_source == "user_yaml"：用 _validate_transition_user + workflow_phases.stages
    builtin 路径行为零变化。
    """
    if tool_name == "Bash":
        command = (tool_input or {}).get("command", "")

        tamper = check_confirmation_tampering(command)
        if tamper.is_denied:
            return tamper

        dag_node_gate = check_dag_node_confirmation(command)
        if dag_node_gate.is_denied:
            return dag_node_gate

        parsed = parse_transition_command(command)
        if parsed is None:
            return HookResult.allow()
        from_stage, to_stage, is_trusted = parsed
        if not is_trusted:
            return HookResult.deny(
                "BLOCKED: state_cli.py transition 调用缺少 DRIVE_TRUSTED=1 前缀。"
                "可信任源仅 orchestrator 主对话；heredoc body / bash -c / python -c 嵌套调用一律拒绝。"
                "调用形式: DRIVE_TRUSTED=1 python3 state_cli.py transition --to <stage>"
            )
        # 命令只给目标时（state_cli transition --to Y），起点取当前 active_stage。
        if from_stage is None:
            from_stage = active_stage
        if not from_stage:
            return HookResult.allow()  # 起点未知，无法判定合法性，交由 CLI 自校验
        # 双轨：根据 workflow_source 选 builtin / user_yaml 表
        if workflow_source == "user_yaml" and workflow_phases is not None:
            ok, reason = _validate_transition_user(from_stage, to_stage, workflow_phases)
            valid_stages_list = list(workflow_phases.stages)
        else:
            ok, reason = validate_transition(from_stage, to_stage)
            valid_stages_list = list(STAGES)
        if not ok:
            return HookResult.deny(
                f"BLOCKED: 非法阶段流转 {from_stage} → {to_stage}。\n{reason}\n"
                f"合法阶段: {valid_stages_list}。"
            )

        verdict_gate = check_verdict_gate(to_stage)
        if verdict_gate.is_denied:
            return verdict_gate

        return check_stage_confirmation(from_stage)

    if tool_name in {"Write", "Edit", "MultiEdit"}:
        if not active_stage:
            return HookResult.allow()  # 未知当前阶段，无法判定跨阶段，放行
        file_path = (tool_input or {}).get("file_path", "")
        # 跨 plan 写拦截（与 planning_write_guard 同步）
        if plan_dir:
            other = _match_other_plan_dir(file_path, plan_dir)
            if other:
                return HookResult.deny(
                    f"BLOCKED: 跨 plan 写拦截违规: {file_path}\n"
                    f"当前 plan 是 {plan_dir}，但目标在另一 plan 子目录 {other}。\n"
                    f"drive 工作单元约定：每个 agent 在自己的 plan-dir 下工作。"
                )
        subpath = planning_subpath(file_path)
        if subpath is None:
            return HookResult.allow()
        owner = artifact_owner(subpath)
        if owner is not None and owner != active_stage:
            return HookResult.deny(
                f"BLOCKED: {active_stage} 阶段写入 {owner} 阶段产物违规: "
                f".drive/{plan_dir}/{subpath}\n"
                f"跨阶段产物污染: 该产物由 {owner} 阶段产出，"
                f"{active_stage} 阶段不得直接写。"
            )
        return HookResult.allow()

    return HookResult.allow()


# === invoke_hook 编程接口 ===
# 名称 → 决策函数。函数签名统一 (tool_name, tool_input, active_stage, plan_dir)；
# 不需要 active_stage / plan_dir 的守卫忽略对应参数。
# plan_dir 用于跨 plan 写拦截。
_HOOK_REGISTRY: dict[str, Any] = {
    "planning_write_guard": lambda tn, ti, stage, pd: check_planning_write(tn, ti, pd),
    "state_transition_guard": check_state_transition,
}

HOOK_NAMES: frozenset[str] = frozenset(_HOOK_REGISTRY)


def invoke_hook(
    hook_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
    active_stage: str | None = None,
    plan_dir: str | None = None,
    workflow_phases: "WorkflowPhases | None" = None,
    workflow_source: str = "builtin",
) -> HookResult:
    """按名调用注册的 hook 决策函数，返回 HookResult。

    plan_dir 用于跨 plan 写拦截（除非 hook 显式忽略）。
    workflow_phases / workflow_source 仅 state_transition_guard 关心；
    其它 hook 忽略这两个参数。未知 hook_name → deny（fail-closed，避免拼写错误静默放行）。
    """
    handler = _HOOK_REGISTRY.get(hook_name)
    if handler is None:
        return HookResult.deny(
            f"unknown hook: {hook_name!r}。已注册: {sorted(HOOK_NAMES)}"
        )
    # state_transition_guard 用扩展签名；其它 hook 用基础签名（忽略 workflow_* 参数）
    if hook_name == "state_transition_guard":
        return handler(
            tool_name, tool_input or {}, active_stage, plan_dir,
            workflow_phases, workflow_source,
        )
    return handler(tool_name, tool_input or {}, active_stage, plan_dir)
