#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conftest.py — 把 scripts/ 挂到 sys.path，并提供公共 fixture。"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def run_dir(tmp_path):
    """一个空的 run 目录（编排层 mkdir 之后的形态）。"""
    path = tmp_path / "e2e-test-20260101-000000"
    path.mkdir()
    return path


@pytest.fixture
def make_anchor():
    """在某段的锚点位置写一个假产物。"""
    def _make(root, stage, text="{}"):
        import state  # 延迟导入：本模块要在挂好 sys.path 之后才 import 得到

        path = root.joinpath(*state.STAGE_ANCHORS[stage])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
    return _make


@pytest.fixture
def read_state():
    """读取本轮 state.json。"""
    def _read(root):
        import state

        return json.loads(state.state_path_of(root).read_text(encoding="utf-8"))
    return _read


@pytest.fixture
def read_events():
    """读取本轮 events.jsonl。"""
    def _read(root):
        import state

        path = state.events_path_of(root)
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    return _read
