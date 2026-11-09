#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conftest.py — 把 scripts/ 挂到 sys.path，并提供公共 fixture。"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def session_log_root(tmp_path, monkeypatch):
    """把会话日志搜索根指到临时目录，并返回该目录。

    autouse：保证任何测试都不会去扫真实的 ~/.claude——那既慢又不密闭，而且
    会把开发者自己几百份会话日志当数据源。需要"日志确实存在"的用例把本 fixture
    作为参数取到路径，再往里面写假日志即可。
    """
    import config  # 延迟导入：本模块要在挂好 sys.path 之后才 import 得到

    root = tmp_path / "fakehome" / ".claude" / "projects"
    root.mkdir(parents=True)
    monkeypatch.setattr(config, "SESSION_LOG_GLOBS", (str(root),))
    return root


def seed_record(data_id="agent_functional_001", **overrides):
    """构造一条 seed 记录（形状对齐 e2e-test-generator 的落盘格式）。"""
    record = {
        "data_id": data_id,
        "kind": "seed",
        "dimension": "functional",
        "source": "gwt",
        "source_ref": "pass-criteria.md#1",
        "input": "请对 ./demo_code 目录做明文密码检查",
        "precondition": "被测 Agent 工程根下存在 ./demo_code 目录",
        "expected_output": ["报告命中该 Java 源文件"],
        "capability_ref": "C01",
    }
    record.update(overrides)
    return record


@pytest.fixture
def make_seed_dir(tmp_path):
    """建一个生成器形态的 run 目录：<run>/generated_datasets/seed.jsonl。"""
    def _make(records, *, run_name="e2e-test-20260101-000000", manifest=True, agent_root=None):
        run_dir = tmp_path / run_name
        artifact_dir = run_dir / "generated_datasets"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "seed.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
        if manifest:
            root = agent_root or (tmp_path / "agent_root")
            payload = {"task_id": "t", "agent_root": str(root)}
            (artifact_dir / "manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return run_dir
    return _make
