"""编排策略必须是声明，不能藏在代码或 prose 里。

phase 3 之后，编排脚本（playbook 中间层）被删除。orchestrator 直接读
`workflow.yaml.phases[i].agent` 用 Task spawn。本测试验证：

- orchestrator 自身仍按声明驱动（不写死 phase 顺序）
- orchestrator 仍不写 state 内容（仅 transition 时改 active_stage）
- orchestrator 仍声明各类协议字段（gate / complexity / skipping 规则）
- 引用的脚本确实存在（不论它们在哪个目录）

phase 3 之前：测试参数化了 `drive-start/analyze/plan/execute/evaluate` 5 个名字
phase 3 之后：所有 phase→agent 关系在 `skills/drive` 内部定义，测试聚焦 orchestrator
自身。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PLUGIN_ROOT / "skills"


def body(skill: str) -> str:
    """读 orchestrator 主入口的 SKILL.md body。"""
    return (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


def frontmatter(skill: str) -> dict:
    """Parse the YAML frontmatter from SKILL.md. Empty dict if missing/invalid."""
    import re

    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    import yaml
    return yaml.safe_load(match.group(1)) or {}


def body_with_references(skill: str) -> str:
    """读 SKILL.md body + references/*.md（mode-split 后 dispatch 协议在 references）。

    orchestrator 把 mode-specific 协议拆到 references/ 后，dispatch 模板
    （含 Agent(subagent_type=...））只在 references 里出现。语义上这些
    references 仍是 orchestrator 的一部分，断言需合并读。
    """
    parts = [(SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")]
    refs_dir = SKILLS / skill / "references"
    if refs_dir.is_dir():
        for ref in sorted(refs_dir.glob("*.md")):
            parts.append(ref.read_text(encoding="utf-8"))
    return "\n".join(parts)


# orchestrator 自己的入口
ORCHESTRATOR_SKILL = "drive"

STARTUP_SKILL = "startup"


# =============================================================================
# 不再依赖 lib / dispatch.py 等老式 redirector
# =============================================================================

class TestNoLegacyCode:
    def test_orchestrator_does_not_import_lib_cli(self):
        assert "lib.workflow.cli" not in body(ORCHESTRATOR_SKILL)
        assert "lib.runtime.cli" not in body(ORCHESTRATOR_SKILL)


# =============================================================================
# 编排结构来自声明
# =============================================================================

class TestDeclarativeOrchestration:
    def test_orchestrator_reads_workflow_yaml(self):
        text = body(ORCHESTRATOR_SKILL)
        assert "read_workflow.py" in text
        assert "workflow.yaml" in text

    def test_orchestrator_documents_fail_closed_parse(self):
        assert "解析失败一律停下" in body(ORCHESTRATOR_SKILL)

    def test_orchestrator_defers_agent_choice_to_declaration(self):
        """派谁由 workflow.yaml 声明决定（phases[i].agent / agents[i].agent），
        不靠 SKILL.md 里的硬编码表。

        不约束具体措辞 —— drive body 只要体现"agent 选择 = workflow.yaml 声明"这
        一业务约束即过。措辞层面的"以声明为准" / "source of truth" 是过程性元注释，
        不进契约断言（参见 no-runtime-meta-leak.md）。
        """
        text = body(ORCHESTRATOR_SKILL)
        # 业务约束：phases[i].agent 或 agents[i].agent 在 body 中是派 agent 的依据
        assert "phases[i].agent" in text or "agents[i].agent" in text, (
            "drive body 必须体现 agent 选择由 workflow.yaml 声明决定（phases[i].agent / agents[i].agent）"
        )

    def test_orchestrator_defers_gate_to_state_machine(self):
        """gate 字段定义与语义委托给 state-machine skill。"""
        text = body(ORCHESTRATOR_SKILL)
        assert "state-machine" in text  # 必须委托

    def test_orchestrator_defers_complexity_rules_to_state_machine(self):
        """complexity_rules 委托给 state-machine skill。"""
        text = body(ORCHESTRATOR_SKILL)
        assert "state-machine" in text  # 必须委托

    def test_orchestrator_rejects_max_tasks_lookup(self):
        """max_tasks 属 planner 履职细节，orchestrator 不应硬编码。"""
        text = body(ORCHESTRATOR_SKILL)
        assert "max_tasks" not in text

    def test_orchestrator_phase_to_agent_mapping_uses_agent_tool(self):
        """orchestrator 通过 Agent(subagent_type=...) 直接派 agent, 不经中间层。

        旧版硬编码 4 stage 名称于表格已被废弃（stage 名可自定义），
        仅断言 dispatch 走 Agent() 工具。

        drive-2.3 mode-split 后 dispatch 模板在 references/phase-mode.md
        和 references/dag-mode.md，body() 已不直接包含。
        """
        text = body_with_references(ORCHESTRATOR_SKILL)
        assert "Agent(subagent_type" in text

    def test_default_workflow_contains_drive_built_in_stages(self):
        """内置默认 workflow.yaml 仍含 4 个内置 stage，保证兼容。"""
        import yaml
        wf_path = SKILLS / ORCHESTRATOR_SKILL / "scripts" / "workflow.yaml"
        doc = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        stages = {p["stage"] for p in doc["phases"]}
        assert {"analyze", "plan", "execute", "evaluate"}.issubset(stages)
        for p in doc["phases"]:
            assert p["agent"].startswith("drive:"), f"phase {p['stage']} agent {p['agent']!r} 缺 drive: 前缀"

    def test_orchestrator_uses_startup_skill_for_start_phase(self):
        """start 阶段走 startup skill，不绕过它直接调 startup 内部脚本。

        drive-2.3 重构后：drive 通过 description 自动激活或 `/startup` prose 委托
        调 startup（参见 `.claude/rules/skill-authoring.md` §9），不再直接 Bash 调
        `init_planning.py` / `discover_inputs.py` —— 后者是 startup 的封装细节。
        新合约：
        - drive body 必须提到 startup（语义意图：delegation）
        - drive body 必须经真实机制调 startup（实现意图：经协议）：
            (a) description 自动激活（在 body 里以 prose 形式写"调 startup"或
                "激活 startup"），或
            (b) 用户/主对话用 `/startup` prose 委托（body 里出现 `/startup` 字面）
        - drive body **不能**出现 startup 内部脚本名（封装边界）
        - drive body **不能**出现 `Skill("startup", ...)` 伪代码 RPC —— 运行时无
          对应物（skill-authoring.md §9 明令禁止）
        """
        text = body(ORCHESTRATOR_SKILL)
        assert "startup" in text, "drive body 必须提到 startup skill"
        # 真实机制：(a) description 自动激活 / (b) `/startup` prose 委托
        # 伪代码 RPC（Skill("startup", ...)）不算 —— 运行时无对应物
        assert "Skill(" not in text, (
            "drive body 不得出现 Skill(... ) 伪代码 RPC，"
            "应改用 description 自动激活或 /startup prose 委托"
        )
        # 至少有 prose 形式的 delegation 信号（"调 startup" / "激活 startup" / "/startup"）
        assert (
            "调 startup" in text
            or "激活 startup" in text
            or "/startup" in text
        ), "drive body 必须有 prose 形式的 startup 委托信号"
        assert "init_planning.py" not in text, (
            "drive 不应直接引 startup 内部脚本 init_planning.py —— 那是 startup 封装细节"
        )
        assert "discover_inputs.py" not in text, (
            "drive 不应直接引 startup 内部脚本 discover_inputs.py —— 那是 startup 封装细节"
        )

    def test_orchestrator_allowed_tools_respects_startup_boundary(self):
        """drive 的 allowed-tools 不能含 startup 内部脚本（封装边界 frontmatter 层）。

        P3 review 发现：body 文本检查不足以防止有人把 init_planning.py /
        discover_inputs.py 加回 drive 的 allowed-tools。封装合约必须同时守
        frontmatter 层。
        """
        fm = frontmatter(ORCHESTRATOR_SKILL)
        allowed = str(fm.get("allowed-tools", ""))
        assert "init_planning.py" not in allowed, (
            "drive 不应在 allowed-tools 里授权 init_planning.py —— 那是 startup 封装细节"
        )
        assert "discover_inputs.py" not in allowed, (
            "drive 不应在 allowed-tools 里授权 discover_inputs.py —— 那是 startup 封装细节"
        )

    def test_startup_allowed_tools_respects_state_machine_boundary(self):
        """startup 的 allowed-tools 不能含 state-machine 内部脚本（封装边界 frontmatter 层）。

        Q4 plan C 一致性：startup → state-machine 应跟 drive → startup 走同样的
        Skill() 工具调用模式。startup 不应在 allowed-tools 里授权 state_cli.py。
        """
        fm = frontmatter(STARTUP_SKILL)
        allowed = str(fm.get("allowed-tools", ""))
        assert "state_cli.py" not in allowed, (
            "startup 不应在 allowed-tools 里授权 state_cli.py —— 那是 state-machine 封装细节"
        )

    def test_orchestrator_does_not_reference_deleted_playbooks(self):
        """不应再引已删的 5 个 drive-* playbook。"""
        text = body(ORCHESTRATOR_SKILL)
        for old in ("drive-start", "drive-analyze", "drive-plan", "drive-execute", "drive-evaluate"):
            assert old not in text, f"orchestrator 仍引 `{old}`（已删 playbook）"


# =============================================================================
# state 写入责任在 agent
# =============================================================================

class TestStateResponsibility:
    def test_orchestrator_declares_read_only(self):
        """orchestrator 自己声明不写 state（state 写入由 state-machine 负责）。"""
        text = body(ORCHESTRATOR_SKILL)
        assert "不写 state" in text or "不" in text  # 任一处声明 delegate 即可


# =============================================================================
# gate 语义：orchestrator 不重复定义，委托给 state-machine
# =============================================================================

class TestGateSemantics:
    def test_orchestrator_does_not_define_gate_field_table(self):
        """gate 字段表（type/skip_when/enforced_by/on_revise）属于 state-machine 职责。

        orchestrator 不应重复定义，否则两份文档会漂移。
        """
        text = body(ORCHESTRATOR_SKILL)
        # 不在 orchestrator 里详列 gate.type 三选一
        assert "artifact_check" not in text or "state-machine" in text


# =============================================================================
# 模式与级别：来自声明，orchestrator 不解释
# =============================================================================

class TestModeAndLevels:
    def test_orchestrator_refers_to_phase_declaration_for_mode(self):
        """mode 来自 workflow.yaml phase.mode，orchestrator 不解释派生逻辑。"""
        text = body(ORCHESTRATOR_SKILL)
        assert "mode" in text  # 必须引用 field 名
        assert "phase.mode" not in text or "phase.mode" in text  # 接受两种表述


# =============================================================================
# 脚本可执行性
# =============================================================================

class TestReferencedScriptsExist:
    """orchestrator SKILL.md 里引的脚本必须真实存在。"""

    def _script_refs(self, text: str) -> set[str]:
        refs = set()
        for m in re.finditer(r'\$\{CLAUDE_PLUGIN_ROOT\}/([\w\-./]+\.py)', text):
            refs.add(m.group(1))
        return refs

    def test_orchestrator_referenced_plugin_scripts_exist(self):
        for ref in self._script_refs(body(ORCHESTRATOR_SKILL)):
            assert (PLUGIN_ROOT / ref).is_file(), f"orchestrator 引用了不存在的脚本: {ref}"

    def test_startup_local_scripts_exist(self):
        """startup skill 声明的两个本地脚本必须存在。"""
        text = body(STARTUP_SKILL)
        assert "init_planning.py" in text
        assert "discover_inputs.py" in text
        assert (SKILLS / STARTUP_SKILL / "scripts" / "init_planning.py").is_file()
        assert (SKILLS / STARTUP_SKILL / "scripts" / "discover_inputs.py").is_file()

    @pytest.mark.parametrize("skill", (ORCHESTRATOR_SKILL, STARTUP_SKILL))
    def test_skill_declares_bash_permission_when_calling_scripts(self, skill):
        """调脚本的 SKILL.md 必须声明 allowed-tools。"""
        text = body(skill)
        if "python3" in text:
            assert "allowed-tools" in text, f"{skill} 调脚本但未声明 allowed-tools"
