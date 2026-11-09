"""workflow-builder 校验 workflow.yaml 的辅助脚本。

校验项（与 PROP-20260805-002 §4.2 + PROP-20260806-001 一致）：
  1. phase 名称不重复
  2. 每个 phase 有 name / stage / agent
  3. 至少一个 terminal_stage，且在最后一个
  4. 没有 stage: start
  5. gate.enforced_by 必须指向真实存在的 hook 文件
  6. allowed_back_jumps 引用的 stage 都存在，且目标必须在前
  7. complexity_rules 的 skip_phases / evaluate_levels 合法
  8. agent 引用是合法 scoped 地址（drive:<name> / 裸名 / 内置类型），且指向真实存在的 agent
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import yaml


REQUIRED_PHASE_FIELDS = ("name", "stage", "agent")
RESERVED_STAGES = ("start",)
ALLOWED_COMPLEXITY_TIERS = ("trivial", "standard", "complex")
ALLOWED_EVAL_LEVELS = ("L0", "L1", "L2")
ALLOWED_GATE_TYPES = ("human_review", "artifact_check", "input_check")
BUILTIN_AGENT_TYPES = frozenset({
    "general-purpose", "Explore", "Plan", "claude",
    "statusline-setup", "claude-code-guide",
})


def _scan_agent_names(agents_dir: Path) -> set[str]:
    """扫描 agents_dir 下所有 .md 的 name: frontmatter。

    文件名、目录结构无关，只看 frontmatter 的 name: 字段。
    """
    names: set[str] = set()
    if not agents_dir.exists():
        return names
    for md in agents_dir.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1])
        except Exception:
            continue
        if isinstance(fm, dict) and "name" in fm:
            name = str(fm["name"]).strip()
            if name:
                names.add(name)
    return names


def _validate_agent_ref(
    agent: str,
    project_agents: set[str],
    plugin_agents: set[str],
    global_agents: set[str],
) -> tuple[bool, str | None]:
    """校验单个 agent 引用。

    四种合法形式（drive-2.3+）：
    - @xxx          → @-mention，让 Claude Code Agent tool 自行解析（不校验）
    - drive:<name>  → 查 plugin agents
    - 裸名          → 查 project agents → fallback global agents
    - 内置类型      → 白名单放行
    """
    if not agent:
        return False, "agent 不能为空"
    if agent in BUILTIN_AGENT_TYPES:
        return True, None
    # @-mention：让运行时 Agent tool 解析，不在校验阶段 fail-closed
    if agent.startswith("@"):
        bare = agent[1:]
        if not bare:
            return False, "@-mention 后缺少 agent 名称"
        return True, None
    if agent.startswith("drive:"):
        bare = agent[6:]
        if not bare:
            return False, "drive: 前缀后缺少 agent 名称"
        if bare not in plugin_agents:
            return False, f"drive 插件中不存在 agent: {bare!r}（可用: {sorted(plugin_agents)}）"
        return True, None
    if agent in project_agents:
        return True, None
    if global_agents and agent in global_agents:
        return True, None
    available = sorted(project_agents | global_agents)
    return False, f"项目中不存在 agent: {agent!r}（可用: {available}）"


def validate(
    workflow_yaml_path: Path,
    plugin_root: Path | None = None,
    work_dir: Path | None = None,
    global_agents_dir: Path | None = None,
) -> dict:
    """校验 workflow.yaml，返回 Envelope 格式 dict。

    global_agents_dir：用户全局 agent 目录，裸名 agent 引用解析不到 project 时 fallback 这里。
    """
    if not workflow_yaml_path.is_file():
        return _fail("schema_invalid", f"文件不存在: {workflow_yaml_path}")

    try:
        doc = yaml.safe_load(workflow_yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return _fail("yaml_decode_error", f"YAML 解析失败: {exc}")

    if not isinstance(doc, dict):
        return _fail("schema_invalid", "顶层必须是 mapping")

    # mode 分支（drive-2.3）：mode=dag 走 DAG 校验，phase 走原逻辑
    mode = str(doc.get("mode", "phase")).strip() or "phase"
    if mode not in ("phase", "dag"):
        return _fail("schema_invalid", f"mode 必须是 'phase' 或 'dag'，收到 {mode!r}")

    if mode == "dag":
        return _validate_dag(doc, work_dir, plugin_root, global_agents_dir)

    phases = doc.get("phases", [])
    if not isinstance(phases, list) or not phases:
        return _fail("schema_invalid", "phases 必须是非空列表")

    # 扫描可用 agent
    project_agents: set[str] = set()
    plugin_agents: set[str] = set()
    global_agents: set[str] = set()
    if work_dir:
        project_agents = _scan_agent_names(work_dir / ".claude" / "agents")
    if plugin_root:
        plugin_agents = _scan_agent_names(plugin_root / "agents")
    if global_agents_dir:
        global_agents = _scan_agent_names(global_agents_dir)

    seen_stages: set[str] = set()
    stage_positions: dict[str, int] = {}
    errors: list[str] = []

    for idx, phase in enumerate(phases):
        if not isinstance(phase, dict):
            errors.append(f"phases[{idx}] 必须是 mapping")
            continue

        for field in REQUIRED_PHASE_FIELDS:
            if field not in phase or not str(phase[field]).strip():
                errors.append(f"phases[{idx}] 缺少 {field}")

        agent = str(phase.get("agent", "")).strip()
        if agent:
            is_valid, err_msg = _validate_agent_ref(agent, project_agents, plugin_agents, global_agents)
            if not is_valid:
                errors.append(
                    f"phases[{idx}] (name={phase.get('name', '?')}) "
                    f"agent 引用无效: {err_msg}"
                )

        stage = str(phase.get("stage", "")).strip()

        if stage in RESERVED_STAGES:
            errors.append(
                f"phases[{idx}]: stage='{stage}' 已废弃。"
                f"start 阶段由 drive 内部自动调用，不应出现在 workflow.yaml"
            )

        if stage:
            if stage in seen_stages:
                errors.append(f"phases 中 stage 名称重复: {stage!r}")
            seen_stages.add(stage)
            stage_positions[stage] = idx

        gate = phase.get("gate")
        if gate is not None:
            if not isinstance(gate, dict):
                errors.append(f"phases[{idx}].gate 必须是 mapping")
            else:
                gate_type = gate.get("type")
                if gate_type is not None and gate_type not in ALLOWED_GATE_TYPES:
                    errors.append(
                        f"phases[{idx}].gate.type 未知: {gate_type!r}"
                    )
                if not gate.get("enforced_by"):
                    errors.append(
                        f"phases[{idx}].gate 缺少 enforced_by"
                    )
                elif plugin_root and not (plugin_root / gate["enforced_by"]).is_file():
                    errors.append(
                        f"phases[{idx}].gate.enforced_by 指向的 hook 不存在: {gate['enforced_by']}"
                    )

        mode = phase.get("mode")
        if mode is not None and mode not in ("code", "analysis"):
            errors.append(f"phases[{idx}].mode 未知: {mode!r}")

    terminals = [p for p in phases if isinstance(p, dict) and p.get("terminal_stage")]
    if len(terminals) > 1:
        errors.append(f"terminal_stage 只能有一个，当前有 {len(terminals)} 个")
    elif terminals and phases.index(terminals[-1]) != len(phases) - 1:
        errors.append("terminal_stage 必须是最后一个 phase")

    back_jumps = doc.get("allowed_back_jumps", {})
    if back_jumps:
        if not isinstance(back_jumps, dict):
            errors.append("allowed_back_jumps 必须是 mapping")
        else:
            for from_stage, targets in back_jumps.items():
                if from_stage not in stage_positions:
                    errors.append(
                        f"allowed_back_jumps 中的源 stage 不存在: {from_stage!r}"
                    )
                if not isinstance(targets, list):
                    errors.append(
                        f"allowed_back_jumps[{from_stage!r}] 必须是列表"
                    )
                    continue
                from_idx = stage_positions.get(from_stage, -1)
                for target in targets:
                    if target not in stage_positions:
                        errors.append(
                            f"allowed_back_jumps[{from_stage!r}] 中的目标 stage 不存在: {target!r}"
                        )
                    elif stage_positions[target] >= from_idx and from_idx >= 0:
                        errors.append(
                            f"allowed_back_jumps[{from_stage!r}] 指向的目标 {target!r} "
                            f"不在当前 stage 之前"
                        )

    complexity = doc.get("complexity_rules", {})
    if complexity:
        if not isinstance(complexity, dict):
            errors.append("complexity_rules 必须是 mapping")
        else:
            for tier, rules in complexity.items():
                if tier not in ALLOWED_COMPLEXITY_TIERS:
                    errors.append(f"complexity_rules 未知 tier: {tier!r}")
                    continue
                if not isinstance(rules, dict):
                    errors.append(f"complexity_rules[{tier!r}] 必须是 mapping")
                    continue
                unknown_fields = set(rules) - {"skip_phases", "evaluate_levels"}
                if unknown_fields:
                    errors.append(
                        f"complexity_rules[{tier!r}] 含未知字段: {sorted(unknown_fields)}"
                    )
                if "skip_phases" in rules:
                    if not isinstance(rules["skip_phases"], list):
                        errors.append(
                            f"complexity_rules[{tier!r}].skip_phases 必须是列表"
                        )
                    else:
                        for s in rules["skip_phases"]:
                            if s not in stage_positions:
                                errors.append(
                                    f"complexity_rules[{tier!r}].skip_phases 引用了未定义的 stage: {s!r}"
                                )
                if "evaluate_levels" in rules:
                    if not isinstance(rules["evaluate_levels"], list):
                        errors.append(
                            f"complexity_rules[{tier!r}].evaluate_levels 必须是列表"
                        )
                    else:
                        for lv in rules["evaluate_levels"]:
                            if lv not in ALLOWED_EVAL_LEVELS:
                                errors.append(
                                    f"complexity_rules[{tier!r}].evaluate_levels 含非法值: {lv!r}"
                                )

    if errors:
        return _fail("schema_invalid", "; ".join(errors), errors=errors)

    return {
        "ok": True,
        "data": {"phases": phases, "complexity_rules": complexity},
        "details": {},
    }


def _validate_dag(
    doc: dict,
    work_dir: Path | None,
    plugin_root: Path | None,
    global_agents_dir: Path | None,
) -> dict:
    """DAG 模式 workflow.yaml 校验（drive-2.3）。

    校验项：
      - agents 列表非空
      - 每个 agent 有 id、agent、depends_on
      - agent 引用是合法 4 种地址形式之一
      - depends_on 引用解析得到目标 id
      - 至少一个 terminal: true
      - 至少一个 verdict_required 在 terminal 上
      - complexity_rules 的 skip_agents 引用合法
    """
    agents = doc.get("agents", [])
    if not isinstance(agents, list) or not agents:
        return _fail("schema_invalid", "agents 必须是非空列表")

    # 扫描可用 agent
    project_agents: set[str] = set()
    plugin_agents: set[str] = set()
    global_agents: set[str] = set()
    if work_dir:
        project_agents = _scan_agent_names(work_dir / ".claude" / "agents")
    if plugin_root:
        plugin_agents = _scan_agent_names(plugin_root / "agents")
    if global_agents_dir:
        global_agents = _scan_agent_names(global_agents_dir)

    seen_ids: set[str] = set()
    terminal_count = 0
    verdict_required_count = 0
    errors: list[str] = []

    for idx, agent in enumerate(agents):
        if not isinstance(agent, dict):
            errors.append(f"agents[{idx}] 必须是 mapping")
            continue

        for field in ("id", "agent"):
            if field not in agent or not str(agent[field]).strip():
                errors.append(f"agents[{idx}] 缺少 {field}")

        aid = str(agent.get("id", "")).strip()
        if aid:
            if aid in seen_ids:
                errors.append(f"agents id 重复: {aid!r}")
            seen_ids.add(aid)

        agent_ref = str(agent.get("agent", "")).strip()
        if agent_ref:
            is_valid, err_msg = _validate_agent_ref(
                agent_ref, project_agents, plugin_agents, global_agents
            )
            if not is_valid:
                errors.append(
                    f"agents[{idx}] (id={aid or '?'}) agent 引用无效: {err_msg}"
                )

        deps = agent.get("depends_on", [])
        if deps is None:
            deps = []
        if not isinstance(deps, list):
            errors.append(f"agents[{idx}].depends_on 必须是 list")
        else:
            for d in deps:
                if str(d) not in seen_ids and d not in [a.get("id") for a in agents[:idx]]:
                    errors.append(
                        f"agents[{idx}] (id={aid}) depends_on 引用未知 id: {d!r}"
                    )

        if agent.get("terminal"):
            terminal_count += 1
            if agent.get("verdict_required"):
                verdict_required_count += 1
            else:
                errors.append(
                    f"agents[{idx}] (id={aid}) terminal=true 但 verdict_required 未设"
                )
        elif agent.get("verdict_required"):
            errors.append(
                f"agents[{idx}] (id={aid}) verdict_required=true 但 terminal=false（Q8 决策）"
            )

    if terminal_count == 0:
        errors.append("DAG 必须至少有一个 terminal=true 的 agent")

    complexity = doc.get("complexity_rules", {})
    if isinstance(complexity, dict):
        for tier, rule in complexity.items():
            if not isinstance(rule, dict):
                continue
            sa = rule.get("skip_agents", [])
            if not sa:
                continue
            if not isinstance(sa, list):
                errors.append(f"complexity_rules.{tier}.skip_agents 必须是列表")
                continue
            for a in sa:
                if a not in seen_ids:
                    errors.append(
                        f"complexity_rules.{tier}.skip_agents 引用未知 id: {a!r}"
                    )

    if errors:
        return _fail("schema_invalid", "workflow.yaml 校验失败", errors=errors)

    return {
        "ok": True,
        "data": {
            "mode": "dag",
            "agent_count": len(agents),
            "terminal_count": terminal_count,
            "verdict_required_count": verdict_required_count,
        },
        "details": {},
    }


def _fail(reason: str, message: str, **details) -> dict:
    return {
        "ok": False,
        "reason": reason,
        "details": {"message": message, **details},
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="校验 workflow.yaml")
    parser.add_argument("workflow_yaml", type=Path, help="workflow.yaml 路径")
    parser.add_argument(
        "--plugin-root", type=Path, default=None,
        help="插件根目录，用于校验 gate.enforced_by 和 drive:* agent 引用",
    )
    parser.add_argument(
        "--work-dir", type=Path, default=None,
        help="项目根目录，用于校验裸名 agent 引用（从 .claude/agents/ 读 name:）",
    )
    parser.add_argument(
        "--global-agents-dir", type=Path, default=None,
        help="用户全局 agent 目录，裸名 agent 引用解析不到 project 时 fallback 这里",
    )
    args = parser.parse_args()

    plugin_root = args.plugin_root.resolve() if args.plugin_root else None
    work_dir = args.work_dir.resolve() if args.work_dir else None
    global_agents_dir = args.global_agents_dir.resolve() if args.global_agents_dir else None
    result = validate(args.workflow_yaml.resolve(), plugin_root, work_dir, global_agents_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())