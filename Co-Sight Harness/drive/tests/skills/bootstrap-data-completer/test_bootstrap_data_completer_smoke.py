"""Smoke test for bootstrap-data-completer."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILL_PATH = Path(__file__).resolve().parents[3] / "skills" / "bootstrap-data-completer" / "SKILL.md"


def test_skill_md_has_required_frontmatter():
    """frontmatter 含 name + description，user-invocable = true。"""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    m = re.search(r"^name:\s*(\S+)\s*$", text, re.M)
    assert m and m.group(1) == "bootstrap-data-completer"
    assert re.search(r"^description:\s*\S", text, re.M)
    assert re.search(r"^user-invocable:\s*true\b", text, re.M)


def test_skill_mentions_bootstrap_concept():
    """skill 主题是 bootstrap 阶段数据补全，应出现相关术语。"""
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "bootstrap" in text.lower() or "补全" in text or "diagnose" in text.lower()
