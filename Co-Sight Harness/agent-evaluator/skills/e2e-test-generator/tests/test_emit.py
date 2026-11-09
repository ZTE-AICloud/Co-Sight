#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_emit.py — S5 输出目录解析、覆盖矩阵、报告渲染、落盘幂等。"""

import json
from pathlib import Path

import pytest

import config
import emit
from common import read_json, write_json


def make_plan(kept=2, dropped=1, quota=None):
    return {
        "count": 4,
        "user_input": "重点覆盖失败路径",
        "tier": config.TIER_A,
        "dimension_weights": {d["id"]: d["weight"] for d in config.DIMENSIONS},
        "focus": ["failure"],
        "focus_reason": "用户提到失败路径",
        "focus_bonus": config.FOCUS_WEIGHT_BONUS,
        "gwt_kept": [
            {"index": 1, "dimension": "functional", "title": "命中"},
            {"index": 4, "dimension": "failure", "title": "路径错误"},
        ][:kept],
        "gwt_dropped": [
            {"index": 6, "dimension": "functional", "title": "前缀键名"},
        ][:dropped],
        "gwt_total": 3,
        "generated_budget": 2,
        "quota": quota or {"functional": 1, "failure": 1},
        "batch_size": config.BATCH_SIZE,
    }


def make_records():
    return [
        {"data_id": "a_functional_001", "dimension": "functional",
         "source": config.SOURCE_GWT},
        {"data_id": "a_failure_001", "dimension": "failure",
         "source": config.SOURCE_GWT},
        {"data_id": "a_functional_002", "dimension": "functional",
         "source": config.SOURCE_LLM},
        {"data_id": "a_failure_002", "dimension": "failure",
         "source": config.SOURCE_LLM},
    ]


def make_profile():
    return {
        "root": "/tmp/my-agent", "agent_slug": "my-agent",
        "project_id": "code_scanner",   # 优先于 agent_slug，作为命名前缀
        "tier": "A",
        "tier_reason": "", "tier_downgraded": False,
        "capabilities": [{"id": "C01", "name": "命中", "desc": "d"}],
        "tools": {"allow": ["Read"], "deny": []}, "constraints": {},
        "boundaries": {}, "gwt_baseline": {"entries": [{"index": 1}, {"index": 4},
                                                       {"index": 6}]},
        "engine": {"source_file": "e.py", "source_bytes": 10,
                   "cli_args": ["target"], "exit_codes": [0, 1]},
        "demo_code": None, "rules": [], "structure_index": {},
        "excluded": [{"path": ".cosight/hooks/hooks.json", "bytes": 49687,
                      "reason": "框架样板"}],
        "warnings": [],
    }


# ============================== 输出目录 ==============================

def make_run(tmp_path, stamp="20260101-120000"):
    """构造标准 run 目录布局，返回 (run 目录, 中间态目录)。

    run 目录的原样使用由 generate.py 保证；这里只需按约定摆好目录与记录。
    """
    run_dir = tmp_path / "outputs" / f"{config.RUN_DIR_PREFIX}-{stamp}"
    work = run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME
    work.mkdir(parents=True)
    write_json(work / "run-args.json",
               {"agent": "./agent", "count": 4, "input": "",
                "stamp": stamp, "out_dir": str(run_dir)})
    return run_dir, work


def test_resolve_output_dir_is_artifacts_dir_under_run_dir(tmp_path):
    run_dir, work = make_run(tmp_path)
    out = emit.resolve_output_dir(work)
    assert out == run_dir / config.ARTIFACT_DIRNAME
    assert out.is_dir()


def test_resolve_output_dir_requires_out_dir_record(tmp_path):
    """产出位置只来自 S0 的解析结果；没有记录就报错，不猜。"""
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(SystemExit) as exc:
        emit.resolve_output_dir(work)
    assert exc.value.code == 1


def test_resolve_output_dir_is_idempotent(tmp_path):
    """不做避让：同一个 run 目录解析出来永远是同一处。"""
    _, work = make_run(tmp_path)
    assert emit.resolve_output_dir(work) == emit.resolve_output_dir(work)


def test_run_dir_default_is_cwd_relative():
    """默认 run 目录是相对 cwd 的 outputs/e2e-test-<时间戳>。"""
    assert config.RUN_PARENT_DIR.parts == ("outputs",)
    assert config.RUN_DIR_PREFIX == "e2e-test"
    assert config.ARTIFACT_DIRNAME == "generated_datasets"


# ============================== 覆盖矩阵 ==============================

def test_build_coverage_splits_by_source():
    records = make_records()
    coverage = emit.build_coverage(records, make_plan(), make_profile())
    row = next(r for r in coverage["matrix"] if r["dimension"] == "functional")
    assert row["from_gwt"] == 1 and row["from_llm"] == 1
    assert row["actual_total"] == 2


def test_build_coverage_totals_match_records():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    totals = coverage["totals"]
    assert totals["records"] == 4
    assert totals["from_gwt"] + totals["from_llm"] == 4
    assert totals["gwt_available"] == 3
    assert totals["gwt_kept"] == 2
    assert totals["gwt_dropped"] == 1


def test_build_coverage_marks_focused_dimension():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    row = next(r for r in coverage["matrix"] if r["dimension"] == "failure")
    assert row["focused"] is True


def test_build_coverage_covers_all_dimensions_even_when_empty():
    coverage = emit.build_coverage([], make_plan(), make_profile())
    assert len(coverage["matrix"]) == len(config.DIMENSIONS)


# ============================== eval-plan ==============================

def test_build_eval_plan_records_gaps_and_dedup():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    verify_report = {
        "round": 1, "gaps": {"boundary": 1},
        "rejected": [{"source_ref": "x", "errors": ["bad"]}],
        "dropped": [{"source_ref": "y", "dimension": "safety", "reason": "dup"}],
    }
    plan = emit.build_eval_plan(make_records(), make_plan(), make_profile(),
                                verify_report, coverage)
    assert plan["gaps"] == {"boundary": 1}
    assert plan["repair_rounds"] == 1
    assert plan["count_actual"] == 4
    assert plan["count_target"] == 4


# ============================== 报告渲染 ==============================

def test_render_report_puts_gap_warning_at_top():
    """有缺口时告警必须置顶，不能埋在文末。"""
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    text = emit.render_report(
        "task-1", make_records(), make_plan(), make_profile(),
        {"input_path": "./a", "input_kind": "dir", "root": "/tmp/a",
         "anchor_found": True},
        {"gaps": {"boundary": 1}, "round": 2, "rejected": [], "dropped": []},
        coverage, "/tmp/work",
    )
    assert "未达标" in text
    assert text.index("未达标") < text.index("## 一、概览")


def test_render_report_without_gaps_has_no_warning():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    text = emit.render_report(
        "task-1", make_records(), make_plan(), make_profile(),
        {"input_path": "./a", "input_kind": "dir", "root": "/tmp/a",
         "anchor_found": True},
        {"gaps": {}, "round": 0, "rejected": [], "dropped": []},
        coverage, "/tmp/work",
    )
    assert "未达标" not in text
    assert "无缺口" in text


def test_render_report_flags_over_cap_drops():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    text = emit.render_report(
        "task-1", make_records(), make_plan(), make_profile(),
        {"input_path": "./a", "input_kind": "dir", "root": "/tmp/a",
         "anchor_found": True},
        {"gaps": {}, "round": 0, "rejected": [], "dropped": [],
         "over_cap": [{"source_ref": "clarified-agent-requirements.yaml#4",
                       "dimension": "boundary",
                       "source": "gwt",
                       "reason": "超出 --count 上限 4 条"}]},
        coverage, "/tmp/work",
    )
    assert "条数已裁剪到上限" in text
    assert "超出上限丢弃" in text
    assert text.index("条数已裁剪到上限") < text.index("## 一、概览")


def test_build_eval_plan_records_over_cap_drops():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    verify_report = {"round": 0, "gaps": {}, "rejected": [], "dropped": [],
                     "over_cap": [{"source_ref": "x", "dimension": "boundary",
                                   "source": "gwt", "reason": "r"}]}
    plan = emit.build_eval_plan(make_records(), make_plan(), make_profile(),
                                verify_report, coverage)
    assert len(plan["over_cap_dropped"]) == 1


def test_render_report_lists_dropped_gwts():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    text = emit.render_report(
        "task-1", make_records(), make_plan(), make_profile(),
        {"input_path": "./a", "input_kind": "dir", "root": "/tmp/a",
         "anchor_found": True},
        {"gaps": {}, "round": 0, "rejected": [], "dropped": []},
        coverage, "/tmp/work",
    )
    assert "前缀键名" in text


def test_render_report_has_all_six_sections():
    coverage = emit.build_coverage(make_records(), make_plan(), make_profile())
    text = emit.render_report(
        "task-1", make_records(), make_plan(), make_profile(),
        {"input_path": "./a", "input_kind": "dir", "root": "/tmp/a",
         "anchor_found": True},
        {"gaps": {}, "round": 0, "rejected": [], "dropped": []},
        coverage, "/tmp/work",
    )
    for heading in ("一、概览", "二、路径回顾", "三、覆盖矩阵",
                    "四、缺口与丢弃", "五、画像摘要", "六、已排除文件与原因"):
        assert heading in text


def test_render_report_marks_tier_c_downgrade():
    profile = make_profile()
    profile["tier"] = config.TIER_C
    profile["tier_downgraded"] = True
    coverage = emit.build_coverage(make_records(), make_plan(), profile)
    text = emit.render_report(
        "task-1", make_records(), make_plan(), profile,
        {"input_path": "./a", "input_kind": "dir", "root": "/tmp/a",
         "anchor_found": True},
        {"gaps": {}, "round": 0, "rejected": [], "dropped": []},
        coverage, "/tmp/work",
    )
    assert "降级" in text


# ============================== 落盘幂等 ==============================

def make_work(tmp_path, emitted):
    """构造一个可落盘的最小中间态目录。"""
    from common import write_json as wj
    (tmp_path / "40-verified.jsonl").write_text(
        json.dumps({"data_id": "a_f_001", "kind": "seed", "dimension": "functional",
                    "source": "llm", "source_ref": "r", "input": "对目录执行检查",
                    "precondition": "", "expected_output": ["要点足够长"]},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    wj(tmp_path / "12-agent-profile.json", make_profile())
    wj(tmp_path / "20-plan.json", make_plan())
    wj(tmp_path / "00-asset.json", {"input_path": "./a", "input_kind": "dir",
                                    "root": "/tmp/a", "anchor_found": True,
                                    "root_sha256": "x"})
    wj(tmp_path / "41-verify.json", {"round": 0, "gaps": {}, "rejected": [],
                                     "dropped": [], "pending_prompts": []})
    if emitted:
        wj(tmp_path / "50-emitted.json", emitted)


def test_emit_refuses_when_already_emitted(tmp_path, monkeypatch, capsys):
    """emit.py 被指定了确切的中间态目录：已落盘则拒绝，不产出内容相同的副本。

    （重跑请走 generate.py——它会滚到新的 run 目录重走全流程。）
    """
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path)
    artifacts = run_dir / config.ARTIFACT_DIRNAME
    make_work(work, {"task_id": "t", "artifacts_dir": str(artifacts),
                     "emitted_at": "x", "record_count": 1, "has_gaps": False})

    assert emit.main(["--work", str(work)]) == 0
    out = capsys.readouterr().out
    assert "不重复落盘" in out
    assert "generate.py" in out
    assert not (artifacts / config.ARTIFACT_SEED).exists()


def test_emit_guard_returns_nonzero_when_gaps(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path)
    make_work(work, {"task_id": "t",
                     "artifacts_dir": str(run_dir / config.ARTIFACT_DIRNAME),
                     "emitted_at": "x", "record_count": 1, "has_gaps": True})

    assert emit.main(["--work", str(work)]) == 1
    assert "存在缺口" in capsys.readouterr().out


def test_emit_writes_marker_on_first_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, work = make_run(tmp_path)
    make_work(work, None)

    assert emit.main(["--work", str(work)]) == 0
    marker = read_json(work / "50-emitted.json")
    assert marker["record_count"] == 1
    assert marker["has_gaps"] is False
    assert Path(marker["artifacts_dir"]).is_dir()


def test_emit_keeps_work_dir(tmp_path, monkeypatch):
    """落盘后中间态必须保留。"""
    monkeypatch.chdir(tmp_path)
    _, work = make_run(tmp_path)
    make_work(work, None)

    emit.main(["--work", str(work)])
    assert (work / "12-agent-profile.json").is_file()


def test_emit_writes_artifacts_into_generated_datasets(tmp_path, monkeypatch):
    """5 件交付物落在 <run 目录>/generated_datasets/，中间态落在同级 .work/。"""
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path)
    make_work(work, None)

    assert emit.main(["--work", str(work)]) == 0

    artifacts = run_dir / config.ARTIFACT_DIRNAME
    assert sorted(p.name for p in artifacts.iterdir()) == sorted(
        [config.WORK_DIRNAME, config.ARTIFACT_SEED, config.ARTIFACT_PROFILE,
         config.ARTIFACT_PLAN, config.ARTIFACT_MANIFEST, config.ARTIFACT_REPORT])


def test_task_id_is_naming_slug_and_stamp_not_run_dir_name(tmp_path, monkeypatch):
    """task_id 与 run 目录名解耦：run 目录可以是用户显式指定的任意路径。"""
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "my-exp"
    work = run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME
    work.mkdir(parents=True)
    make_work(work, None)
    write_json(work / "run-args.json",
               {"agent": "./agent", "count": 4, "input": "",
                "stamp": "20260101-120000", "out_dir": str(run_dir)})

    assert emit.main(["--work", str(work)]) == 0

    manifest = read_json(run_dir / config.ARTIFACT_DIRNAME /
                         config.ARTIFACT_MANIFEST)
    assert manifest["task_id"] == "code-scanner_20260101-120000"


def test_task_id_prefers_project_id_over_path(tmp_path, monkeypatch):
    """task_id 优先取工程自报的 project_id，而不是路径推导的 agent_slug。"""
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path)
    make_work(work, None)
    profile = read_json(work / "12-agent-profile.json")
    profile["agent_slug"] = "my-agent"          # S0 从路径推导
    profile["project_id"] = "code_scanner"      # 工程自报的规范名，应当胜出
    write_json(work / "12-agent-profile.json", profile)

    assert emit.main(["--work", str(work)]) == 0

    manifest = read_json(run_dir / config.ARTIFACT_DIRNAME /
                         config.ARTIFACT_MANIFEST)
    assert manifest["task_id"] == "code-scanner_20260101-120000"


def test_task_id_falls_back_to_path_when_project_id_missing(tmp_path, monkeypatch):
    """CLAUDE.md 类工程没有元数据表，project_id 为空 → 回退路径推导的 agent_slug。"""
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path)
    make_work(work, None)
    profile = read_json(work / "12-agent-profile.json")
    profile["agent_slug"] = "my-agent"
    profile["project_id"] = ""                  # 无元数据表
    write_json(work / "12-agent-profile.json", profile)

    assert emit.main(["--work", str(work)]) == 0

    manifest = read_json(run_dir / config.ARTIFACT_DIRNAME /
                         config.ARTIFACT_MANIFEST)
    assert manifest["task_id"] == "my-agent_20260101-120000"


def test_task_id_falls_back_when_project_id_slugifies_to_empty(tmp_path, monkeypatch):
    """project_id 只由符号组成时 slugify 得空串 → 不能产出空前缀，回退 agent_slug。"""
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path)
    make_work(work, None)
    profile = read_json(work / "12-agent-profile.json")
    profile["agent_slug"] = "my-agent"
    profile["project_id"] = "***"
    write_json(work / "12-agent-profile.json", profile)

    assert emit.main(["--work", str(work)]) == 0

    manifest = read_json(run_dir / config.ARTIFACT_DIRNAME /
                         config.ARTIFACT_MANIFEST)
    assert manifest["task_id"] == "my-agent_20260101-120000"


def test_task_id_slugifies_unsafe_agent_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path)
    make_work(work, None)
    profile = read_json(work / "12-agent-profile.json")
    profile["agent_slug"] = "My Agent/v2"
    profile["project_id"] = ""
    write_json(work / "12-agent-profile.json", profile)

    assert emit.main(["--work", str(work)]) == 0

    marker = read_json(work / "50-emitted.json")
    assert marker["task_id"] == "my-agent-v2_20260101-120000"


def test_emit_stamp_flag_wins_over_run_args(tmp_path, monkeypatch):
    """generate.py 显式透传的 --stamp 优先于 run-args.json 里的记录。"""
    monkeypatch.chdir(tmp_path)
    _, work = make_run(tmp_path)
    make_work(work, None)
    saved = read_json(work / "run-args.json")
    write_json(work / "run-args.json", {**saved, "stamp": "old"})

    assert emit.main(["--work", str(work), "--stamp", "new"]) == 0

    assert read_json(work / "50-emitted.json")["task_id"] == "code-scanner_new"
