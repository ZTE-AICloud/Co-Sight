#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_freeze_profile.py — S1 收尾：能力点归一、档位判定、0 能力点降级。"""

import pytest

import config
import freeze_profile
from common import GoldevalError


def make_input(**overrides):
    payload = {
        "root": "/tmp/agent",
        "tier_hint": config.TIER_A,
        "flavor": "cosight", "flavor_label": "COSIGHT 类",
        "anchor_file": "COSIGHT.md",
        "manifest": {"meta": {"project_id": "my-agent", "project_name": "我的智能体",
                              "version": "v2"},
                     "capability_boundary": "边界", "positioning": "定位",
                     "quickstart": "用法", "structure_index": {"engine.py": "引擎"}},
        "settings": {"allow": ["Read"], "deny": [], "model_tier": "standard",
                     "constraints": {"scan_mode": "read-only"}},
        "skills": [{"constraints": "三约束", "not_for": "Not for"}],
        "pass_criteria": {"file": ".agent-genesis/work/my-agent/agent-creation/clarified-agent-requirements.yaml", "gwt_count": 1,
                          "gwt_entries": [{"index": 1}], "nonfunctional": "清单"},
        "engine": {"source_file": "engine.py"},
        "demo_code": None,
        "rules": [],
        "excluded": [],
    }
    payload.update(overrides)
    return payload


# ============================== 能力点解析 ==============================

def test_parse_capabilities_keeps_valid_entries():
    answer = {"capabilities": [
        {"id": "C01", "name": "命中", "desc": "d", "evidence": "e"},
        {"id": "C02", "name": "排除", "desc": "d2", "evidence": "e2"},
    ]}
    caps = freeze_profile.parse_capabilities(answer)
    assert [c["id"] for c in caps] == ["C01", "C02"]


def test_parse_capabilities_assigns_ids_when_missing():
    answer = {"capabilities": [{"name": "无 id"}]}
    caps = freeze_profile.parse_capabilities(answer)
    assert caps[0]["id"] == "C01"


def test_parse_capabilities_dedupes_duplicate_ids():
    answer = {"capabilities": [{"id": "C01", "name": "a"}, {"id": "C01", "name": "b"}]}
    caps = freeze_profile.parse_capabilities(answer)
    assert len(caps) == 2
    assert len({c["id"] for c in caps}) == 2


def test_parse_capabilities_skips_entries_without_name():
    answer = {"capabilities": [{"id": "C01", "desc": "无名字"}, {"name": "有名字"}]}
    caps = freeze_profile.parse_capabilities(answer)
    assert len(caps) == 1 and caps[0]["name"] == "有名字"


def test_parse_capabilities_requires_array():
    with pytest.raises(GoldevalError, match="capabilities"):
        freeze_profile.parse_capabilities({"capabilities": "not a list"})


# ============================== 档位判定 ==============================

def test_zero_capabilities_downgrades_to_tier_c_not_abort():
    """共识：0 能力点不中止，降级档 C 并标记。"""
    profile_input = make_input(tier_hint=config.TIER_A)
    profile = freeze_profile.build_profile(profile_input, {"capabilities": []})
    assert profile["tier"] == config.TIER_C
    assert profile["tier_downgraded"] is True
    assert any("降级" in w for w in profile["warnings"])


def test_capabilities_keep_declared_tier():
    profile = freeze_profile.build_profile(
        make_input(), {"tier": "B", "capabilities": [{"id": "C01", "name": "a"}]}
    )
    assert profile["tier"] == config.TIER_B
    assert profile["tier_downgraded"] is False


def test_unknown_tier_falls_back_to_c():
    profile = freeze_profile.build_profile(
        make_input(tier_hint="Z"), {"capabilities": [{"id": "C01", "name": "a"}]}
    )
    assert profile["tier"] == config.TIER_C


def test_tier_hint_used_when_answer_omits_it():
    profile = freeze_profile.build_profile(
        make_input(tier_hint=config.TIER_B),
        {"capabilities": [{"id": "C01", "name": "a"}]},
    )
    assert profile["tier"] == config.TIER_B


# ============================== 画像组装 ==============================

def test_profile_carries_cosight_metadata():
    profile = freeze_profile.build_profile(
        make_input(), {"capabilities": [{"id": "C01", "name": "a"}]}
    )
    assert profile["project_id"] == "my-agent"
    assert profile["project_name"] == "我的智能体"
    assert profile["version"] == "v2"


def test_profile_maps_settings_and_boundaries():
    profile = freeze_profile.build_profile(
        make_input(), {"capabilities": [{"id": "C01", "name": "a"}]}
    )
    assert profile["tools"]["allow"] == ["Read"]
    assert profile["constraints"]["scan_mode"] == "read-only"
    assert profile["boundaries"]["capability_boundary"] == "边界"
    assert profile["boundaries"]["skill_constraints"] == ["三约束"]


def test_profile_carries_gwt_baseline():
    profile = freeze_profile.build_profile(
        make_input(), {"capabilities": [{"id": "C01", "name": "a"}]}
    )
    assert profile["gwt_baseline"]["count"] == 1
    assert len(profile["gwt_baseline"]["entries"]) == 1


def test_profile_warns_when_engine_missing():
    profile = freeze_profile.build_profile(
        make_input(engine=None), {"capabilities": [{"id": "C01", "name": "a"}]}
    )
    assert any("引擎" in w for w in profile["warnings"])


def test_profile_without_engine_has_no_engine_warning_duplication():
    profile = freeze_profile.build_profile(
        make_input(engine=None), {"capabilities": [{"id": "C01", "name": "a"}]}
    )
    assert profile["engine"] is None


# ============================== CLI ==============================

def test_main_requires_profile_input(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        freeze_profile.main(["--work", str(tmp_path)])
    assert exc.value.code == 1
    assert "extract.py" in capsys.readouterr().err


def test_main_requires_merge_answer(tmp_path, capsys):
    from common import write_json
    write_json(tmp_path / "10-profile-input.json", make_input())
    with pytest.raises(SystemExit) as exc:
        freeze_profile.main(["--work", str(tmp_path)])
    assert exc.value.code == 1
    assert "11-merge.answer.json" in capsys.readouterr().err


def test_main_writes_profile(tmp_path):
    from common import read_json, write_json
    write_json(tmp_path / "10-profile-input.json", make_input())
    write_json(tmp_path / "11-merge.answer.json",
               {"capabilities": [{"id": "C01", "name": "命中", "desc": "d"}]})

    assert freeze_profile.main(["--work", str(tmp_path)]) == 0
    profile = read_json(tmp_path / "12-agent-profile.json")
    assert profile["project_id"] == "my-agent"
    assert len(profile["capabilities"]) == 1
