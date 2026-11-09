#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态机单元 + 契约测试：迁移守卫、原子写、对账、参数冻结、事件流。"""

import hashlib
import json

import pytest

import state


# ============================== 测试辅助 ==============================

def call(*argv):
    return state.main([str(a) for a in argv])


def init_run(root, **overrides):
    argv = ["init", "--run-dir", str(root)]
    for key, flag in (("agent", "--agent"), ("count", "--count"),
                      ("requirement", "--requirement"),
                      ("output_parent", "--output-parent"),
                      ("concurrency", "--concurrency")):
        if key in overrides:
            argv += [flag, str(overrides[key])]
    return call(*argv)


def begin(root, stage):
    return call("begin", "--run-dir", str(root), "--stage", stage)


def complete(root, stage, exit_code=0, warning=None):
    argv = ["complete", "--run-dir", str(root), "--stage", stage,
            "--exit-code", str(exit_code)]
    if warning:
        argv += ["--warning", warning]
    return call(*argv)


def reconcile(root, **overrides):
    argv = ["reconcile", "--run-dir", str(root)]
    for key, flag in (("agent", "--agent"), ("count", "--count"),
                      ("requirement", "--requirement"),
                      ("concurrency", "--concurrency")):
        if key in overrides:
            argv += [flag, str(overrides[key])]
    return call(*argv)


def finish_stage(root, make_anchor, stage, text="{}"):
    assert begin(root, stage) == 0
    make_anchor(root, stage, text)
    assert complete(root, stage) == 0


# ============================== init ==============================

def test_init_creates_all_pending(run_dir, read_state):
    assert init_run(run_dir, agent="/x/v1", count=5) == 0
    saved = read_state(run_dir)
    assert saved["schema_version"] == 1
    assert saved["adopted"] is False
    assert saved["params"]["agent"] == "/x/v1"
    assert saved["params"]["count"] == 5
    assert saved["frozen"] == ["agent", "count", "requirement"]
    assert {s: m["status"] for s, m in saved["stages"].items()} == {
        "generate": "pending", "run": "pending",
        "eval": "pending", "trace": "pending",
    }


def test_init_twice_is_guard_error(run_dir, capsys):
    assert init_run(run_dir) == 0
    assert init_run(run_dir) == state.EXIT_GUARD
    assert "已有状态文件" in capsys.readouterr().err


def test_init_missing_run_dir_is_guard_error(tmp_path, capsys):
    assert init_run(tmp_path / "nope") == state.EXIT_GUARD
    assert "run 目录不存在" in capsys.readouterr().err


def test_init_writes_first_event(run_dir, read_events):
    init_run(run_dir)
    events = read_events(run_dir)
    assert [e["event"] for e in events] == ["run.init"]
    assert events[0]["seq"] == 1


# ============================== status ==============================

def test_status_reports_next_action(run_dir, capsys):
    init_run(run_dir)
    capsys.readouterr()
    assert call("status", "--run-dir", str(run_dir)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next_action"] == "generate"
    assert payload["blocked_reason"] is None


def test_status_missing_state_is_guard_error(run_dir, capsys):
    assert call("status", "--run-dir", str(run_dir)) == state.EXIT_GUARD
    assert "没有状态文件" in capsys.readouterr().err


def test_status_rejects_unknown_schema(run_dir, capsys):
    init_run(run_dir)
    path = state.state_path_of(run_dir)
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["schema_version"] = 99
    path.write_text(json.dumps(saved), encoding="utf-8")
    capsys.readouterr()
    assert call("status", "--run-dir", str(run_dir)) == state.EXIT_GUARD
    assert "版本不匹配" in capsys.readouterr().err


def test_status_table_format(run_dir, capsys):
    init_run(run_dir)
    capsys.readouterr()
    assert call("status", "--run-dir", str(run_dir), "--format", "table") == 0
    out = capsys.readouterr().out
    assert "next_action: generate" in out
    assert "generate" in out and "pending" in out


# ============================== begin ==============================

def test_begin_enforces_linear_order(run_dir, capsys):
    init_run(run_dir)
    capsys.readouterr()
    assert begin(run_dir, "run") == state.EXIT_GUARD
    err = capsys.readouterr().err
    assert "generate" in err and "尚未完成" in err


def test_begin_reentry_from_failed(run_dir, make_anchor, read_state):
    init_run(run_dir)
    begin(run_dir, "generate")
    assert call("fail", "--run-dir", str(run_dir), "--stage", "generate",
                "--reason", "前置失败") == 0
    assert begin(run_dir, "generate") == 0
    assert read_state(run_dir)["stages"]["generate"]["status"] == "running"
    assert read_state(run_dir)["stages"]["generate"]["reason"] is None


def test_begin_after_done_is_guard_error(run_dir, make_anchor, capsys):
    init_run(run_dir)
    finish_stage(run_dir, make_anchor, "generate")
    capsys.readouterr()
    assert begin(run_dir, "generate") == state.EXIT_GUARD
    assert "已完成，不能直接重开" in capsys.readouterr().err


def test_begin_rejects_missing_input_path(run_dir, tmp_path, make_anchor, capsys):
    init_run(run_dir)
    finish_stage(run_dir, make_anchor, "generate")
    capsys.readouterr()
    missing = tmp_path / "gone"
    assert call("begin", "--run-dir", str(run_dir), "--stage", "run",
                "--input-path", str(missing)) == state.EXIT_GUARD
    assert "输入路径不存在" in capsys.readouterr().err


# ============================== complete / fail ==============================

def test_complete_requires_running(run_dir, capsys):
    init_run(run_dir)
    assert complete(run_dir, "generate") == state.EXIT_GUARD
    assert "只有 running" in capsys.readouterr().err


def test_complete_rejects_missing_anchor(run_dir, capsys):
    init_run(run_dir)
    begin(run_dir, "generate")
    assert complete(run_dir, "generate") == state.EXIT_GUARD
    assert "锚点产物不存在" in capsys.readouterr().err


def test_complete_records_hash_and_keeps_exit_code_1(run_dir, make_anchor, read_state):
    """退出码 1 是「有缺口但已交付」，照样 complete。"""
    init_run(run_dir)
    begin(run_dir, "generate")
    make_anchor(run_dir, "generate", "seed-bytes")
    assert complete(run_dir, "generate", exit_code=1, warning="缺口：4/5") == 0
    meta = read_state(run_dir)["stages"]["generate"]
    assert meta["status"] == "done"
    assert meta["exit_code"] == 1
    assert meta["warnings"] == ["缺口：4/5"]
    assert meta["anchor_sha256"] == hashlib.sha256(b"seed-bytes").hexdigest()


def test_fail_records_reason(run_dir, read_state, read_events):
    init_run(run_dir)
    begin(run_dir, "generate")
    assert call("fail", "--run-dir", str(run_dir), "--stage", "generate",
                "--reason", "解析不出") == 0
    assert read_state(run_dir)["stages"]["generate"]["status"] == "failed"
    assert read_state(run_dir)["stages"]["generate"]["reason"] == "解析不出"
    assert read_events(run_dir)[-1]["event"] == "stage.fail"


def test_fail_requires_running(run_dir, capsys):
    init_run(run_dir)
    assert call("fail", "--run-dir", str(run_dir), "--stage", "generate",
                "--reason", "x") == state.EXIT_GUARD
    assert "只有 running" in capsys.readouterr().err


# ============================== reconcile ==============================

def test_reconcile_promotes_running_with_anchor(run_dir, make_anchor, read_state,
                                                read_events, capsys):
    init_run(run_dir)
    begin(run_dir, "generate")
    make_anchor(run_dir, "generate", "seed")
    capsys.readouterr()
    assert reconcile(run_dir) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["promoted"] == ["generate"]
    assert payload["stop"] is False
    assert read_state(run_dir)["stages"]["generate"]["status"] == "done"
    assert read_state(run_dir)["stages"]["generate"]["exit_code"] is None
    assert read_events(run_dir)[-1]["event"] == "reconcile.promote"


def test_reconcile_downgrades_missing_anchor_and_stops(run_dir, make_anchor,
                                                       read_state, capsys):
    init_run(run_dir)
    finish_stage(run_dir, make_anchor, "generate")
    run_dir.joinpath(*state.STAGE_ANCHORS["generate"]).unlink()
    capsys.readouterr()
    assert reconcile(run_dir) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stop"] is True
    assert payload["next_action"] == "blocked"
    assert payload["downgraded"][0]["stage"] == "generate"
    assert read_state(run_dir)["stages"]["generate"]["status"] == "pending"


def test_reconcile_cascades_to_downstream(run_dir, make_anchor, read_state, capsys):
    init_run(run_dir)
    for stage in ("generate", "run", "eval"):
        finish_stage(run_dir, make_anchor, stage)
    # 删除最早一段的锚点：其后已完成的两段都基于旧输入，必须一并降级。
    run_dir.joinpath(*state.STAGE_ANCHORS["generate"]).unlink()
    capsys.readouterr()
    assert reconcile(run_dir) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {d["stage"] for d in payload["downgraded"]} == {"generate", "run", "eval"}
    statuses = {s: m["status"] for s, m in read_state(run_dir)["stages"].items()}
    assert statuses == {"generate": "pending", "run": "pending",
                        "eval": "pending", "trace": "pending"}


def test_reconcile_detects_rewritten_anchor(run_dir, make_anchor, read_state, capsys):
    init_run(run_dir)
    finish_stage(run_dir, make_anchor, "generate", "v1")
    anchor = run_dir.joinpath(*state.STAGE_ANCHORS["generate"])
    anchor.write_text("v2", encoding="utf-8")
    capsys.readouterr()
    assert reconcile(run_dir) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["downgraded"][0]["reason"] == "anchor changed"
    assert read_state(run_dir)["stages"]["generate"]["status"] == "pending"


def test_reconcile_reports_when_all_done(run_dir, make_anchor, capsys):
    init_run(run_dir)
    for stage in state.STAGES:
        finish_stage(run_dir, make_anchor, stage)
    capsys.readouterr()
    assert reconcile(run_dir) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next_action"] == "report"
    assert payload["stop"] is False


# ============================== 参数冻结 ==============================

def test_reconcile_rejects_changed_frozen_param(run_dir, capsys):
    init_run(run_dir, agent="/x/v1", count=5)
    capsys.readouterr()
    assert reconcile(run_dir, agent="/x/v2") == state.EXIT_GUARD
    err = capsys.readouterr().err
    assert "参数与首轮不一致" in err
    assert "/x/v1" in err and "/x/v2" in err
    assert "换一条新命令" in err and "--concurrency" in err


def test_reconcile_accepts_matching_params(run_dir):
    init_run(run_dir, agent="/x/v1", count=5, requirement="")
    assert reconcile(run_dir, agent="/x/v1", count=5, requirement="") == 0


def test_reconcile_records_concurrency_change(run_dir, read_state, read_events):
    init_run(run_dir, concurrency=1)
    assert reconcile(run_dir, concurrency=4) == 0
    assert read_state(run_dir)["params"]["concurrency"] == 4
    update = [e for e in read_events(run_dir) if e["event"] == "resume.params_update"]
    assert len(update) == 1
    assert update[0]["message"] == "concurrency: 1 -> 4"


# ============================== 事件流 ==============================

def test_events_seq_is_monotonic(run_dir, make_anchor, read_events):
    init_run(run_dir)
    finish_stage(run_dir, make_anchor, "generate")
    reconcile(run_dir)
    seqs = [e["seq"] for e in read_events(run_dir)]
    assert seqs == list(range(1, len(seqs) + 1))


def test_events_are_flat_objects(run_dir, make_anchor, read_events):
    init_run(run_dir)
    finish_stage(run_dir, make_anchor, "generate")
    for event in read_events(run_dir):
        assert set(event) == {
            "seq", "ts", "event", "stage", "from", "to",
            "exit_code", "duration_s", "warnings", "message",
        }


# ============================== 契约：全链 + 续跑 ==============================

def test_full_chain_then_resume_reports(run_dir, make_anchor, capsys):
    """四段依次推进后，--resume 的开场对账应为 report，不重跑任何阶段。"""
    assert init_run(run_dir, agent="/x/v1", count=5) == 0
    for stage in state.STAGES:
        assert begin(run_dir, stage) == 0
        make_anchor(run_dir, stage)
        assert complete(run_dir, stage) == 0
    capsys.readouterr()
    assert reconcile(run_dir, agent="/x/v1", count=5) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next_action"] == "report"
    assert payload["promoted"] == []
    assert payload["downgraded"] == []


def test_resume_after_interruption_reneters_pending_stage(run_dir, make_anchor, capsys):
    """中断在 eval：reconcile 给 next_action=eval，状态保持 pending。"""
    init_run(run_dir)
    for stage in ("generate", "run"):
        finish_stage(run_dir, make_anchor, stage)
    capsys.readouterr()
    assert reconcile(run_dir) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next_action"] == "eval"
    assert payload["stop"] is False


def test_complete_isolated_from_stdout_and_stderr(run_dir, make_anchor, capsys):
    """complete 成功路径不往 stderr 写任何东西——编排层靠退出码分流。"""
    init_run(run_dir)
    begin(run_dir, "generate")
    make_anchor(run_dir, "generate")
    capsys.readouterr()
    assert complete(run_dir, "generate") == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["ok"] is True


# ============================== 边界与容错 ==============================

def test_duration_between_handles_missing_and_bad_values():
    assert state.duration_between(None, "2026-01-01T00:00:00") is None
    assert state.duration_between("2026-01-01T00:00:00", None) is None
    assert state.duration_between("not-a-time", "2026-01-01T00:00:00") is None
    assert state.duration_between(
        "2026-01-01T00:00:00+08:00", "2026-01-01T00:00:05+08:00") == 5.0


def test_corrupt_state_file_is_internal_error(run_dir, capsys):
    init_run(run_dir)
    state.state_path_of(run_dir).write_text("{not json", encoding="utf-8")
    capsys.readouterr()
    assert call("status", "--run-dir", str(run_dir)) == state.EXIT_ERROR
    assert "无法解析状态文件" in capsys.readouterr().err


def test_unknown_stage_rejected_directly():
    with pytest.raises(state.GuardError, match="未知阶段"):
        state.require_stage("bogus")


def test_last_seq_skips_blank_and_bad_lines(run_dir, read_state):
    init_run(run_dir)
    path = state.events_path_of(run_dir)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write("{broken\n")
        fh.write(json.dumps({"seq": 7}) + "\n")
    assert state.last_seq_of(run_dir) == 7
    # 状态文件记的是 1；事件流实际到 7，新事件必须接着 8，不能重号。
    saved = read_state(run_dir)
    event = state.append_event(run_dir, saved, state.EVENT_BEGIN, stage="generate")
    assert event["seq"] == 8


def test_table_shows_blocked_reason(run_dir):
    init_run(run_dir)
    saved = json.loads(state.state_path_of(run_dir).read_text(encoding="utf-8"))
    payload = state.status_payload(saved, blocked_reason="产物被删除")
    assert "blocked:     产物被删除" in state.render_table(payload)
    assert payload["next_action"] == "blocked"


def test_state_file_is_written_atomically(run_dir):
    """写完后不应残留 .tmp 文件。"""
    init_run(run_dir)
    assert list(state.state_dir_of(run_dir).glob("*.tmp")) == []
