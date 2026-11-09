#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_locate.py — --input / --output 的解析与守卫。

定位出错是**静默**的：路径错 → 找不到数据或读到错的数据，不会崩。所以这里铺得细。
"""

import pytest

import common
import config
from conftest import seed_record


# ============================== --input 三形态 ==============================

def test_input_accepts_run_dir(make_run, monkeypatch, tmp_path):
    run_dir, seed_path, _ = make_run([seed_record()])
    monkeypatch.chdir(tmp_path)
    assert common.locate_seed(str(run_dir)) == seed_path.resolve()


def test_input_accepts_run_datasets_dir(make_run, monkeypatch, tmp_path):
    run_dir, seed_path, _ = make_run([seed_record()])
    monkeypatch.chdir(tmp_path)
    assert common.locate_seed(str(run_dir / "run_datasets")) == seed_path.resolve()


def test_input_accepts_seed_file(make_run, monkeypatch, tmp_path):
    _, seed_path, _ = make_run([seed_record()])
    monkeypatch.chdir(tmp_path)
    assert common.locate_seed(str(seed_path)) == seed_path.resolve()


def test_probe_order_prefers_run_datasets_over_bare_seed(make_run, monkeypatch, tmp_path):
    """run 目录下同时有两份 seed 时，必须读 run_datasets 那份（跑过的）。

    读反了就会拿到没跑过的用例集——这正是探测链顺序存在的理由。
    """
    run_dir, seed_path, _ = make_run([seed_record()])
    (run_dir / "seed.jsonl").write_text('{"data_id": "not-run"}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert common.locate_seed(str(run_dir)) == seed_path.resolve()


# ============================== 默认值 ==============================

def test_default_input_takes_newest_run_dir(make_run, monkeypatch, tmp_path):
    make_run([seed_record()], run_name="e2e-test-20260101-000000")
    newest, newest_seed, _ = make_run([seed_record()], run_name="e2e-test-20260202-000000")
    monkeypatch.chdir(tmp_path)
    assert common.locate_seed(None) == newest_seed.resolve()


def test_default_output_takes_newest_run_dir(make_run, monkeypatch, tmp_path):
    make_run([seed_record()], run_name="e2e-test-20260101-000000")
    newest, newest_seed, _ = make_run([seed_record()], run_name="e2e-test-20260202-000000")
    monkeypatch.chdir(tmp_path)
    assert common.resolve_output_dir(None, newest_seed) == newest.resolve()


def test_default_input_without_any_run_dir_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(common.EvalError, match="没有 e2e-test"):
        common.locate_seed(None)


def test_default_output_without_any_run_dir_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(common.EvalError, match="没有 e2e-test"):
        common.resolve_output_dir(None, tmp_path / "x" / "seed.jsonl")


# ============================== 报错而非静默避让 ==============================

def test_missing_input_path_errors(tmp_path):
    with pytest.raises(common.EvalError, match="不存在"):
        common.locate_seed(str(tmp_path / "nope"))


def test_wrong_filename_errors(tmp_path):
    other = tmp_path / "cases.jsonl"
    other.write_text("{}\n", encoding="utf-8")
    with pytest.raises(common.EvalError, match="不是 seed.jsonl"):
        common.locate_seed(str(other))


def test_generated_datasets_gets_dedicated_hint(make_run, monkeypatch, tmp_path):
    """指到生成器交付物时，提示必须指名 e2e-test-runner，而不是笼统的"找不到"。"""
    run_dir, _, _ = make_run([seed_record()])
    generated = run_dir / config.GENERATOR_ARTIFACT_DIRNAME
    generated.mkdir()
    (generated / config.SEED_FILENAME).write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(common.EvalError) as excinfo:
        common.locate_seed(str(generated))
    assert "e2e-test-runner" in str(excinfo.value)


def test_run_dir_containing_only_generated_datasets_gets_hint(make_run, monkeypatch,
                                                              tmp_path):
    """run 目录里只有生成器产物（runner 从没跑过）时，也给那条提示。"""
    run_dir = tmp_path / "e2e-test-20260101-000000"
    generated = run_dir / config.GENERATOR_ARTIFACT_DIRNAME
    generated.mkdir(parents=True)
    (generated / config.SEED_FILENAME).write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(common.EvalError, match="e2e-test-runner"):
        common.locate_seed(str(run_dir))


def test_output_pointing_at_run_datasets_dir_errors(make_run, monkeypatch, tmp_path):
    """--output 要的是 run 目录；给了 run_datasets/ 会让结果落错一层。"""
    run_dir, _, _ = make_run([seed_record()])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(common.EvalError, match="run 目录"):
        common.resolve_output_dir(str(run_dir / "run_datasets"), run_dir / "seed.jsonl")


# ============================== 守卫 ==============================

def test_guard_rejects_overwriting_input_seed(make_run):
    run_dir, seed_path, _ = make_run([seed_record()])
    with pytest.raises(common.EvalError, match="覆盖"):
        common.guard_no_seed_overwrite(seed_path, seed_path)


def test_guard_rejects_output_inside_case_workspace(make_run):
    """产物目录落在用例副本内 = 把含 expected_output 的 prompt 放进被测目录。"""
    run_dir, seed_path, records = make_run([seed_record()])
    workspace = records[0]["run"]["workspace_dir"]

    with pytest.raises(common.EvalError, match="工作副本内部"):
        common.guard_no_answer_leak(
            f"{workspace}/{config.OUTPUT_ARTIFACT_DIRNAME}", records, seed_path.parent)


def test_guard_rejects_output_at_workspace_root(make_run):
    """产物目录恰好就是副本目录本身，同样算落进去了。"""
    run_dir, seed_path, records = make_run([seed_record()])
    with pytest.raises(common.EvalError, match="工作副本内部"):
        common.guard_no_answer_leak(
            records[0]["run"]["workspace_dir"], records, seed_path.parent)


def test_guard_allows_sibling_artifact_dir(make_run):
    """正常形态：产物与用例副本是并列目录，放行。"""
    run_dir, seed_path, records = make_run([seed_record()])
    common.guard_no_answer_leak(
        run_dir / config.OUTPUT_ARTIFACT_DIRNAME, records, seed_path.parent)


def test_guard_rejects_output_inside_agent_root(make_run, tmp_path):
    agent_root = tmp_path / "agent_root"
    agent_root.mkdir()
    run_dir, seed_path, _ = make_run(
        [seed_record()], with_manifest=True,
        manifest={"agent_root": str(agent_root)})

    with pytest.raises(common.EvalError, match="源目录内部"):
        common.guard_no_agent_root_write(agent_root / "eval_datasets", seed_path.parent)


def test_guard_skips_agent_root_check_without_manifest(make_run):
    """读不到 manifest 就不猜——守卫只做能确定的事。"""
    run_dir, seed_path, _ = make_run([seed_record()])
    common.guard_no_agent_root_write(
        run_dir / config.OUTPUT_ARTIFACT_DIRNAME, seed_path.parent)
