"""tools.py 的插件根定位与 agents 目录解析测试（含 Cosight `.cosight/agents` 形态）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tools


def _make_layout(root: Path, *, top_agents: bool = False, cosight_agents: bool = False):
    if top_agents:
        (root / "agents").mkdir(parents=True, exist_ok=True)
        (root / "agents" / "proposal-agent.md").write_text(
            "---\nname: proposal-agent\ndescription: d\n---\nbody\n", encoding="utf-8"
        )
    if cosight_agents:
        (root / ".cosight" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cosight" / "agents" / "proposal-agent.md").write_text(
            "---\nname: proposal-agent\ndescription: d\n---\nbody\n", encoding="utf-8"
        )
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    return root


def test_find_agents_dir_finds_top_agents(tmp_path, monkeypatch):
    root = _make_layout(tmp_path, top_agents=True)
    for env in ("CLAUDE_PLUGIN_ROOT", "COSIGHT_PLUGIN_ROOT"):
        monkeypatch.delenv(env, raising=False)
    start = root / "scripts"
    assert tools._find_agents_dir(start) == root


def test_find_agents_dir_finds_cosight_subdir(tmp_path, monkeypatch):
    """只有 .cosight/agents（无顶层 agents）时，插件根仍应被识别。"""
    root = _make_layout(tmp_path, cosight_agents=True)
    for env in ("CLAUDE_PLUGIN_ROOT", "COSIGHT_PLUGIN_ROOT"):
        monkeypatch.delenv(env, raising=False)
    assert tools._find_agents_dir(root / "scripts") == root


def test_find_agents_dir_respects_env(tmp_path, monkeypatch):
    """宿主注入 env（COSIGHT_PLUGIN_ROOT）优先于向上探测。"""
    root = _make_layout(tmp_path, cosight_agents=True)
    monkeypatch.setenv("COSIGHT_PLUGIN_ROOT", str(root))
    assert tools._find_agents_dir() == root


def test_plugins_agents_dir_prefers_top(tmp_path):
    """顶层 agents/ 优先；缺顶层时才用 .cosight/agents。"""
    both = _make_layout(tmp_path / "both", top_agents=True, cosight_agents=True)
    assert tools._plugins_agents_dir(both) == both / "agents"

    cosight_only = _make_layout(tmp_path / "c", cosight_agents=True)
    assert tools._plugins_agents_dir(cosight_only) == cosight_only / ".cosight" / "agents"


def test_load_agent_definition_from_cosight_subdir(tmp_path, monkeypatch):
    """Cosight 形态下能经 .cosight/agents 加载 agent 定义。"""
    root = _make_layout(tmp_path, cosight_agents=True)
    monkeypatch.setenv("COSIGHT_PLUGIN_ROOT", str(root))
    found_root = tools._find_agents_dir()
    content = tools._load_agent_definition("proposal-agent", found_root)
    assert "body" in content and "proposal-agent" in content


def test_load_agent_definition_missing_returns_empty(tmp_path, monkeypatch):
    root = _make_layout(tmp_path)
    for env in ("CLAUDE_PLUGIN_ROOT", "COSIGHT_PLUGIN_ROOT"):
        monkeypatch.delenv(env, raising=False)
    assert tools._load_agent_definition("anything", root) == ""