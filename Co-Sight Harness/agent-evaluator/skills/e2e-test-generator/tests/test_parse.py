#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_parse.py — S0 输入判定、解包安全、锚点定位。"""

import tarfile
import zipfile

import pytest

import config
import parse
from common import GoldevalError


# ============================== 类型判定 ==============================

def test_detect_kind_directory(tmp_path):
    assert parse.detect_kind(tmp_path) == "dir"


def test_detect_kind_rejects_unknown_extension(tmp_path):
    path = tmp_path / "agent.txt"
    path.write_text("x")
    with pytest.raises(GoldevalError, match="不支持的输入格式"):
        parse.detect_kind(path)


def test_detect_kind_rejects_missing_path(tmp_path):
    with pytest.raises(GoldevalError, match="不存在"):
        parse.detect_kind(tmp_path / "nope")


def test_detect_kind_rejects_fake_targz(tmp_path):
    """扩展名声称 tar.gz 但魔数不符：拒绝，防伪装。"""
    path = tmp_path / "fake.tar.gz"
    path.write_text("not really gzip")
    with pytest.raises(GoldevalError, match="魔数不匹配"):
        parse.detect_kind(path)


def test_detect_kind_rejects_fake_zip(tmp_path):
    path = tmp_path / "fake.zip"
    path.write_text("not really zip")
    with pytest.raises(GoldevalError, match="魔数不匹配"):
        parse.detect_kind(path)


def test_detect_kind_accepts_real_targz(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "COSIGHT.md").write_text("# x")
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src / "COSIGHT.md", arcname="COSIGHT.md")
    assert parse.detect_kind(archive) == "targz"


def test_detect_kind_rejects_oversized_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_ARCHIVE_BYTES", 4)
    path = tmp_path / "big.zip"
    path.write_bytes(config.ZIP_MAGIC + b"0" * 100)
    with pytest.raises(GoldevalError, match="超过体积上限"):
        parse.detect_kind(path)


# ============================== 解包安全 ==============================

def test_zip_slip_is_rejected(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../pwned.txt", "x")
    with pytest.raises(GoldevalError, match="非法成员路径"):
        parse.unpack(archive, "zip", tmp_path / "work")


def test_absolute_path_member_is_rejected(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("/etc/pwned", "x")
    with pytest.raises(GoldevalError, match="非法成员路径"):
        parse.unpack(archive, "zip", tmp_path / "work")


def test_too_many_files_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_EXTRACTED_FILES", 2)
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for i in range(5):
            zf.writestr(f"f{i}.txt", "x")
    with pytest.raises(GoldevalError, match="文件数超过上限"):
        parse.unpack(archive, "zip", tmp_path / "work")


def test_zip_unpack_roundtrip(tmp_path):
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("agent/COSIGHT.md", "# hi")
    root = parse.unpack(archive, "zip", tmp_path / "work")
    assert (root / "agent" / "COSIGHT.md").read_text() == "# hi"


# ============================== 锚点定位 ==============================

def test_locate_root_shallow_finds_anchor(tmp_path):
    (tmp_path / config.flavor_of("cosight")["anchor"]).write_text("# x")
    root, _, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and root == tmp_path


def test_locate_root_finds_anchor_in_subdirectory(tmp_path):
    """用户指向的是工程根之上的一层：锚点在子目录里，应当深挖到它。"""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / config.flavor_of("cosight")["anchor"]).write_text("# x")
    root, _, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and root == sub


def test_locate_root_deep_finds_unique_anchor(tmp_path):
    """深挖不受深度限制：解包后多层的锚点也能定位到。"""
    deep = tmp_path / "runtime" / "output" / "agents" / "v1"
    deep.mkdir(parents=True)
    (deep / config.flavor_of("cosight")["anchor"]).write_text("# x")
    root, _, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and root == deep


def test_locate_root_prefers_root_level_anchor(tmp_path):
    """根层有锚点就不再往下找。"""
    (tmp_path / config.flavor_of("cosight")["anchor"]).write_text("# root")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / config.flavor_of("cosight")["anchor"]).write_text("# sub")
    root, _, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and root == tmp_path


def test_locate_root_errors_on_multiple_anchors(tmp_path):
    """多个锚点无法确定扫哪个，必须报错而非猜。"""
    for name in ("a", "b"):
        sub = tmp_path / name
        sub.mkdir()
        (sub / config.flavor_of("cosight")["anchor"]).write_text("# x")
    with pytest.raises(GoldevalError, match="多个"):
        parse.locate_root(tmp_path)


def test_locate_root_without_any_anchor_falls_back(tmp_path):
    (tmp_path / "README.md").write_text("x")
    root, _, found, _, _, _ = parse.locate_root(tmp_path)
    assert not found and root == tmp_path


def test_top_level_listing_marks_directories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.md").write_text("x")
    listing = parse.top_level_listing(tmp_path)
    assert "sub/" in listing and "file.md" in listing


# ============================== build_asset 集成 ==============================

def test_build_asset_on_directory(tmp_path):
    (tmp_path / config.flavor_of("cosight")["anchor"]).write_text("# x")
    (tmp_path / "a.py").write_text("print(1)")
    asset, _ = parse.build_asset(str(tmp_path), tmp_path / "work")
    assert asset["input_kind"] == "dir"
    assert asset["anchor_found"] is True
    assert asset["warnings"] == []
    assert len(asset["root_sha256"]) == 64


def test_build_asset_without_anchor_warns_and_falls_back(tmp_path):
    (tmp_path / "README.md").write_text("x")
    asset, _ = parse.build_asset(str(tmp_path), tmp_path / "work")
    assert asset["anchor_found"] is False
    assert any("未找到任何工程锚点" in w for w in asset["warnings"])


def test_build_asset_on_tarball_locates_deep_anchor(tmp_path):
    src = tmp_path / "pack" / "runtime" / "agents" / "v1"
    src.mkdir(parents=True)
    (src / config.flavor_of("cosight")["anchor"]).write_text("# x")
    (src / "engine.py").write_text("print(1)")
    archive = tmp_path / "pack.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src, arcname="runtime/agents/v1")

    asset, _ = parse.build_asset(str(archive), tmp_path / "work")
    assert asset["input_kind"] == "targz"
    assert asset["anchor_found"] is True
    assert asset["root"].endswith("runtime/agents/v1")


# ============================== 解包后 slug 推导 ==============================

def test_slugify_keeps_cjk():
    """中文 agent 名不能被清空成 fallback。"""
    from common import slugify
    assert slugify("明文密码智能体") == "明文密码智能体"


def test_slugify_falls_back_when_only_punctuation():
    from common import slugify
    assert slugify("!!!") == "agent"


def test_agent_slug_uses_parent_when_leaf_is_version():
    from common import slug_from_path
    assert slug_from_path("/a/b/plaintext-password-checker/v1") == \
        "plaintext-password-checker"


def test_agent_slug_strips_archive_suffix():
    from common import slug_from_path
    assert slug_from_path("/a/明文密码智能体.tar.gz") == "明文密码智能体"


def test_agent_slug_keeps_meaningful_leaf():
    from common import slug_from_path
    assert slug_from_path("/a/b/reviewer") == "reviewer"


# ============================== 产出命名（project_id 优先） ==============================

def test_naming_slug_prefers_project_id():
    from common import naming_slug
    # 目录名是 runtime（--agent 指向上层），工程自报名是 project_id
    profile = {"agent_slug": "runtime", "project_id": "plaintext-password-checker",
               "root": "/x/runtime/output/agents/plaintext-password-checker/v1"}
    assert naming_slug(profile) == "plaintext-password-checker"


def test_naming_slug_falls_back_when_project_id_empty():
    """CLAUDE.md 类工程没有元数据表，project_id 为空 → 回退路径推导。"""
    from common import naming_slug
    assert naming_slug({"agent_slug": "my-agent", "project_id": ""}) == "my-agent"
    assert naming_slug({"agent_slug": "my-agent"}) == "my-agent"


def test_naming_slug_falls_back_when_project_id_all_punctuation():
    """project_id 只由符号组成时不能产出空前缀（否则 data_id 会以 _ 开头）。"""
    from common import naming_slug
    assert naming_slug({"agent_slug": "my-agent", "project_id": "***"}) == "my-agent"


def test_naming_slug_slugifies_unsafe_project_id():
    """project_id 会变成 data_id 前缀，而 data_id 被 runner 用作目录名。"""
    from common import naming_slug
    assert naming_slug({"agent_slug": "x", "project_id": "My Agent/v2"}) == "my-agent-v2"


# ============================== flavor 判定 ==============================

def make_claude_agent(root):
    """构造一个合法的 Claude 类工程：CLAUDE.md + 自带的 .claude/ 目录。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("# x", encoding="utf-8")
    (root / ".claude").mkdir(exist_ok=True)
    return root


def test_claude_anchor_yields_claude_flavor(tmp_path):
    make_claude_agent(tmp_path)
    root, flavor, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and root == tmp_path and flavor == "claude"


def test_cosight_anchor_yields_cosight_flavor(tmp_path):
    (tmp_path / "COSIGHT.md").write_text("# x")
    _, flavor, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and flavor == "cosight"


def test_claude_without_dot_claude_is_not_recognized(tmp_path):
    """只有 CLAUDE.md、没有 .claude/ 的目录：不算 Claude 类工程，回退。"""
    (tmp_path / "CLAUDE.md").write_text("# x")
    root, flavor, found, _, _, _ = parse.locate_root(tmp_path)
    assert not found
    assert root == tmp_path and flavor == config.FALLBACK_FLAVOR


def test_claude_without_dot_claude_warns_in_asset(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# x")
    asset, _ = parse.build_asset(str(tmp_path), tmp_path / "work")
    assert asset["anchor_found"] is False
    assert any("未找到任何工程锚点" in w for w in asset["warnings"])
    # 类型没识别出来时不能报「Claude 类」，那会与"锚点未找到"自相矛盾
    assert asset["flavor_label"] == config.DEFAULT_LABEL


def test_deep_claude_without_dot_claude_skipped(tmp_path):
    """深挖时同样要求 .claude/：光有 CLAUDE.md 不算命中。"""
    deep = tmp_path / "agents" / "reviewer"
    deep.mkdir(parents=True)
    (deep / "CLAUDE.md").write_text("# x")
    root, flavor, found, _, _, _ = parse.locate_root(tmp_path)
    assert not found and root == tmp_path


def test_both_anchors_prefer_cosight_and_report_shadowed(tmp_path):
    """同目录两种锚点并存：取 COSIGHT，并把被忽略的记入 shadowed。"""
    (tmp_path / "COSIGHT.md").write_text("# c")
    make_claude_agent(tmp_path)
    root, flavor, found, _, shadowed, _ = parse.locate_root(tmp_path)
    assert found and flavor == "cosight"
    assert [f["id"] for f in shadowed] == ["claude"]


def test_both_anchors_warns_in_asset(tmp_path):
    (tmp_path / "COSIGHT.md").write_text("# c")
    make_claude_agent(tmp_path)
    asset, _ = parse.build_asset(str(tmp_path), tmp_path / "work")
    assert asset["flavor"] == "cosight"
    assert any("同时存在多个锚点" in w for w in asset["warnings"])


def test_claude_deep_anchor_located(tmp_path):
    deep = make_claude_agent(tmp_path / "agents" / "reviewer")
    root, flavor, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and root == deep and flavor == "claude"


def test_mixed_flavors_at_different_depths_errors(tmp_path):
    """两个不同工程各有自己的锚点：无法确定扫哪个，必须报错。"""
    a = tmp_path / "a"
    a.mkdir()
    (a / "COSIGHT.md").write_text("# c")
    make_claude_agent(tmp_path / "b")
    with pytest.raises(GoldevalError, match="多个工程锚点"):
        parse.locate_root(tmp_path)


def test_lone_claude_md_does_not_block_cosight_elsewhere(tmp_path):
    """散落的 CLAUDE.md（无 .claude/）不参与竞争，COSIGHT 工程照常命中。"""
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "COSIGHT.md").write_text("# c")
    stray = tmp_path / "notes"
    stray.mkdir()
    (stray / "CLAUDE.md").write_text("# 随手写的笔记")

    root, flavor, found, _, _, _ = parse.locate_root(tmp_path)
    assert found and flavor == "cosight"
    assert root == agent


def test_no_anchor_falls_back_to_fallback_flavor(tmp_path):
    (tmp_path / "README.md").write_text("x")
    _, flavor, found, _, _, _ = parse.locate_root(tmp_path)
    assert not found and flavor == config.FALLBACK_FLAVOR


def test_build_asset_records_flavor_fields(tmp_path):
    make_claude_agent(tmp_path)
    asset, _ = parse.build_asset(str(tmp_path), tmp_path / "work")
    assert asset["flavor"] == "claude"
    assert asset["flavor_label"] == "Claude 类"
    assert asset["anchor_file"].endswith("CLAUDE.md")
