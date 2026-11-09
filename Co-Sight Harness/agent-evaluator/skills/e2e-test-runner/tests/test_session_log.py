#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话日志查找与拷贝的测试。

搜索形态对齐真实 CLI 的落盘布局：
    <projects>/<cwd 编码>/<session_id>.jsonl              主会话
    <projects>/<cwd 编码>/<session_id>/subagents/*.jsonl  子代理
注意主会话是**文件**、子代理是**目录**，两者同名。
"""

from pathlib import Path

import config
from common import copy_session_log, find_session_log
from test_run import write_fake_session_log

SID = "f7078c0b-fddb-4450-8cba-ad8b8cb43395"


# ============================== find_session_log ==============================

def test_find_session_log_empty_id_returns_nothing(tmp_path):
    """空 id 必须短路返回空。

    `rglob("")` 等价于 `rglob("*")`，会把整棵 projects 树都匹配上——一个空串能
    捞回全库每个文件与目录。result.json 解析不出 id 的场合真实存在，所以这个
    守卫是必须的，不是防御性编程。
    """
    write_fake_session_log(tmp_path, SID)
    assert find_session_log("") == []
    assert find_session_log("   ") == []
    assert find_session_log(None) == []


def test_find_session_log_returns_file_and_dir(tmp_path):
    write_fake_session_log(tmp_path, SID)
    found = find_session_log(SID, [str(tmp_path)])
    names = sorted(p.name for p in found)
    assert names == [SID, f"{SID}.jsonl"]


def test_find_session_log_missing_id_returns_nothing(tmp_path):
    write_fake_session_log(tmp_path, SID)
    assert find_session_log("00000000-0000-0000-0000-000000000000", [str(tmp_path)]) == []


def test_find_session_log_searches_every_root(tmp_path):
    """多个配置根（本机有 ~/.claude 与 ~/.cosight）都要扫到。"""
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    write_fake_session_log(root_a, SID)
    write_fake_session_log(root_b, SID)

    found = find_session_log(SID, [str(root_a), str(root_b)])

    assert len(found) == 4
    assert sum(1 for p in found if str(root_a) in str(p)) == 2
    assert sum(1 for p in found if str(root_b) in str(p)) == 2


def test_find_session_log_ignores_nonexistent_root(tmp_path):
    assert find_session_log(SID, [str(tmp_path / "nope")]) == []


# ============================== copy_session_log ==============================

def test_copy_session_log_returns_empty_when_absent(tmp_path):
    """没找到就返回空列表，不抛错——日志缺失是基建问题，不该让用例失败。"""
    assert copy_session_log(SID, tmp_path / "out", [str(tmp_path)]) == []
    assert not (tmp_path / "out").exists()


def test_copy_session_log_copies_file_and_subagents(tmp_path):
    write_fake_session_log(tmp_path, SID)
    dest = tmp_path / "out" / "sessions"

    copied = copy_session_log(SID, dest, [str(tmp_path)])

    assert len(copied) == 2
    assert (dest / f"{SID}.jsonl").read_text(encoding="utf-8") == '{"type":"user"}\n'
    assert (dest / SID / "subagents" / "agent-abc.jsonl").is_file()


def test_copy_session_log_is_idempotent(tmp_path):
    """重复拷同一会话不报错，目录已存在也照常覆盖。"""
    write_fake_session_log(tmp_path, SID)
    dest = tmp_path / "out"

    copy_session_log(SID, dest, [str(tmp_path)])
    copied = copy_session_log(SID, dest, [str(tmp_path)])

    assert len(copied) == 2
    assert (dest / f"{SID}.jsonl").is_file()


def test_copy_session_log_creates_destination_parents(tmp_path):
    write_fake_session_log(tmp_path, SID)
    dest = tmp_path / "deep" / "nested" / "sessions"

    copy_session_log(SID, dest, [str(tmp_path)])

    assert dest.is_dir()


def test_copy_session_log_uses_config_globs_by_default(tmp_path, monkeypatch):
    """不给 roots 时走 config.SESSION_LOG_GLOBS（conftest 已把它指到临时目录）。"""
    root = Path(config.SESSION_LOG_GLOBS[0])
    write_fake_session_log(root, SID)

    copied = copy_session_log(SID, tmp_path / "out")

    assert len(copied) == 2
