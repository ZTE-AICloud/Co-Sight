#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""--input 探测、run 目录反推、--agent 回退的单元测试。"""

import json

import pytest

import common
from common import RunnerError


# ============================== locate_seed ==============================

def test_locate_seed_accepts_run_dir(make_seed_dir):
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}])
    assert common.locate_seed(str(run_dir)) == (run_dir / "generated_datasets" / "seed.jsonl").resolve()


def test_locate_seed_accepts_artifact_dir(make_seed_dir):
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}])
    artifact_dir = run_dir / "generated_datasets"
    assert common.locate_seed(str(artifact_dir)) == (artifact_dir / "seed.jsonl").resolve()


def test_locate_seed_accepts_seed_file(make_seed_dir):
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}])
    seed = run_dir / "generated_datasets" / "seed.jsonl"
    assert common.locate_seed(str(seed)) == seed.resolve()


def test_locate_seed_accepts_bare_seed_dir(tmp_path):
    """seed.jsonl 直接放在某目录下（无 generated_datasets 层）也应命中。"""
    bare = tmp_path / "handmade"
    bare.mkdir()
    (bare / "seed.jsonl").write_text('{"data_id":"c1","input":"hi"}\n', encoding="utf-8")
    assert common.locate_seed(str(bare)) == (bare / "seed.jsonl").resolve()


def test_locate_seed_rejects_missing_path(tmp_path):
    with pytest.raises(RunnerError, match="不存在"):
        common.locate_seed(str(tmp_path / "nope"))


def test_locate_seed_rejects_wrong_filename(tmp_path):
    other = tmp_path / "cases.jsonl"
    other.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RunnerError, match="不是 seed.jsonl"):
        common.locate_seed(str(other))


def test_locate_seed_rejects_dir_without_seed(tmp_path):
    empty = tmp_path / "e2e-test-20260101-000000"
    empty.mkdir()
    with pytest.raises(RunnerError, match="找不到 seed.jsonl"):
        common.locate_seed(str(empty))


def test_locate_seed_defaults_to_newest_run_dir(tmp_path, monkeypatch):
    """缺省 --input 时按目录名倒序取最新，不按 mtime。"""
    outputs = tmp_path / "outputs"
    for name in ("e2e-test-20260101-000000", "e2e-test-20260301-120000", "e2e-test-20260201-090000"):
        artifact = outputs / name / "generated_datasets"
        artifact.mkdir(parents=True)
        (artifact / "seed.jsonl").write_text('{"data_id":"c1","input":"hi"}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    found = common.locate_seed(None)
    assert found.parent.parent.name == "e2e-test-20260301-120000"


def test_locate_seed_defaults_ignore_non_run_dirs(tmp_path, monkeypatch):
    """outputs/ 下的其他目录不参与匹配。"""
    outputs = tmp_path / "outputs"
    decoy = outputs / "something-else" / "generated_datasets"
    decoy.mkdir(parents=True)
    (decoy / "seed.jsonl").write_text('{"data_id":"decoy","input":"x"}\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(RunnerError, match="没有 e2e-test"):
        common.locate_seed(None)


def test_locate_seed_defaults_error_when_outputs_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RunnerError, match="请显式指定：--input"):
        common.locate_seed(None)


# ============================== run_dir_of ==============================

def test_run_dir_of_strips_generated_datasets(make_seed_dir):
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}])
    seed = run_dir / "generated_datasets" / "seed.jsonl"
    assert common.run_dir_of(seed) == run_dir


def test_run_dir_of_bare_seed_returns_parent(tmp_path):
    bare = tmp_path / "handmade"
    bare.mkdir()
    seed = bare / "seed.jsonl"
    seed.write_text("{}\n", encoding="utf-8")
    assert common.run_dir_of(seed) == bare


# ============================== resolve_agent_root ==============================

def test_agent_root_from_manifest(make_seed_dir, tmp_path):
    root = tmp_path / "agent_root"
    root.mkdir()
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}], agent_root=root)
    seed = run_dir / "generated_datasets" / "seed.jsonl"
    assert common.resolve_agent_root(None, seed) == root.resolve()


def test_agent_root_explicit_wins(make_seed_dir, tmp_path):
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}])
    seed = run_dir / "generated_datasets" / "seed.jsonl"
    assert common.resolve_agent_root(str(explicit), seed) == explicit.resolve()


def test_agent_root_dead_path_errors(make_seed_dir, tmp_path):
    """manifest 里的 agent_root 指向已清理的解包中间态时报错，不静默回退。"""
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}],
                            agent_root=tmp_path / "gone")
    seed = run_dir / "generated_datasets" / "seed.jsonl"
    with pytest.raises(RunnerError) as exc:
        common.resolve_agent_root(None, seed)
    message = str(exc.value)
    assert "agent_root 不存在" in message
    assert "请显式指定：--agent" in message


def test_agent_root_without_manifest_errors(make_seed_dir):
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}], manifest=False)
    seed = run_dir / "generated_datasets" / "seed.jsonl"
    with pytest.raises(RunnerError, match="找不到 manifest.json"):
        common.resolve_agent_root(None, seed)


def test_agent_root_manifest_lacks_field(make_seed_dir):
    run_dir = make_seed_dir([{"data_id": "c1", "input": "hi"}], manifest=False)
    artifact_dir = run_dir / "generated_datasets"
    (artifact_dir / "manifest.json").write_text(json.dumps({"task_id": "t"}), encoding="utf-8")
    seed = artifact_dir / "seed.jsonl"
    with pytest.raises(RunnerError, match="没有 agent_root 字段"):
        common.resolve_agent_root(None, seed)


def test_agent_root_explicit_missing_dir(tmp_path):
    with pytest.raises(RunnerError, match="--agent 指向的目录不存在"):
        common.resolve_agent_root(str(tmp_path / "nope"), tmp_path / "seed.jsonl")
