"""tests/agents/test_reviewer_agents.py — 两个 reviewer agent 的契约测试。

reviewer 是只读审查者：它们能读代码、报 finding，但不能改文件、不能写 state、
不能派 subagent。这些约束靠 frontmatter 的 tools 白名单兜住，本测试守住该白名单
不被后续改动放宽。

同时守 plugin.json 的 agents[] 注册 —— 该字段是显式清单，漏登记会让
Task(subagent_type="code-reviewer") 直接 spawn 失败。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
REVIEWERS = ("code-reviewer", "security-reviewer")

# reviewer 只读：给了 Write / Edit 就能改自己审的代码，审查失去意义。
ALLOWED_TOOLS = frozenset({"Read", "Grep", "Glob", "Bash"})
FORBIDDEN_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "Task", "NotebookEdit"})


def agent_path(name: str) -> Path:
    return PLUGIN_ROOT / "agents" / f"{name}.md"


def read_frontmatter(path: Path) -> dict:
    """取 markdown 文件的 YAML frontmatter。"""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} 缺 frontmatter 起始分隔符"
    _, fm, _ = text.split("---", 2)
    parsed = yaml.safe_load(fm)
    assert isinstance(parsed, dict), f"{path.name} frontmatter 不是 mapping"
    return parsed


@pytest.mark.parametrize("name", REVIEWERS)
def test_agent_file_exists(name: str):
    assert agent_path(name).is_file(), f"缺 agents/{name}.md"


@pytest.mark.parametrize("name", REVIEWERS)
def test_frontmatter_required_fields(name: str):
    fm = read_frontmatter(agent_path(name))
    assert fm.get("name") == name, f"{name}: frontmatter name 与文件名不一致"
    assert fm.get("description"), f"{name}: description 必填（触发器）"
    assert fm.get("user-invocable") is False, (
        f"{name}: reviewer 由 orchestrator 派，不暴露给用户 /"
    )
    assert isinstance(fm.get("maxTurns"), int), f"{name}: maxTurns 必须是整数"
    assert fm["maxTurns"] > 0, f"{name}: maxTurns 必须为正"


@pytest.mark.parametrize("name", REVIEWERS)
def test_tools_are_read_only(name: str):
    """reviewer 的 tools 只能是只读工具集。"""
    fm = read_frontmatter(agent_path(name))
    tools = fm.get("tools")
    assert isinstance(tools, list), f"{name}: tools 必须是列表"

    declared = set(tools)
    forbidden = declared & FORBIDDEN_TOOLS
    assert not forbidden, (
        f"{name}: 声明了写类工具 {sorted(forbidden)}。reviewer 必须只读 —— "
        f"能改自己审的代码则审查失去意义。"
    )
    unexpected = declared - ALLOWED_TOOLS
    assert not unexpected, (
        f"{name}: 声明了白名单外工具 {sorted(unexpected)}。"
        f"允许集: {sorted(ALLOWED_TOOLS)}"
    )


@pytest.mark.parametrize("name", REVIEWERS)
def test_registered_in_plugin_manifest(name: str):
    """agents[] 是显式清单，不是目录自动发现 —— 漏登记则 spawn 失败。"""
    manifest = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    entries = manifest.get("agents") or []
    assert f"./agents/{name}.md" in entries, (
        f"plugin.json 的 agents[] 缺 ./agents/{name}.md，"
        f"Task(subagent_type={name!r}) 会 spawn 失败。当前: {entries}"
    )


def test_manifest_agents_match_directory():
    """plugin.json 的 agents[] 与 agents/*.md 一一对应，防漏登记或留悬空条目。"""
    manifest = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    declared = {Path(p).stem for p in (manifest.get("agents") or [])}
    on_disk = {p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md")}

    missing = on_disk - declared
    assert not missing, f"agents/ 下有文件未登记进 plugin.json: {sorted(missing)}"

    dangling = declared - on_disk
    assert not dangling, f"plugin.json 登记了不存在的 agent: {sorted(dangling)}"


@pytest.mark.parametrize("name", REVIEWERS)
def test_declares_json_return_contract(name: str):
    """reviewer 必须返回 JSON 给 orchestrator 解析，body 要写明该契约。"""
    body = agent_path(name).read_text(encoding="utf-8")
    assert '"verdict"' in body, f"{name}: 未声明 verdict 字段"
    assert '"findings"' in body, f"{name}: 未声明 findings 字段"
    for value in ("approve", "warning", "block"):
        assert value in body, f"{name}: 未声明 verdict 取值 {value!r}"


@pytest.mark.parametrize("name", REVIEWERS)
def test_declares_zero_findings_is_valid(name: str):
    """零 finding 必须被显式认可 —— 否则 LLM 会编造 finding 证明自己跑过。"""
    body = agent_path(name).read_text(encoding="utf-8")
    assert "零 finding" in body, (
        f"{name}: 未声明零 finding 合法。缺这条会诱发编造 finding。"
    )
