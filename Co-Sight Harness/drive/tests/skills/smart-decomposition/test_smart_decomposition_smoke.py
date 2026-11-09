"""Smoke test for smart-decomposition."""
from __future__ import annotations

import re
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[3] / "skills" / "smart-decomposition" / "SKILL.md"


def test_skill_md_has_required_frontmatter():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    m = re.search(r"^name:\s*(\S+)\s*$", text, re.M)
    assert m and m.group(1) == "smart-decomposition"
    assert re.search(r"^description:\s*\S", text, re.M)
    assert re.search(r"^user-invocable:\s*false\b", text, re.M)


def test_skill_mentions_smart_and_decomposition():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "SMART" in text
    assert "分解" in text or "拆" in text
