"""插件契约测试：清单字段、组件文件存在性、路径引用、残留 Cosight 机制。

复刻 drive/tests/test_plugin_contract.py 思路，适配 skill-optimizer 的组件布局，
并在 Phase 2 运行时解耦后加一条"无残留 Cosight 机制"防回归检查。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = PLUGIN_ROOT / ".claude-plugin" / "marketplace.json"

RUNTIME_DIRS = [
    "agents",
    "commands",
    "skills",
    "scripts",
    "references",
    "framework_configs",
    "config",
    "docs",
    "rules",
]


def test_plugin_manifest_required_fields():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for field in ("name", "displayName", "version", "description"):
        assert field in m and m[field], f"manifest 缺 {field}"
    assert m["name"] == "skill-optimizer"
    assert re.match(r"^\d+\.\d+\.\d+$", m["version"]), m["version"]


def test_agent_files_exist_and_unique():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for rel in m.get("agents", []):
        p = PLUGIN_ROOT / rel
        assert p.is_file(), f"agent 文件不存在: {rel}"
        text = p.read_text(encoding="utf-8")
        assert text.startswith("---"), f"agent 缺 frontmatter: {rel}"
        fm = _frontmatter(text)
        assert fm.get("name"), f"agent frontmatter 缺 name: {rel}"
        assert fm.get("description"), f"agent frontmatter 缺 description: {rel}"
        assert fm["name"] not in seen, f"agent name 重复: {fm['name']}"
        seen.add(fm["name"])


def test_command_files_exist():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for rel in m.get("commands", []):
        p = PLUGIN_ROOT / rel
        assert p.is_file(), f"command 文件不存在: {rel}"
        text = p.read_text(encoding="utf-8")
        assert text.startswith("---"), f"command 缺 frontmatter: {rel}"


def test_skills_dirs_exist():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for rel in m.get("skills", []):
        d = PLUGIN_ROOT / rel
        assert d.is_dir(), f"skill 目录不存在: {rel}"
        assert (d / "SKILL.md").is_file(), f"skill 缺 SKILL.md: {rel}"


def test_cosight_mechanism_confined_to_runtime_backends():
    """Cosight 支持限定在运行时后端（agent_runner.py / install.sh）与文档。

    移植版重新加回 Cosight 支持后，`cosight -p` 调用与 `.cosight` 快照布局允许出现，
    但必须限定在明确承载该机制的文件内 —— 不允许散落到无关的运行时组件
    （如 command/agent/skill 定义、metrics、scorer 等业务逻辑）。此处维护一份
    Cosight-runtime 白名单，防止重蹈「Cosight 机制残留全树」覆辙。
    """
    patterns = {
        "cosight -p spawn": r'["\']cosight["\']\s*,\s*["\']-p["\']',
        ".cosight path": r"(?<!config)\.cosight[/\\\"']",
    }
    # 允许出现 Cosight 机制的文件（相对插件根）。其余文件命中即视为残留。
    allowlist_files = {
        Path("scripts/agent_runner.py"),   # CosightRunner：cosight -p + env 注入
        Path("scripts/install.sh"),        # install_cosight：生成 .cosight 快照 + 注册
        Path("scripts/tools.py"),          # _find_agents_dir / $COSIGHT_PLUGIN_ROOT
        Path("scripts/orchestrators/create_pipeline.py"),  # agent-cli 冒烟探活
        Path("tests/test_agent_runner.py"),
        Path("tests/test_cosight_install.py"),
        Path("docs/runtime-portability.md"),
        Path("README.md"),
    }
    # 顶层目录/文件自身允许含 dot-cosight（RUNTIME_ITEMS 同步）、带 .docker 等无关忽略
    allowlist_dirs = {Path("docs")}
    files: list[Path] = []
    for d in RUNTIME_DIRS:
        if (PLUGIN_ROOT / d).is_dir():
            files.extend((PLUGIN_ROOT / d).rglob("*"))
    files = [f for f in files if f.is_file() and f.suffix in (".py", ".md", ".sh", ".yaml", ".yml", ".json")]
    found: list[str] = []
    for f in files:
        rel = f.relative_to(PLUGIN_ROOT)
        if rel in allowlist_files or any(rel.is_relative_to(d) for d in allowlist_dirs):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pat in patterns.items():
            if re.search(pat, text):
                found.append(f"{label} @ {rel}")
    assert not found, "Cosight 机制超出运行时后端白名单:\n" + "\n".join(sorted(set(found)))


def test_marketplace_has_plugin():
    mp = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert mp.get("name") == "skillx"
    names = [pl.get("name") for pl in mp.get("plugins", [])]
    assert "skill-optimizer" in names


def _frontmatter(text: str) -> dict:
    """用 PyYAML（声明依赖）解析 frontmatter，正确处理 `description: |` 块字面量。"""
    try:
        import yaml  # PyYAML==6.0.2（脚本/requirements.txt 声明）
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("缺少 PyYAML，请先 `pip install -r scripts/requirements.txt`") from e
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    assert m, "frontmatter 界定符不完整"
    fm = yaml.safe_load(m.group(1)) or {}
    assert isinstance(fm, dict), f"frontmatter 不是映射: {fm!r}"
    return fm