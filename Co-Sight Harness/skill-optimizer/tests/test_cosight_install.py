"""Cosight 运行时安装测试。

通过真实子进程跑 `scripts/install.sh --runtime cosight`，用隔离 COSIGHT_HOME + 假 registry
（不依赖真实 ~/.cosight），验证：

- `.cosight/` 组件快照（agents/commands/rules/skills）从顶层生成；
- `.cosight-plugin/` manifest 落盘（marketplace.json 含 skillx、plugin name = skill-optimizer）；
- 三个注册表生成：known_marketplaces / installed_plugins / settings.json(enabledPlugins)；
- 幂等：重复执行不破坏、不重复叠加。

不复用 DEST 模式（那是 claude 专属），直接设 COSIGHT_HOME 到 tmp 隔离目录。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

MKT = "skillx"
PLUG = "skill-optimizer"


def _read_json(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _run_install(cosight_home: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(cosight_home / "home"),
        "COSIGHT_HOME": str(cosight_home),
    }
    # --no-pip：避免触发真实 `pip install`（联网装 matplotlib 等慢/挂起），测试只管布局与注册。
    return subprocess.run(
        ["bash", str(SCRIPTS / "install.sh"), "--runtime", "cosight", "--no-pip"],
        cwd=str(SCRIPTS),
        env=env,
        capture_output=True,
        text=True,
    )


def test_cosight_install_generates_snapshot(tmp_path):
    home = tmp_path / "cosight"
    res = _run_install(home)
    assert res.returncode == 0, f"install 失败:\n{res.stdout}\n{res.stderr}"

    mkt_dir = home / "plugins" / "marketplaces" / MKT
    # .cosight 快照：agents/commands/rules/skills 各至少有文件
    cosight_agents = mkt_dir / ".cosight" / "agents"
    assert cosight_agents.is_dir()
    assert list(cosight_agents.glob("*.md")), ".cosight/agents 应有 agent md"
    assert (mkt_dir / ".cosight" / "commands").is_dir()
    assert (mkt_dir / ".cosight" / "skills").is_dir()
    assert (mkt_dir / ".cosight" / "rules").is_dir()

    # Cosight 快照里的 agent 数量应与顶层一致（同一份内容）
    top_agents = mkt_dir / "agents"
    assert {p.name for p in cosight_agents.glob("*.md")} == {p.name for p in top_agents.glob("*.md")}


def test_cosight_install_writes_manifests(tmp_path):
    home = tmp_path / "cosight"
    _run_install(home)
    mkt_dir = home / "plugins" / "marketplaces" / MKT

    mp = _read_json(mkt_dir / ".cosight-plugin" / "marketplace.json")
    assert mp and mp.get("name") == MKT
    assert any(pl.get("name") == PLUG for pl in mp.get("plugins", []))

    # 顶层 .claude-plugin 仍保留（未被 Cosight 安装覆盖）
    assert _read_json(mkt_dir / ".claude-plugin" / "marketplace.json")["name"] == "skillx"


def test_cosight_install_registers_registries(tmp_path):
    home = tmp_path / "cosight"
    _run_install(home)

    plugins = home / "plugins"
    km = _read_json(plugins / "known_marketplaces.json")
    assert km and MKT in km
    assert km[MKT]["installLocation"]
    assert km[MKT]["source"]["path"]

    inst = _read_json(plugins / "installed_plugins.json")
    assert inst and inst.get("plugins")
    entry = inst["plugins"].get(f"{PLUG}@{MKT}")
    assert entry and entry[0]["installPath"] and entry[0]["version"]

    settings = _read_json(home / "settings.json")
    assert settings and settings.get("enabledPlugins", {}).get(f"{PLUG}@{MKT}") is True


def test_cosight_install_idempotent(tmp_path):
    home = tmp_path / "cosight"
    assert _run_install(home).returncode == 0
    assert _run_install(home).returncode == 0

    # 快照不因重装而异常（列表仍完整）；注册表仍单条且 enabled。
    mkt_dir = home / "plugins" / "marketplaces" / MKT
    assert list((mkt_dir / ".cosight" / "agents").glob("*.md"))
    settings = _read_json(home / "settings.json")
    assert settings["enabledPlugins"].get(f"{PLUG}@{MKT}") is True
    inst = _read_json(home / "plugins" / "installed_plugins.json")
    assert len(inst["plugins"][f"{PLUG}@{MKT}"]) == 1