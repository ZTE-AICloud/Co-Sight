"""解析并校验 workflow.yaml — 编排结构的唯一真相源。

只做解析 + 校验 + 输出，不做调度决策：谁在什么时候上场由 main agent 读本脚本
的输出后决定。

用法:
    python3 read_workflow.py --work-dir <dir>            # 解析，输出 JSON
    python3 read_workflow.py --work-dir <dir> --validate # 只校验，不输出模型

无 workflow.yaml 时返回内置默认 5-stage。非法 yaml 一律 fail-closed。

v2.2.1 重要变更：
- start 阶段已从 workflow.yaml 中移除（drive 内部自动调用 startup skill）
- 状态转换从 phases + allowed_back_jumps 推断，不再硬编码
- stage 名称完全自由，用户可自定义
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from envelope import (  # noqa: E402
    Envelope,
    REASON_INVALID_ARG,
    REASON_SCHEMA_INVALID,
    REASON_JSON_DECODE_ERROR,
)

# ---- Agent 扫描与校验 ----

BUILTIN_AGENT_TYPES: frozenset[str] = frozenset({
    "general-purpose",
    "Explore",
    "Plan",
    "claude",
    "statusline-setup",
    "claude-code-guide",
})


def _scan_agent_names(agents_dir: Path) -> set[str]:
    """扫描 agents_dir/**/*.md 读取 frontmatter name: 字段。

    返回所有合法 agent name 集合（忽略没有 name: 的文件）。
    """
    names = set()
    if not agents_dir.exists():
        return names

    for md_file in agents_dir.rglob("*.md"):
        try:
            with md_file.open("r", encoding="utf-8") as f:
                lines = []
                in_frontmatter = False
                frontmatter_started = False

                for line in f:
                    stripped = line.strip()
                    if stripped == "---":
                        if not frontmatter_started:
                            frontmatter_started = True
                            in_frontmatter = True
                        elif in_frontmatter:
                            # 第二个 --- 结束 frontmatter
                            break
                    elif in_frontmatter:
                        lines.append(line)

                if lines:
                    fm = yaml.safe_load("".join(lines))
                    if isinstance(fm, dict) and "name" in fm:
                        name = str(fm["name"]).strip()
                        if name:
                            names.add(name)
        except Exception:
            # 忽略解析失败的文件（可能不是 agent 文件）
            continue

    return names


def _validate_agent_ref(agent: str, project_agents: set[str], plugin_agents: set[str]) -> tuple[bool, str | None]:
    """校验单个 agent 引用是否合法。

    支持 4 种地址形式（Q12 决策）：
      - "@xxx"        → Claude Code 内置 subagent（Explore/Plan/general-purpose/claude 等）
      - "drive:xxx"   → drive 内置 agent（plugin agents/）
      - "plugin:xxx"  → plugin 提供的 agent（保留扩展）
      - 裸名          → 项目本地 agent

    优先级（Q12）：项目 > 用户 > plugin > 内置

    Args:
        agent: agent 引用
        project_agents: 项目 agent name 集合
        plugin_agents: 插件 agent name 集合

    Returns:
        (is_valid, error_message)
    """
    if not agent:
        return False, "agent 不能为空"

    if agent in BUILTIN_AGENT_TYPES:
        return True, None

    if agent.startswith("@"):
        bare_name = agent[1:]  # 去掉 "@" 前缀
        if not bare_name:
            return False, f"@-mention 后缺少 agent 名称"
        # @-mention 不在校验阶段 fail-closed——运行时 Agent tool 会兜底
        return True, None

    if agent.startswith("drive:"):
        bare_name = agent[6:]  # 去掉 "drive:" 前缀
        if not bare_name:
            return False, f"drive: 前缀后缺少 agent 名称"
        if bare_name not in plugin_agents:
            return False, f"drive 插件中不存在 agent: {bare_name!r}（可用: {sorted(plugin_agents)}）"
        return True, None

    if agent not in project_agents:
        return False, (
            f"项目中不存在 agent: {agent!r}"
            f"（可用项目 agents: {sorted(project_agents)}；"
            f"如需引用内置 agent 用 drive:<name> 或 @<name> 语法）"
        )

    return True, None

# ---- schema 常量 ----

GATE_TYPES: frozenset[str] = frozenset({"human_review", "artifact_check", "input_check"})
EXEC_MODES: frozenset[str] = frozenset({"code", "analysis"})
EVAL_LEVELS: frozenset[str] = frozenset({"L0", "L1", "L2"})
COMPLEXITY_TIERS: frozenset[str] = frozenset({"trivial", "standard", "complex"})

WORKFLOW_FILENAMES: tuple[str, ...] = ("workflow.yaml", "workflow.yml")

# 每个 phase 默认都要人点头才能流转出去。auto_mode 是唯一的整体旁路，
# 由用户在 start 时显式开启。gate 由 hooks/state_transition_guard.py 强制


# ---- 数据模型 ----

@dataclass(frozen=True)
class Gate:
    """一个 gate 声明。enforced_by 必填 —— 保证 gate 有 hook 强制，不靠模型自觉。"""

    type: str
    enforced_by: str
    skip_when: tuple[str, ...] = field(default_factory=tuple)
    on_revise: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "enforced_by": self.enforced_by,
            "skip_when": list(self.skip_when),
            "on_revise": self.on_revise,
        }


@dataclass(frozen=True)
class ExpectedState:
    """本阶段 agent 应上报的状态字段。供 orchestrator 读取与人工对照，不在写入时强制。"""

    required: tuple[str, ...] = field(default_factory=tuple)
    optional: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": list(self.required),
            "optional": list(self.optional),
        }


@dataclass(frozen=True)
class AgentSpec:
    """DAG 模式 workflow.yaml 中单个 agent 声明。

    对应 workflow.yaml 的：
        agents:
          - id: my-agent
            agent: drive:analyzer     # AgentAddress 形式
            depends_on: [other-agent]
            description: ...
            gate: { ... }
            terminal: true
            verdict_required: true
            ...
    """
    id: str
    agent: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    gate: Gate | None = None
    mode: str | None = None
    skip_git: bool = False
    verdict_required: bool = False
    terminal: bool = False
    expected_state: ExpectedState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent,
            "depends_on": list(self.depends_on),
            "description": self.description,
            "gate": self.gate.to_dict() if self.gate else None,
            "mode": self.mode,
            "skip_git": self.skip_git,
            "verdict_required": self.verdict_required,
            "terminal": self.terminal,
            "expected_state": self.expected_state.to_dict() if self.expected_state else {},
        }


@dataclass(frozen=True)
class DAGWorkflow:
    """DAG 模式 workflow 数据子（mode="dag" 时填充到 Workflow.dag 字段）。

    包含所有 DAG 特有的字段：agents / orchestration。
    Workflow 主类的 agents/orchestration 字段在解析后与此处同步。
    """
    agents: tuple[AgentSpec, ...] = field(default_factory=tuple)
    orchestration: dict[str, Any] = field(default_factory=dict)
    skip_agents: dict[str, list[str]] = field(default_factory=dict)  # complexity_rules.trivial.skip_agents

    def to_dict(self) -> dict[str, Any]:
        return {
            "agents": [a.to_dict() for a in self.agents],
            "orchestration": self.orchestration,
            "skip_agents": self.skip_agents,
        }


@dataclass(frozen=True)
class AgentAddress:
    """解析后的 agent 地址。

    支持 4 种地址形式（Q12 决策）：
      - "@xxx"        → kind="mention"，name="xxx"（Claude Code Agent tool 解析）
      - "drive:xxx"   → kind="scoped", scope="drive", name="xxx"
      - "plugin:xxx"  → kind="scoped", scope="plugin-name", name="xxx"
      - 裸名          → kind="bare", name="xxx"

    优先级（Q12）：项目 > 用户 > plugin > 内置
    """
    raw: str
    kind: str          # "mention" | "scoped" | "bare"
    scope: str | None = None
    name: str = ""
    resolved_from: str | None = None  # 实际找到 agent 的位置（路径或 "builtin"）


@dataclass(frozen=True)
class Phase:
    name: str
    stage: str
    agent: str | None = None
    description: str = ""
    gate: Gate | None = None
    mode: str | None = None
    wave_barrier: bool = False
    # 本阶段 agent 应上报哪些状态字段。缺省为 None —— 不声明即不约定。
    expected_state: ExpectedState | None = None
    # 本阶段不碰 git。用户说"不要执行任何 git 操作"时有个地方可落，
    # 不必让 orchestrator 每次临场解读。
    skip_git: bool = False
    # 流转出本阶段前要求 state.verdict == pass。
    verdict_required: bool = False
    # 本阶段是收工点：确认后转 completed，而不是继续往下流转。
    terminal_stage: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "agent": self.agent,
            "description": self.description,
            "gate": self.gate.to_dict() if self.gate else None,
            "mode": self.mode,
            "wave_barrier": self.wave_barrier,
            "expected_state": self.expected_state.to_dict() if self.expected_state else {},
            "skip_git": self.skip_git,
            "verdict_required": self.verdict_required,
            "terminal_stage": self.terminal_stage,
        }


@dataclass(frozen=True)
class Workflow:
    source: str
    phases: tuple[Phase, ...] = field(default_factory=tuple)
    complexity_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    allowed_back_jumps: dict[str, list[str]] = field(default_factory=dict)
    back_jump_limits: dict[str, int] = field(default_factory=dict)
    # DAG 模式字段：mode="dag" 时填充；phases 字段在 DAG 模式忽略
    mode: str = "phase"  # "phase" | "dag"（缺省 phase，read_workflow 警告）
    agents: tuple = field(default_factory=tuple)  # tuple[AgentSpec, ...]
    orchestration: dict[str, Any] = field(default_factory=dict)

    @property
    def stages(self) -> list[str]:
        return [p.stage for p in self.phases]

    def phase_for_stage(self, stage: str) -> Phase | None:
        return next((p for p in self.phases if p.stage == stage), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "mode": self.mode,
            "phases": [p.to_dict() for p in self.phases],
            "agents": [a.to_dict() for a in self.agents],
            "orchestration": self.orchestration,
            "complexity_rules": self.complexity_rules,
            "allowed_back_jumps": self.allowed_back_jumps,
            "back_jump_limits": self.back_jump_limits,
        }


class SchemaError(Exception):
    """schema 校验失败。message 直接回显给调用方。"""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


class YamlParseError(Exception):
    """YAML 解析失败（区别于 schema 错误）。"""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


# ---- 校验 ----

def _resolve_hook(enforced_by: str, plugin_root: Path | None, work_dir: Path | None) -> Path | None:
    """解析 hook 路径，依次尝试 plugin_root、work_dir 下的几个常见位置。

    路径策略（按优先级）：
      1. plugin_root / enforced_by        （drive 自带 hook）
      2. work_dir / enforced_by          （项目本地 .claude/hooks/xxx）
      3. work_dir / .claude/hooks / enforced_by
      4. work_dir / .cosight/hooks / enforced_by   （兼容 cosight 风格）

    返回第一个存在的路径；都不存在返回 None。
    """
    if plugin_root is not None:
        p = plugin_root / enforced_by
        if p.is_file():
            return p
    if work_dir is not None:
        for prefix in (Path("."), Path(".claude/hooks"), Path(".cosight/hooks")):
            p = work_dir / prefix / enforced_by
            if p.is_file():
                return p
    return None


def _parse_gate(
    raw: Any,
    phase_label: str,
    plugin_root: Path | None,
    work_dir: Path | None = None,
    *,
    mode: str = "phase",
) -> Gate:
    """解析 gate 声明。

    enforced_by 处理（mode-aware）：
      - phase 模式：必填，指向真实存在的 hook 文件
      - dag 模式：可选（dag_scheduler 自己管 gate-human 等节点的强制逻辑）

    enforced_by 路径解析顺序：先 plugin_root（drive 自带），再 work_dir 下
    几种常见位置（项目本地 hook）。两者都找不到则拒绝。
    """
    if not isinstance(raw, dict):
        raise SchemaError(f"{phase_label}.gate 必须是 mapping", got=type(raw).__name__)

    gate_type = str(raw.get("type", "")).strip()
    if not gate_type:
        raise SchemaError(f"{phase_label}.gate 缺少 type", valid=sorted(GATE_TYPES))
    if gate_type not in GATE_TYPES:
        raise SchemaError(
            f"{phase_label}.gate.type 未知: {gate_type!r}", valid=sorted(GATE_TYPES)
        )

    enforced_by = str(raw.get("enforced_by", "")).strip()
    if not enforced_by and mode == "phase":
        # phase 模式：必须 hook 强制
        raise SchemaError(
            f"{phase_label}.gate 缺少 enforced_by —— gate 必须声明由哪个 hook 强制，"
            f"否则无法保证不被跳过",
            gate_type=gate_type,
        )
    if enforced_by:
        hook_path = _resolve_hook(enforced_by, plugin_root, work_dir)
        if hook_path is None:
            raise SchemaError(
                f"{phase_label}.gate.enforced_by 指向的 hook 不存在: {enforced_by}",
                hint="先确认 hook 路径，再确认 plugin_root（drive 安装根）或 work_dir（项目根）正确",
                enforced_by=enforced_by,
            )

    skip_when_raw = raw.get("skip_when", [])
    if skip_when_raw is None:
        skip_when_raw = []
    if not isinstance(skip_when_raw, list):
        raise SchemaError(f"{phase_label}.gate.skip_when 必须是列表")

    on_revise = raw.get("on_revise")
    return Gate(
        type=gate_type,
        enforced_by=enforced_by,
        skip_when=tuple(str(s) for s in skip_when_raw),
        on_revise=str(on_revise) if on_revise else None,
    )


_EXPECTED_STATE_KEYS: frozenset[str] = frozenset({"required", "optional"})


def _parse_expected_state(raw: Any, phase_label: str) -> ExpectedState:
    """解析 expected_state 声明。

    形状在此校验（拼错的键名当场拒绝，不留到运行时才发现），字段内容不校验 ——
    agent 是否真上报了这些字段由 orchestrator 判定，本层只承载声明。
    """
    if not isinstance(raw, dict):
        raise SchemaError(
            f"{phase_label}.expected_state 必须是 mapping", got=type(raw).__name__
        )

    unknown = set(raw) - _EXPECTED_STATE_KEYS
    if unknown:
        raise SchemaError(
            f"{phase_label}.expected_state 含未知字段: {sorted(unknown)}",
            valid=sorted(_EXPECTED_STATE_KEYS),
        )

    buckets: dict[str, tuple[str, ...]] = {}
    for key in sorted(_EXPECTED_STATE_KEYS):
        value = raw.get(key, [])
        if value is None:
            value = []
        if not isinstance(value, list):
            raise SchemaError(
                f"{phase_label}.expected_state.{key} 必须是列表",
                got=type(value).__name__,
            )
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise SchemaError(
                    f"{phase_label}.expected_state.{key} 的元素必须是非空字符串",
                    got=repr(item),
                )
        buckets[key] = tuple(item.strip() for item in value)

    return ExpectedState(required=buckets["required"], optional=buckets["optional"])


def _parse_phase(
    raw: Any, idx: int, plugin_root: Path | None, work_dir: Path | None = None
) -> Phase:
    """解析一个 phase 声明。必填: name, stage。"""
    if not isinstance(raw, dict):
        raise SchemaError(f"phases[{idx}] 必须是 mapping", got=type(raw).__name__)

    name = str(raw.get("name", "")).strip()
    stage = str(raw.get("stage", "")).strip()
    if not name:
        raise SchemaError(f"phases[{idx}] 缺少 name")
    if not stage:
        raise SchemaError(f"phases[{idx}] 缺少 stage", name=name)

    if stage == "start":
        raise SchemaError(
            f"phases[{idx}]: stage='start' 已废弃（自 v2.3.0）。"
            f"start 阶段由 drive 内部自动调用 startup skill，"
            f"不应出现在 workflow.yaml 中。请从配置中删除此阶段。",
            name=name,
        )

    agent = raw.get("agent")
    description = str(raw.get("description", "")).strip()

    gate_raw = raw.get("gate")
    gate = _parse_gate(gate_raw, f"phases[{idx}]", plugin_root, work_dir) if gate_raw else None

    mode = raw.get("mode")
    if mode and mode not in EXEC_MODES:
        raise SchemaError(
            f"phases[{idx}].mode 未知: {mode!r}", valid=sorted(EXEC_MODES), name=name
        )

    expected_state_raw = raw.get("expected_state")
    expected_state = (
        _parse_expected_state(expected_state_raw, f"phases[{idx}]")
        if expected_state_raw is not None
        else None
    )

    wave_barrier = bool(raw.get("wave_barrier", False))
    skip_git = bool(raw.get("skip_git", False))
    verdict_required = bool(raw.get("verdict_required", False))
    terminal_stage = bool(raw.get("terminal_stage", False))

    return Phase(
        name=name,
        stage=stage,
        agent=str(agent) if agent else None,
        description=description,
        gate=gate,
        mode=str(mode) if mode else None,
        wave_barrier=wave_barrier,
        expected_state=expected_state,
        skip_git=skip_git,
        verdict_required=verdict_required,
        terminal_stage=terminal_stage,
    )


def _parse_agent(
    raw: Any,
    idx: int,
    plugin_root: Path | None,
    work_dir: Path | None,
    *,
    mode: str = "dag",
) -> AgentSpec:
    """解析 DAG 模式 workflow.yaml 中单个 agent 声明。

    必填：id, agent。
    """
    if not isinstance(raw, dict):
        raise SchemaError(f"agents[{idx}] 必须是 mapping", got=type(raw).__name__)

    # id 必填
    aid = str(raw.get("id", "")).strip()
    if not aid:
        raise SchemaError(f"agents[{idx}] 缺少 id")

    # agent 必填（支持 4 种地址形式）
    agent_ref = str(raw.get("agent", "")).strip()
    if not agent_ref:
        raise SchemaError(f"agents[{idx}] 缺少 agent", id=aid)

    # depends_on 可选（list[str]）
    deps_raw = raw.get("depends_on", [])
    if deps_raw is None:
        deps_raw = []
    if not isinstance(deps_raw, list):
        raise SchemaError(f"agents[{idx}].depends_on 必须是 list", id=aid)
    depends_on = tuple(str(d).strip() for d in deps_raw if str(d).strip())

    description = str(raw.get("description", "")).strip()

    # gate 可选（与 phase 复用 Gate 数据类）
    gate_raw = raw.get("gate")
    gate = _parse_gate(gate_raw, f"agents[{idx}]", plugin_root, work_dir, mode=mode) if gate_raw else None

    # mode 可选
    mode = raw.get("mode")
    if mode and mode not in EXEC_MODES:
        raise SchemaError(
            f"agents[{idx}].mode 未知: {mode!r}", valid=sorted(EXEC_MODES), id=aid
        )

    skip_git = bool(raw.get("skip_git", False))
    verdict_required = bool(raw.get("verdict_required", False))
    terminal = bool(raw.get("terminal", False))

    # verdict_required 只能挂在 terminal agent 上
    if verdict_required and not terminal:
        raise SchemaError(
            f"agents[{idx}] verdict_required=true 但 terminal=false；"
            f"verdict_required 仅 terminal agent 可设（Q8 决策）",
            id=aid,
        )

    expected_state_raw = raw.get("expected_state")
    expected_state = (
        _parse_expected_state(expected_state_raw, f"agents[{idx}]")
        if expected_state_raw is not None
        else None
    )

    return AgentSpec(
        id=aid,
        agent=agent_ref,
        depends_on=depends_on,
        description=description,
        gate=gate,
        mode=str(mode) if mode else None,
        skip_git=skip_git,
        verdict_required=verdict_required,
        terminal=terminal,
        expected_state=expected_state,
    )


def _parse_orchestration(raw: Any) -> dict[str, Any]:
    """解析 orchestration 块（Q16 决策：缺省时由调用方注入默认值）。

    合法字段：
      - max_concurrent_agents: int（默认 16）
      - wave_dispatch: "barrier" | "fire_and_forget"（默认 barrier）
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SchemaError("orchestration 必须是 mapping")

    result: dict[str, Any] = {}

    mc_raw = raw.get("max_concurrent_agents", 16)
    if not isinstance(mc_raw, int) or mc_raw < 1:
        raise SchemaError(
            "orchestration.max_concurrent_agents 必须是 ≥1 的整数",
            got=mc_raw,
        )
    result["max_concurrent_agents"] = mc_raw

    wd_raw = raw.get("wave_dispatch", "barrier")
    if wd_raw not in ("barrier", "fire_and_forget"):
        raise SchemaError(
            "orchestration.wave_dispatch 必须是 'barrier' 或 'fire_and_forget'",
            got=wd_raw,
        )
    result["wave_dispatch"] = wd_raw

    return result


def _apply_orchestration_defaults(orch: dict[str, Any]) -> dict[str, Any]:
    """Q16 决策：orchestration 缺省时注入默认值（浅合并）。"""
    defaults = {
        "max_concurrent_agents": 16,
        "wave_dispatch": "barrier",
    }
    return {**defaults, **orch}


def _validate_dag_topology(agents: tuple[AgentSpec, ...]) -> None:
    """校验 DAG 拓扑结构。

    检查项：
      - 所有 depends_on 引用必须存在（Q14 fail-closed）
      - 至少一个 terminal agent
      - id 不能重复（_parse_agent 已检查，这里 double-check）
    """
    if not agents:
        raise SchemaError("agents 列表为空；DAG 必须至少有一个 agent")

    ids = {a.id for a in agents}

    # depends_on 必须指向已定义的 id
    for a in agents:
        for dep in a.depends_on:
            if dep not in ids:
                raise SchemaError(
                    f"agent {a.id!r} 依赖未知 agent {dep!r}",
                    agent_id=a.id,
                    unknown_dep=dep,
                    defined_agents=sorted(ids),
                )

    # 至少一个 terminal
    terminals = [a for a in agents if a.terminal]
    if not terminals:
        raise SchemaError(
            "DAG 必须至少有一个 terminal=true 的 agent",
            hint="terminal agent 是 workflow 终点，配合 verdict_required 决定完成",
        )


def _parse_dag_workflow(
    raw: dict[str, Any],
    plugin_root: Path | None,
    work_dir: Path | None,
) -> tuple[tuple[AgentSpec, ...], dict[str, Any], dict[str, list[str]], dict[str, int], dict[str, list[str]]]:
    """解析 DAG 模式 workflow 主体。

    Returns:
        (agents, orchestration, skip_agents)
    """
    # 1. 解析 agents
    agents_raw = raw.get("agents", [])
    if not isinstance(agents_raw, list):
        raise SchemaError("agents 必须是列表")
    if not agents_raw:
        raise SchemaError("agents 列表为空；DAG 模式必须有 agents")

    agents_list = []
    seen_ids: set[str] = set()
    for i, a in enumerate(agents_raw):
        agent = _parse_agent(a, i, plugin_root, work_dir, mode="dag")
        if agent.id in seen_ids:
            raise SchemaError(
                f"agent id 重复: {agent.id!r}",
                agent_id=agent.id,
                index=i,
            )
        seen_ids.add(agent.id)
        agents_list.append(agent)
    agents = tuple(agents_list)

    # 2. 校验拓扑
    _validate_dag_topology(agents)

    # 3. 解析 orchestration（缺省时注入默认值）
    orch_raw = raw.get("orchestration")
    orchestration = _apply_orchestration_defaults(_parse_orchestration(orch_raw))

    ids = {a.id for a in agents}

    # 4. 解析 complexity_rules.skip_agents
    skip_agents: dict[str, list[str]] = {}
    complexity = raw.get("complexity_rules", {})
    if isinstance(complexity, dict):
        for tier, rule in complexity.items():
            if not isinstance(rule, dict):
                continue
            sa = rule.get("skip_agents", [])
            if sa:
                if not isinstance(sa, list):
                    raise SchemaError(
                        f"complexity_rules.{tier}.skip_agents 必须是列表",
                        tier=tier,
                    )
                # 校验 skip_agents 引用存在
                for ag in sa:
                    if ag not in ids:
                        raise SchemaError(
                            f"complexity_rules.{tier}.skip_agents 引用未知 agent: {ag!r}",
                            tier=tier,
                            defined_agents=sorted(ids),
                        )
                skip_agents[tier] = list(sa)

    return agents, orchestration, skip_agents


def _infer_valid_transitions(phases: tuple[Phase, ...], allowed_back_jumps: dict[str, list[str]]) -> dict[str, list[str]]:
    """从 phases 序列 + allowed_back_jumps 推断合法的状态转换表。

    规则：
    1. 前向转换：stage[i] → stage[i+1]（按 phases 顺序）
    2. 后向跳转：stage[i] → allowed_back_jumps[stage[i]] 中的任一目标

    返回: {from_stage: [to_stage1, to_stage2, ...]}
    """
    transitions: dict[str, list[str]] = {}
    stages = [p.stage for p in phases]

    for i, stage in enumerate(stages):
        allowed = []

        # 前向转换：到下一个 stage
        if i + 1 < len(stages):
            allowed.append(stages[i + 1])

        # 后向跳转
        if stage in allowed_back_jumps:
            for target in allowed_back_jumps[stage]:
                if target in stages and target not in allowed:
                    allowed.append(target)

        transitions[stage] = allowed

    return transitions


def _validate_phase_order(phases: tuple[Phase, ...], allowed_back_jumps: dict[str, list[str]]) -> None:
    """校验 phases 序列的合法性。

    - 禁止 start 阶段（start 由 drive 内部调用 startup skill，不应出现在 workflow.yaml 中）
    - stage 名称不能重复
    - allowed_back_jumps 中的目标必须存在于 phases 中
    - 后向跳转的目标必须在当前 stage 之前（不能前向跳）
    """
    if not phases:
        raise SchemaError("phases 不能为空")

    stages = [p.stage for p in phases]
    stage_indices = {s: i for i, s in enumerate(stages)}

    # 检查重复
    if len(stages) != len(stage_indices):
        duplicates = [s for s in stages if stages.count(s) > 1]
        raise SchemaError(
            f"phases 中 stage 名称重复: {duplicates}",
            stages=stages,
        )

    # 校验 allowed_back_jumps
    for from_stage, targets in allowed_back_jumps.items():
        if from_stage not in stage_indices:
            raise SchemaError(
                f"allowed_back_jumps 中的源 stage 不存在: {from_stage!r}",
                defined_stages=stages,
            )

        from_idx = stage_indices[from_stage]
        for target in targets:
            if target not in stage_indices:
                raise SchemaError(
                    f"allowed_back_jumps[{from_stage!r}] 中的目标 stage 不存在: {target!r}",
                    defined_stages=stages,
                )
            target_idx = stage_indices[target]
            if target_idx >= from_idx:
                raise SchemaError(
                    f"allowed_back_jumps[{from_stage!r}] 指向的目标 {target!r} "
                    f"不在当前 stage 之前（索引 {target_idx} >= {from_idx}）",
                    hint="后向跳转只能跳到之前的 stage",
                )

    # 校验 terminal_stage：最多一个，且必须在末尾
    terminals = [i for i, p in enumerate(phases) if p.terminal_stage]
    if len(terminals) > 1:
        raise SchemaError(
            f"terminal_stage 只能有一个，当前有 {len(terminals)} 个",
            stages=[phases[i].stage for i in terminals],
        )
    if terminals and terminals[0] != len(phases) - 1:
        raise SchemaError(
            f"terminal_stage 必须是最后一个 phase，"
            f"当前标在 {phases[terminals[0]].stage!r}，其后还有 phase",
        )

    # 用户可以自由定义 stage 名称和顺序


def _parse_complexity_rules(
    raw: Any,
    known_stages: set[str],
    *,
    known_agents: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """解析 complexity_rules 映射。

    key 必须是合法的 tier。
    跳过字段按 mode 区分（Q9 决策）：
      - phase 模式：skip_phases 引用 stage 名
      - DAG 模式：skip_agents 引用 agent id（known_agents 参数提供）

    evaluate_levels 两 mode 通用。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SchemaError("complexity_rules 必须是 mapping")

    if known_agents is None:
        known_agents = set()

    result = {}
    for tier_str, rule_val in raw.items():
        tier = str(tier_str).strip()
        if tier not in COMPLEXITY_TIERS:
            raise SchemaError(
                f"complexity_rules 中未知 tier: {tier!r}", valid=sorted(COMPLEXITY_TIERS)
            )
        if not isinstance(rule_val, dict):
            raise SchemaError(f"complexity_rules[{tier!r}] 必须是 mapping")

        # 只接受 skip_phases / skip_agents / evaluate_levels 三个字段
        unknown_fields = set(rule_val) - {"skip_phases", "skip_agents", "evaluate_levels"}
        if unknown_fields:
            raise SchemaError(
                f"complexity_rules[{tier!r}] 含未知字段: {sorted(unknown_fields)}",
                hint="只允许 skip_phases（phase 模式）/ skip_agents（DAG 模式）/ evaluate_levels",
            )

        # mode 错配检查
        if "skip_phases" in rule_val and known_agents:
            raise SchemaError(
                f"complexity_rules[{tier!r}] 在 DAG 模式下用了 skip_phases；"
                f"应改用 skip_agents（Q9 决策）",
                tier=tier,
            )
        if "skip_agents" in rule_val and not known_agents:
            raise SchemaError(
                f"complexity_rules[{tier!r}] 在 phase 模式下用了 skip_agents；"
                f"应改用 skip_phases（Q9 决策）",
                tier=tier,
            )

        tier_rule = {}

        # 校验 skip_phases 引用的 stage 必须存在（phase 模式）
        if "skip_phases" in rule_val:
            skips = rule_val["skip_phases"] or []
            if not isinstance(skips, list):
                raise SchemaError(f"complexity_rules[{tier!r}].skip_phases 必须是列表")
            for s in skips:
                if str(s) not in known_stages:
                    raise SchemaError(
                        f"complexity_rules[{tier!r}].skip_phases 引用了未定义的 stage: {s!r}",
                        defined_stages=sorted(known_stages),
                    )
            tier_rule["skip_phases"] = [str(s) for s in skips]

        # 校验 skip_agents 引用的 agent 必须存在（DAG 模式）
        if "skip_agents" in rule_val:
            sa = rule_val["skip_agents"] or []
            if not isinstance(sa, list):
                raise SchemaError(f"complexity_rules[{tier!r}].skip_agents 必须是列表")
            for a in sa:
                if str(a) not in known_agents:
                    raise SchemaError(
                        f"complexity_rules[{tier!r}].skip_agents 引用了未定义的 agent: {a!r}",
                        defined_agents=sorted(known_agents),
                    )
            tier_rule["skip_agents"] = [str(a) for a in sa]

        # 校验 evaluate_levels 必须是合法值
        if "evaluate_levels" in rule_val:
            levels = rule_val["evaluate_levels"] or []
            if not isinstance(levels, list):
                raise SchemaError(f"complexity_rules[{tier!r}].evaluate_levels 必须是列表")
            for lv in levels:
                if str(lv) not in EVAL_LEVELS:
                    raise SchemaError(
                        f"complexity_rules[{tier!r}].evaluate_levels 含非法值: {lv!r}",
                        valid=sorted(EVAL_LEVELS),
                    )
            tier_rule["evaluate_levels"] = [str(lv) for lv in levels]

        result[tier] = tier_rule
    return result


def _parse_allowed_back_jumps(raw: Any) -> dict[str, list[str]]:
    """解析 allowed_back_jumps 映射。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SchemaError("allowed_back_jumps 必须是 mapping")

    result = {}
    for from_stage, targets in raw.items():
        if not isinstance(targets, list):
            raise SchemaError(f"allowed_back_jumps[{from_stage!r}] 必须是列表")
        result[str(from_stage)] = [str(t) for t in targets]
    return result


def _parse_back_jump_limits(raw: Any) -> dict[str, int]:
    """解析 back_jump_limits 映射。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SchemaError("back_jump_limits 必须是 mapping")

    result = {}
    for stage, limit in raw.items():
        if not isinstance(limit, int) or limit < 0:
            raise SchemaError(
                f"back_jump_limits[{stage!r}] 必须是非负整数",
                got=limit,
            )
        result[str(stage)] = limit
    return result


def _parse_workflow_yaml(
    doc: dict[str, Any],
    plugin_root: Path | None,
    work_dir: Path | None,
    source: str = "user-defined",
) -> Workflow:
    """从 yaml 文档解析 Workflow 对象。

    mode 分支（v2.3.0+）：
      - "dag"   → 解析 agents/orchestration，phases 字段忽略
      - "phase" → 解析 phases/allowed_back_jumps（默认；Q15）
      - 未设 mode → 默认 "phase" + 警告"建议显式标注"（Q15）
    """
    # mode 检测（缺省 phase + 警告建议显式标注）
    mode = str(doc.get("mode", "phase")).strip() or "phase"
    if mode not in ("phase", "dag"):
        raise SchemaError(
            f"workflow.yaml mode 必须是 'phase' 或 'dag'",
            got=mode,
        )

    # 扫描 agent name（两个 mode 都需要）
    project_agents: set[str] = set()
    plugin_agents: set[str] = set()

    if work_dir:
        project_agents = _scan_agent_names(work_dir / ".claude" / "agents")
    if plugin_root:
        plugin_agents = _scan_agent_names(plugin_root / "agents")

    # DAG 模式分支
    if mode == "dag":
        agents, orchestration, skip_agents = _parse_dag_workflow(
            doc, plugin_root, work_dir
        )

        # 校验所有 agent 引用（fail-closed：未知引用直接拒绝）
        for agent in agents:
            is_valid, error_msg = _validate_agent_ref(agent.agent, project_agents, plugin_agents)
            if not is_valid:
                raise SchemaError(
                    f"agents[{agent.id}].agent 引用无效: {error_msg}",
                    agent=agent.agent,
                    agent_id=agent.id,
                )

        # complexity_rules 兼容：把 skip_agents 转成原格式
        agent_ids = {a.id for a in agents}
        complexity_rules = _parse_complexity_rules(
            doc.get("complexity_rules"), set(), known_agents=agent_ids
        )
        # merge skip_agents 到 complexity_rules[tier].skip_agents
        for tier, sa_list in skip_agents.items():
            if tier in complexity_rules:
                complexity_rules[tier]["skip_agents"] = sa_list
            else:
                complexity_rules[tier] = {"skip_agents": sa_list}

        return Workflow(
            source=source,
            mode="dag",
            phases=(),
            agents=agents,
            orchestration=orchestration,
            complexity_rules=complexity_rules,
        )

    # phase 模式
    phases_raw = doc.get("phases", [])
    if not isinstance(phases_raw, list):
        raise SchemaError("phases 必须是列表")

    phases_list = []
    for i, p in enumerate(phases_raw):
        phases_list.append(_parse_phase(p, i, plugin_root, work_dir))
    phases = tuple(phases_list)

    # 校验所有 agent 引用
    for phase in phases:
        if phase.agent:
            is_valid, error_msg = _validate_agent_ref(phase.agent, project_agents, plugin_agents)
            if not is_valid:
                raise SchemaError(
                    f"phases[{phase.name}].agent 引用无效: {error_msg}",
                    agent=phase.agent,
                    phase=phase.name,
                )

    known_stages = {p.stage for p in phases}
    complexity_rules = _parse_complexity_rules(doc.get("complexity_rules"), known_stages)
    allowed_back_jumps = _parse_allowed_back_jumps(doc.get("allowed_back_jumps"))
    back_jump_limits = _parse_back_jump_limits(doc.get("back_jump_limits"))

    # 校验 phases 序列和后向跳转
    _validate_phase_order(phases, allowed_back_jumps)

    return Workflow(
        source=source,
        mode="phase",
        phases=phases,
        complexity_rules=complexity_rules,
        allowed_back_jumps=allowed_back_jumps,
        back_jump_limits=back_jump_limits,
    )


def _load_workflow_from_file(work_dir: Path, plugin_root: Path | None) -> Workflow:
    """从 work_dir 中的 workflow.yaml / workflow.yml 加载 Workflow。

    不存在则返回内置默认 5-stage。yaml 解析失败或 schema 非法一律 raise。
    """
    yaml_path = None
    is_builtin = False

    for name in WORKFLOW_FILENAMES:
        candidate = work_dir / name
        if candidate.is_file():
            yaml_path = candidate
            break

    if yaml_path is None:
        # 无 workflow.yaml → 使用内置默认配置文件
        builtin_workflow_path = Path(__file__).parent / "workflow.yaml"
        if not builtin_workflow_path.exists():
            raise SchemaError(
                f"内置 workflow.yaml 不存在: {builtin_workflow_path}",
                hint="这是 drive 的打包问题，请报告 bug",
            )
        yaml_path = builtin_workflow_path
        is_builtin = True

    try:
        with yaml_path.open("r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise YamlParseError(
            f"workflow.yaml 解析失败: {e}", path=str(yaml_path)
        ) from e
    except Exception as e:
        raise SchemaError(
            f"读取 workflow.yaml 失败: {e}", path=str(yaml_path)
        ) from e

    if not isinstance(doc, dict):
        raise SchemaError(
            f"workflow.yaml 顶层必须是 mapping", got=type(doc).__name__, path=str(yaml_path)
        )

    source = "plugin-default" if is_builtin else "user-defined"
    return _parse_workflow_yaml(doc, plugin_root, work_dir, source=source)


def load_workflow(work_dir: Path | str, plugin_root: Path | None = None) -> Envelope:
    """公开 API：加载 workflow.yaml 并返回 Envelope。

    Args:
        work_dir: 项目根目录（寻找 workflow.yaml 的起点）
        plugin_root: 插件根目录（用于解析 gate.enforced_by 相对路径）

    Returns:
        Envelope: 成功时 ok=True, data=workflow 字典；失败时 ok=False, reason=...
    """
    work_dir_path = Path(work_dir)
    if not work_dir_path.is_dir():
        return Envelope.fail(
            REASON_INVALID_ARG,
            message=f"work_dir 不存在或不是目录: {work_dir_path}",
            work_dir=str(work_dir_path),
        )
    try:
        workflow = _load_workflow_from_file(work_dir_path, plugin_root)
        data = workflow.to_dict()
        # workflow_file 字段应该在 data 里（测试期望）
        work_path = Path(work_dir)
        if (work_path / "workflow.yaml").exists():
            data["workflow_file"] = str(work_path / "workflow.yaml")
        elif (work_path / "workflow.yml").exists():
            data["workflow_file"] = str(work_path / "workflow.yml")
        else:
            # 使用内置的 workflow.yaml
            data["workflow_file"] = str(Path(__file__).parent / "workflow.yaml")
        return Envelope(ok=True, data=data)
    except YamlParseError as e:
        return Envelope.fail(REASON_JSON_DECODE_ERROR, message=str(e), **e.details)
    except SchemaError as e:
        return Envelope.fail(REASON_SCHEMA_INVALID, message=str(e), **e.details)
    except Exception as e:
        return Envelope.fail(REASON_JSON_DECODE_ERROR, message=f"Unexpected error: {e}")


# ---- CLI ----

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        required=True,
        help="工作目录（包含 workflow.yaml 的项目根）",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="仅校验，不输出模型（exit 0 = 合法，exit 1 = 非法）",
    )
    parser.add_argument(
        "--plugin-root",
        type=Path,
        help="plugin 根目录（用于校验 gate.enforced_by 指向的 hook 是否存在）",
    )
    args = parser.parse_args()

    work_dir: Path = args.work_dir.resolve()
    plugin_root: Path | None = args.plugin_root.resolve() if args.plugin_root else None

    if not work_dir.is_dir():
        env = Envelope.fail(
            REASON_INVALID_ARG, message=f"work_dir 不存在或不是目录: {work_dir}"
        )
        print(env.to_json(), flush=True)
        sys.exit(env.exit_code())

    try:
        workflow = _load_workflow_from_file(work_dir, plugin_root)
    except YamlParseError as e:
        env = Envelope.fail(REASON_JSON_DECODE_ERROR, message=str(e), **e.details)
        print(env.to_json(), flush=True)
        sys.exit(env.exit_code())
    except SchemaError as e:
        env = Envelope.fail(REASON_SCHEMA_INVALID, message=str(e), **e.details)
        print(env.to_json(), flush=True)
        sys.exit(env.exit_code())
    except Exception as e:
        env = Envelope.fail(REASON_JSON_DECODE_ERROR, message=f"Unexpected error: {e}")
        print(env.to_json(), flush=True)
        sys.exit(env.exit_code())

    if args.validate:
        workflow_yaml_path = None
        for name in WORKFLOW_FILENAMES:
            candidate = work_dir / name
            if candidate.is_file():
                workflow_yaml_path = candidate
                break
        if workflow_yaml_path is None:
            workflow_yaml_path = Path(__file__).parent / "workflow.yaml"
        env = Envelope.ok_envelope(
            source=workflow.source,
            stages=[p.stage for p in workflow.phases],
            workflow_file=str(workflow_yaml_path),
        )
        print(env.to_json(), flush=True)
        sys.exit(0)

    # 输出模型（包含推断的 valid_transitions）
    valid_transitions = _infer_valid_transitions(workflow.phases, workflow.allowed_back_jumps)

    output = {
        **workflow.to_dict(),
        "valid_transitions": valid_transitions,
    }

    env = Envelope.ok_envelope(**output)
    print(env.to_json(), flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()

