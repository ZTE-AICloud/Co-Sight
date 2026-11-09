"""wave-barrier/scripts/aggregate.py 单测。

覆盖范围：condense、aggregate、check_wave_completeness、load_summaries、main。
writeback 走 state_cli subprocess，单测难做端到端；用 monkeypatch 验 key path。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import aggregate as agg  # noqa: E402


# ---------- condense ----------


def test_condense_extracts_basic_fields():
    s = {
        "task_id": "t1",
        "status": "completed",
        "duration_sec": 12.5,
        "files_changed": ["a.py", "b.py"],
    }
    out = agg.condense(s)
    assert out is not None
    assert out["task_id"] == "t1"
    assert out["entry"]["status"] == "completed"
    assert out["entry"]["files_count"] == 2
    assert out["entry"]["files_changed"] == ["a.py", "b.py"]
    assert out["entry"]["duration_sec"] == 12.5
    assert out["entry"]["attempts"] == 1


def test_condense_returns_none_without_task_id():
    assert agg.condense({"status": "completed"}) is None
    assert agg.condense({"task_id": ""}) is None
    assert agg.condense({"task_id": "   "}) is None
    # condense() 本身要求 dict 输入，None / 非 dict 由 aggregate() 那边 catch
    # 验证 condense 在 None 上抛错即可
    import pytest as _pt
    with _pt.raises(AttributeError):
        agg.condense(None)  # type: ignore[arg-type]
    with _pt.raises(AttributeError):
        agg.condense("not a dict")  # type: ignore[arg-type]


def test_condense_normalizes_attempts():
    s = {"task_id": "t", "status": "completed", "attempts": "3"}
    out = agg.condense(s)
    assert out["entry"]["attempts"] == 3
    # 无效 attempts 降级为 1
    s = {"task_id": "t", "status": "completed", "attempts": "abc"}
    assert agg.condense(s)["entry"]["attempts"] == 1
    # None / 缺 → 1
    s = {"task_id": "t", "status": "completed"}
    assert agg.condense(s)["entry"]["attempts"] == 1
    # 0 / 负数 → 至少 1
    s = {"task_id": "t", "status": "completed", "attempts": 0}
    assert agg.condense(s)["entry"]["attempts"] == 1
    s = {"task_id": "t", "status": "completed", "attempts": -5}
    assert agg.condense(s)["entry"]["attempts"] == 1


def test_condense_filters_non_string_files():
    s = {
        "task_id": "t",
        "status": "completed",
        "files_changed": ["a.py", 123, None, Path("b.py"), {"x": 1}],
    }
    out = agg.condense(s)
    # condense 对原始 list 计数（files_count = len(files_list)），
    # 过滤仅作用于写入的 files_changed
    assert out["entry"]["files_changed"] == ["a.py", "b.py"]
    assert out["entry"]["files_count"] == 5


def test_condense_handles_files_as_non_list():
    s = {"task_id": "t", "status": "completed", "files_changed": "a.py"}
    out = agg.condense(s)
    # 非 list 视作空
    assert out["entry"]["files_count"] == 0
    assert out["entry"]["files_changed"] == []


# ---------- aggregate ----------


def _summary(task_id: str, status: str = "completed", files: list[str] | None = None) -> dict:
    return {
        "task_id": task_id,
        "status": status,
        "files_changed": files if files is not None else [f"{task_id}.py"],
        "duration_sec": 1.0,
    }


def test_aggregate_dones_count_as_success():
    summaries = [_summary("a"), _summary("b", status="skipped")]
    out = agg.aggregate(1, summaries)
    assert out["wave_summaries"]["1"]["success_count"] == 2
    assert out["wave_summaries"]["1"]["fail_count"] == 0
    assert out["barrier_blocked"] is False


def test_aggregate_failed_status_increments_fail_count():
    summaries = [
        _summary("a"),
        _summary("b", status="failed"),
        _summary("c", status="partial"),
    ]
    out = agg.aggregate(1, summaries)
    assert out["wave_summaries"]["1"]["success_count"] == 1
    assert out["wave_summaries"]["1"]["fail_count"] == 2


def test_aggregate_empty_fsdiff_blocks_barrier():
    summaries = [
        _summary("a", files=["a.py"]),
        _summary("b", files=[]),  # 完成但无文件 → 触发 empty_fsdiff
    ]
    out = agg.aggregate(1, summaries)
    assert out["barrier_blocked"] is True
    assert "b" in out["empty_fsdiff"]


def test_aggregate_invalid_summary_increments_invalid_count():
    summaries = [
        _summary("a"),
        {"status": "completed"},  # 缺 task_id
        "not a dict",  # type: ignore[list-item]
    ]
    out = agg.aggregate(1, summaries)
    assert out["invalid_count"] == 2
    # invalid 也算 fail
    assert out["wave_summaries"]["1"]["fail_count"] >= 2


def test_aggregate_total_duration_sums_int_and_float():
    summaries = [
        _summary("a"),
        {"task_id": "b", "status": "completed",
         "files_changed": ["b.py"], "duration_sec": 3},
    ]
    out = agg.aggregate(1, summaries)
    assert out["wave_summaries"]["1"]["total_duration_sec"] == 4.0


# ---------- expected_task_ids ----------


def test_expected_task_ids_missing_file_returns_none(tmp_path: Path):
    assert agg.expected_task_ids(tmp_path, 1) is None


def test_expected_task_ids_yaml_error_returns_none(tmp_path: Path):
    (tmp_path / "waves.yaml").write_text("invalid: [unclosed", encoding="utf-8")
    assert agg.expected_task_ids(tmp_path, 1) is None


def test_expected_task_ids_non_dict_returns_none(tmp_path: Path):
    (tmp_path / "waves.yaml").write_text("- a\n- b\n", encoding="utf-8")
    assert agg.expected_task_ids(tmp_path, 1) is None


def test_expected_task_ids_returns_matching_wave(tmp_path: Path):
    (tmp_path / "waves.yaml").write_text(
        "waves:\n"
        "  - wave: 1\n"
        "    tasks:\n"
        "      - task_id: a\n"
        "      - task_id: b\n"
        "  - wave: 2\n"
        "    tasks:\n"
        "      - task_id: c\n",
        encoding="utf-8",
    )
    assert agg.expected_task_ids(tmp_path, 1) == ["a", "b"]
    assert agg.expected_task_ids(tmp_path, 2) == ["c"]
    assert agg.expected_task_ids(tmp_path, 3) is None


# ---------- check_wave_completeness ----------


def test_check_wave_completeness_expected_none_returns_unenforced():
    out = agg.check_wave_completeness(None, [])
    assert out == {"enforced": False}


def test_check_wave_completeness_perfect_match():
    out = agg.check_wave_completeness(["a", "b"], [{"task_id": "a"}, {"task_id": "b"}])
    assert out["enforced"] is True
    assert out["missing"] == []
    assert out["extras"] == []
    assert out["duplicates"] == []


def test_check_wave_completeness_missing_and_extras():
    out = agg.check_wave_completeness(
        ["a", "b"], [{"task_id": "a"}, {"task_id": "c"}]
    )
    assert out["missing"] == ["b"]
    assert out["extras"] == ["c"]


def test_check_wave_completeness_detects_duplicates():
    out = agg.check_wave_completeness(
        ["a"], [{"task_id": "a"}, {"task_id": "a"}]
    )
    assert out["duplicates"] == ["a"]


def test_check_wave_completeness_skips_non_dict_summaries():
    out = agg.check_wave_completeness(
        ["a"], [{"task_id": "a"}, "not a dict", None]  # type: ignore[list-item]
    )
    assert out["missing"] == []
    assert out["extras"] == []


def test_check_wave_completeness_skips_empty_task_id():
    out = agg.check_wave_completeness(
        ["a"], [{"task_id": ""}, {"task_id": "   "}, {"task_id": "a"}]
    )
    assert out["missing"] == []


# ---------- load_summaries ----------


def _args(summaries, summaries_file, stdin):
    ns = type("Args", (), {})()
    ns.summaries = summaries
    ns.summaries_file = summaries_file
    ns.stdin = stdin
    return ns


def test_load_summaries_from_summaries_arg():
    args = _args(summaries='[{"task_id":"a"}]', summaries_file=None, stdin=False)
    out = agg.load_summaries(args)
    assert out == [{"task_id": "a"}]


def test_load_summaries_from_summaries_file(tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text('[{"task_id":"a"}]', encoding="utf-8")
    args = _args(summaries=None, summaries_file=str(p), stdin=False)
    assert agg.load_summaries(args) == [{"task_id": "a"}]


def test_load_summaries_file_missing(tmp_path: Path):
    args = _args(summaries=None, summaries_file=str(tmp_path / "nope"), stdin=False)
    out = agg.load_summaries(args)
    assert isinstance(out, agg.Envelope)
    assert not out.ok
    assert out.reason == agg.REASON_INVALID_ARG


def test_load_summaries_invalid_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    args = _args(summaries=None, summaries_file=str(p), stdin=False)
    out = agg.load_summaries(args)
    assert isinstance(out, agg.Envelope)
    assert out.reason == agg.REASON_INVALID_ARG


def test_load_summaries_non_list_payload(tmp_path: Path):
    p = tmp_path / "obj.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    args = _args(summaries=None, summaries_file=str(p), stdin=False)
    out = agg.load_summaries(args)
    assert isinstance(out, agg.Envelope)
    assert out.reason == agg.REASON_INVALID_ARG


def test_load_summaries_no_source():
    args = _args(summaries=None, summaries_file=None, stdin=False)
    out = agg.load_summaries(args)
    assert isinstance(out, agg.Envelope)
    assert out.reason == agg.REASON_INVALID_ARG


def test_load_summaries_stdin(monkeypatch):
    class _FakeStdin:
        def read(self) -> str:
            return '[{"task_id":"a"}]'
    monkeypatch.setattr(sys, "stdin", _FakeStdin())
    args = _args(summaries=None, summaries_file=None, stdin=True)
    assert agg.load_summaries(args) == [{"task_id": "a"}]


# ---------- read_existing / writeback ----------


class _FakeProc:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_read_existing_handles_bad_state_cli(monkeypatch, tmp_path: Path):
    """state_cli 返回非 0 时 read_existing 返回空 dict。"""
    fake_cli = tmp_path / "fake_state_cli.py"
    fake_cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: _FakeProc(2, "", ""))
    out = agg.read_existing(fake_cli, tmp_path)
    assert out == {}


def test_read_existing_handles_bad_json(monkeypatch, tmp_path: Path):
    fake_cli = tmp_path / "fake_state_cli.py"
    fake_cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: _FakeProc(0, "not json", ""))
    out = agg.read_existing(fake_cli, tmp_path)
    assert out == {}


def test_read_existing_returns_state(monkeypatch, tmp_path: Path):
    fake_cli = tmp_path / "fake_state_cli.py"
    fake_cli.write_text("", encoding="utf-8")
    payload = json.dumps({"data": {"state": {"task_results": {"a": {"status": "completed"}}}}})
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: _FakeProc(0, payload, ""))
    out = agg.read_existing(fake_cli, tmp_path)
    assert out == {"task_results": {"a": {"status": "completed"}}}


def test_read_existing_handles_timeout(monkeypatch, tmp_path: Path):
    fake_cli = tmp_path / "fake_state_cli.py"
    fake_cli.write_text("", encoding="utf-8")
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="state_cli", timeout=30)
    monkeypatch.setattr(subprocess, "run", boom)
    assert agg.read_existing(fake_cli, tmp_path) == {}


def test_writeback_state_cli_missing(tmp_path: Path, monkeypatch):
    """cli 不存在时直接 fail，不发子进程。"""
    fake = tmp_path / "no_such_cli.py"
    monkeypatch.setattr(agg, "_state_cli_path", lambda: fake)
    out = agg.writeback(tmp_path, {"task_results": {}, "wave_summaries": {}})
    assert not out.ok
    assert out.reason == agg.REASON_WRITEBACK_FAILED


def test_writeback_subprocess_timeout(tmp_path: Path, monkeypatch):
    fake = tmp_path / "cli.py"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(agg, "_state_cli_path", lambda: fake)
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="cli", timeout=30)
    monkeypatch.setattr(subprocess, "run", boom)
    out = agg.writeback(tmp_path, {"task_results": {}, "wave_summaries": {}})
    assert not out.ok
    assert out.reason == agg.REASON_SUBPROCESS_TIMEOUT


def test_writeback_state_cli_error(tmp_path: Path, monkeypatch):
    fake = tmp_path / "cli.py"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(agg, "_state_cli_path", lambda: fake)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: _FakeProc(1, json.dumps({"reason": "x"}), ""))
    out = agg.writeback(tmp_path, {"task_results": {}, "wave_summaries": {}})
    assert not out.ok
    assert out.reason == agg.REASON_WRITEBACK_FAILED


def test_writeback_success(tmp_path: Path, monkeypatch):
    fake = tmp_path / "cli.py"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(agg, "_state_cli_path", lambda: fake)
    payload = json.dumps({"data": {"revision": "r1"}})
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: _FakeProc(0, payload, ""))
    out = agg.writeback(tmp_path, {"task_results": {"a": {"status": "completed"}},
                                    "wave_summaries": {"1": {"task_count": 1}}})
    assert out.ok
    assert out.data["revision"] == "r1"


# ---------- main ----------


def test_main_planning_dir_missing(tmp_path: Path):
    rc = agg.main(["--planning-dir", str(tmp_path / "nope"), "--wave", "1",
                   "--summaries", "[]"])
    assert rc == 1


def test_main_empty_summaries_fails(tmp_path: Path):
    rc = agg.main(["--planning-dir", str(tmp_path), "--wave", "1",
                   "--summaries", "[]"])
    assert rc == 1


def test_main_invalid_json_fails(tmp_path: Path):
    rc = agg.main(["--planning-dir", str(tmp_path), "--wave", "1",
                   "--summaries", "not json"])
    assert rc == 1


def test_main_wave_mismatch_blocks(tmp_path: Path):
    """waves.yaml 里 wave 1 是 [a, b]，但 summaries 只有 a。"""
    (tmp_path / "waves.yaml").write_text(
        "waves:\n  - wave: 1\n    tasks:\n      - task_id: a\n      - task_id: b\n",
        encoding="utf-8",
    )
    rc = agg.main([
        "--planning-dir", str(tmp_path), "--wave", "1",
        "--summaries", json.dumps([_summary("a")]),
    ])
    assert rc == 1


def test_main_empty_fsdiff_blocks(tmp_path: Path, monkeypatch):
    """空 waves.yaml → 走 degrade-allow；进 aggregate 后空 fs 被拦。"""
    fake = tmp_path / "cli.py"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(agg, "_state_cli_path", lambda: fake)
    rc = agg.main([
        "--planning-dir", str(tmp_path), "--wave", "1",
        "--summaries", json.dumps([_summary("a", files=[])]),
    ])
    assert rc == 1


def test_main_success_path(tmp_path: Path, monkeypatch, capsys):
    fake = tmp_path / "cli.py"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(agg, "_state_cli_path", lambda: fake)
    payload = json.dumps({"data": {"revision": "r1"}})
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **kw: _FakeProc(0, payload, ""))
    rc = agg.main([
        "--planning-dir", str(tmp_path), "--wave", "1",
        "--summaries", json.dumps([_summary("a", files=["a.py"])]),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["ok"] is True
    assert out["data"]["barrier_enforced"] is False  # 没 waves.yaml
