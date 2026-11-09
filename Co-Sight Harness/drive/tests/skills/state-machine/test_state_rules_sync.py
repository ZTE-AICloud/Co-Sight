"""流转表的两份副本必须一致。

state-machine skill 持权威定义；hooks 持一份用于不变量强制的独立副本
（hooks 不能依赖目录外的模块，否则强制器自身会因加载失败而失效）。
两份分开是有意的，但内容漂移会导致"skill 允许、hook 拦截"的死锁，故此校验。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SKILL_RULES = PLUGIN_ROOT / "skills" / "state-machine" / "scripts" / "state_rules.py"
HOOK_RULES = PLUGIN_ROOT / "hooks" / "state_rules.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SKILL = _load(SKILL_RULES, "_rules_skill")
HOOK = _load(HOOK_RULES, "_rules_hook")


def test_both_copies_exist():
    assert SKILL_RULES.is_file()
    assert HOOK_RULES.is_file()


def test_stages_match():
    assert SKILL.STAGES == HOOK.STAGES


def test_transition_tables_match():
    assert SKILL.VALID_TRANSITIONS == HOOK.VALID_TRANSITIONS


def test_verdicts_match_across_all_stage_pairs():
    """逐对穷举，保证两份实现对每种流转给出相同判定。"""
    stages = list(SKILL.STAGES) + ["bogus"]
    for src in stages:
        for dst in stages:
            skill_ok, _ = SKILL.validate_transition(src, dst)
            hook_ok, _ = HOOK.validate_transition(src, dst)
            assert skill_ok == hook_ok, f"判定不一致: {src} → {dst}"


def test_skill_md_documents_the_same_transitions():
    """SKILL.md 是流转语义的说明源，不能与可执行表脱节。"""
    body = (SKILL_RULES.parent.parent / "SKILL.md").read_text(encoding="utf-8")
    for stage in SKILL.STAGES:
        assert stage in body, f"SKILL.md 未提及阶段 {stage}"


def test_rollback_paths_are_declared():
    """execute / evaluate 可回退到 plan —— 这是有意设计，不可被误删。"""
    assert "plan" in SKILL.VALID_TRANSITIONS["execute"]
    assert "plan" in SKILL.VALID_TRANSITIONS["evaluate"]
