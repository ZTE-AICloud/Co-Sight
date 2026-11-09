#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_generate.py — 入口调度：步骤判定、续跑幂等、修复轮重跑。"""

import json
import time
from pathlib import Path

import pytest

import config
import generate
from common import write_json


def make_plan(gwt_kept=2, quota=None):
    return {
        "gwt_kept": [{"index": i} for i in range(1, gwt_kept + 1)],
        "quota": quota if quota is not None else {"functional": 1},
        "count": 6,
    }


def seed_plan(work, plan):
    work.mkdir(parents=True, exist_ok=True)
    write_json(work / "20-plan.json", plan)


def seed_asset_and_input(work):
    write_json(work / "00-asset.json", {"root": "/tmp/a"})
    write_json(work / "10-profile-input.json", {})


def seed_profile_with_gwt(work):
    """画像含 GWT 条目——tag 分支只在这时才有意义。"""
    write_json(work / "12-agent-profile.json", {
        "tier": config.TIER_A,
        "gwt_baseline": {"entries": [{"index": 1, "given": "g", "when": "w", "then": "t"}]},
    })


# ============================== 提示词就绪判定 ==============================

def test_prompts_not_ready_without_gwt_prompt(tmp_path):
    plan = make_plan(gwt_kept=2)
    work = tmp_path
    seed_plan(work, plan)
    state = generate.collect_state(work)
    assert generate._prompts_ready(work, plan, state) is False


def test_prompts_ready_when_budget_zero_and_no_gwt(tmp_path):
    """budget=0 且无 GWT：不需要任何提示词，不能反复重跑 prompts.py。"""
    plan = make_plan(gwt_kept=0, quota={d: 0 for d in config.DIMENSION_IDS})
    state = generate.collect_state(tmp_path)
    assert generate._prompts_ready(tmp_path, plan, state) is True


def test_prompts_ready_requires_expected_batch_count(tmp_path):
    plan = make_plan(gwt_kept=0, quota={"functional": 7})
    # 7 条 / BATCH_SIZE 5 => 2 个批次
    (tmp_path / "30-batch-functional-1.prompt.md").write_text("x")
    state = generate.collect_state(tmp_path)
    assert generate._prompts_ready(tmp_path, plan, state) is False

    (tmp_path / "30-batch-functional-2.prompt.md").write_text("x")
    state = generate.collect_state(tmp_path)
    assert generate._prompts_ready(tmp_path, plan, state) is True


def test_zero_quota_dims_expect_no_batches(tmp_path):
    plan = make_plan(gwt_kept=1, quota={"functional": 0, "safety": 0})
    (tmp_path / "30-gwt.prompt.md").write_text("x")
    state = generate.collect_state(tmp_path)
    assert generate._prompts_ready(tmp_path, plan, state) is True


# ============================== 步骤推进 ==============================

def test_step_s0_when_no_asset(tmp_path):
    label, kind, _ = generate.next_step(tmp_path, 5, None, "./agent", "")
    assert kind == "script" and label.startswith("S0")


def test_step_stops_at_llm_when_merge_answer_missing(tmp_path):
    seed_asset_and_input(tmp_path)
    label, kind, payload = generate.next_step(tmp_path, 5, None, "./agent", "")
    assert kind == "llm"
    assert payload[0].name == "11-merge.prompt.md"


def test_plan_step_passes_user_input(tmp_path):
    """--input 必须传给 plan.py，否则用户要求会进不了报告与 manifest。"""
    seed_asset_and_input(tmp_path)
    write_json(tmp_path / "11-merge.answer.json", {})
    seed_profile_with_gwt(tmp_path)

    # plan 尚未生成
    _, kind, payload = generate.next_step(
        tmp_path, 10, {"gwt_kept": []}, "./agent", "重点覆盖失败路径"
    )
    # S2 已拆两步：先 tag.py 出归类提示词，再 plan.py 算配额
    assert kind == "script"
    script, extra = payload[0]
    assert script == "tag.py"
    assert extra[extra.index("--input") + 1] == "重点覆盖失败路径"


def test_tag_step_then_llm_then_plan(tmp_path):
    """归类提示词产出后停在 LLM，填完答案才轮到 plan.py。"""
    seed_asset_and_input(tmp_path)
    write_json(tmp_path / "11-merge.answer.json", {})
    seed_profile_with_gwt(tmp_path)

    pending = {"gwt_kept": []}   # plan 未生成

    # 尚无归类提示词 → 先跑 tag.py
    label, kind, payload = generate.next_step(tmp_path, 10, pending, "./agent", "")
    assert kind == "script" and payload[0][0] == "tag.py"

    # 提示词已产出但答案未填 → 停在 LLM
    (tmp_path / "20-tag.prompt.md").write_text("prompt")
    label, kind, payload = generate.next_step(tmp_path, 10, pending, "./agent", "")
    assert kind == "llm"
    assert payload[0].name == "20-tag.prompt.md"

    # 答案填好 → 轮到 plan.py
    write_json(tmp_path / "20-tag.answer.json", {"gwt_tags": [], "focus": []})
    label, kind, payload = generate.next_step(tmp_path, 10, pending, "./agent", "")
    assert kind == "script" and payload[0][0] == "plan.py"


def test_plan_step_receives_user_input_for_traceability(tmp_path):
    """--input 必须传给 plan.py 以写入 plan.json/报告/manifest。"""
    seed_asset_and_input(tmp_path)
    write_json(tmp_path / "11-merge.answer.json", {})
    write_json(tmp_path / "12-agent-profile.json", {})
    (tmp_path / "20-tag.prompt.md").write_text("p")
    write_json(tmp_path / "20-tag.answer.json", {"gwt_tags": [], "focus": []})

    _, kind, payload = generate.next_step(
        tmp_path, 10, None, "./agent", "重点覆盖失败路径"
    )
    script, extra = payload[0]
    assert script == "plan.py"
    assert extra[extra.index("--input") + 1] == "重点覆盖失败路径"


def test_emit_is_last_step(tmp_path):
    seed_asset_and_input(tmp_path)
    for name in ("11-merge.answer.json", "12-agent-profile.json"):
        write_json(tmp_path / name, {})
    seed_plan(tmp_path, make_plan(gwt_kept=0, quota={}))
    (tmp_path / "40-verified.jsonl").write_text('{"a":1}\n')
    (tmp_path / "30-gwt.answer.json").write_text("{}")

    _, kind, payload = generate.next_step(tmp_path, 6, make_plan(gwt_kept=0, quota={}),
                                          "./agent", "")
    assert kind == "script" and payload[0][0] == "emit.py"


# ============================== 修复轮重跑判定 ==============================

def test_needs_reverify_when_repair_answer_is_newer(tmp_path):
    """补生成答案晚于上次校验 → 必须重跑 verify.py。"""
    write_json(tmp_path / "41-verify.json", {"gaps": {"failure": 1}, "round": 1})
    time.sleep(0.01)
    (tmp_path / "31-repair-failure-r1-1.prompt.md").write_text("x")
    (tmp_path / "31-repair-failure-r1-1.answer.json").write_text("{}")

    state = generate.collect_state(tmp_path)
    assert generate._needs_reverify(tmp_path, state) is True


def test_no_reverify_when_no_repair_answers(tmp_path):
    write_json(tmp_path / "41-verify.json", {"gaps": {"failure": 1}, "round": 1})
    (tmp_path / "31-repair-failure-r1-1.prompt.md").write_text("x")
    state = generate.collect_state(tmp_path)
    assert generate._needs_reverify(tmp_path, state) is False


def test_no_reverify_when_no_gaps(tmp_path):
    write_json(tmp_path / "41-verify.json", {"gaps": {}, "round": 0})
    (tmp_path / "31-repair-failure-r1-1.answer.json").write_text("{}")
    state = generate.collect_state(tmp_path)
    assert generate._needs_reverify(tmp_path, state) is False


def test_no_reverify_when_repair_rounds_exhausted(tmp_path):
    """补生成轮次用尽后不再重跑，交由 emit 落盘并退出码 1。"""
    write_json(tmp_path / "41-verify.json",
               {"gaps": {"failure": 1}, "round": config.MAX_REPAIR_ROUNDS})
    time.sleep(0.01)
    (tmp_path / "31-repair-failure-r2-1.answer.json").write_text("{}")
    state = generate.collect_state(tmp_path)
    assert generate._needs_reverify(tmp_path, state) is False


# ============================== 参数续跑 ==============================

def make_run(tmp_path, run_name="run", stamp="20260101-120000", agent="./agent"):
    """摆好一个可续跑的 run 目录，返回 (run 目录, 中间态目录)。"""
    run_dir = tmp_path / run_name if "/" not in run_name else Path(run_name)
    work = run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME
    work.mkdir(parents=True, exist_ok=True)
    write_json(work / "run-args.json", {
        "agent": agent, "count": 5, "input": "",
        "stamp": stamp, "out_dir": str(run_dir),
    })
    return run_dir, work


def test_run_args_persist_agent_count_and_input(tmp_path, monkeypatch):
    """首次运行应把参数落到中间态目录的 run-args.json，供续跑复用。"""
    monkeypatch.setattr(generate, "stamp_now", lambda: "20260101-120000")
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "outputs" / f"{config.RUN_DIR_PREFIX}-20260101-120000"
    work = run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME

    generate.main(["--agent", "./agent", "--count", "7", "--input", "要求"])
    saved = json.loads((work / "run-args.json").read_text())

    assert saved == {"agent": "./agent", "count": 7, "input": "要求",
                     "stamp": "20260101-120000", "out_dir": str(run_dir)}


def test_resume_reuses_saved_args(tmp_path):
    _, work = make_run(tmp_path, agent="./agent")
    write_json(work / "00-asset.json", {"root": "/tmp/a"})
    write_json(work / "10-profile-input.json", {})

    # 不传 --agent / --count / --input，应回落到存档值
    rc = generate.main(["--work", str(work)])
    assert rc == 0


def test_resume_without_out_dir_record_fails(tmp_path):
    """旧中间态/手工目录没有 out_dir：无法确定产出位置，报错不猜。"""
    work = tmp_path / "w"
    work.mkdir()
    write_json(work / "run-args.json", {"agent": "./agent", "count": 5})
    write_json(work / "00-asset.json", {"root": "/tmp/a"})
    write_json(work / "10-profile-input.json", {})

    with pytest.raises(SystemExit) as exc:
        generate.main(["--work", str(work)])
    assert exc.value.code == 1


def test_resume_without_agent_anywhere_fails(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    try:
        generate.main(["--work", str(work)])
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("应当以退出码 1 结束")


# ============================== --output 与 --work 一致性 ==============================

def test_output_and_work_agreeing_is_accepted(tmp_path):
    run_dir, work = make_run(tmp_path, run_name="exp")
    write_json(work / "00-asset.json", {"root": "/tmp/a"})
    write_json(work / "10-profile-input.json", {})

    rc = generate.main(["--work", str(work), "--output", str(run_dir)])
    assert rc == 0


def test_output_and_work_disagreeing_fails(tmp_path):
    _, work = make_run(tmp_path, run_name="exp")
    with pytest.raises(SystemExit) as exc:
        generate.main(["--work", str(work), "--output", str(tmp_path / "other")])
    assert exc.value.code == 1


# ============================== run 目录解析 ==============================

def test_resolve_run_dir_defaults_to_prefixed_timestamp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = generate.resolve_run_dir(None, "20260101-120000")
    assert run_dir == (tmp_path / "outputs" /
                       "e2e-test-20260101-120000").resolve()


def test_resolve_run_dir_uses_explicit_output_verbatim(tmp_path):
    """显式传入的 --output 原样使用，不拼前缀、不改名、不避让。"""
    run_dir = generate.resolve_run_dir("./my-exp", "20260101-120000")
    assert run_dir == Path("./my-exp").resolve()


def test_work_dir_of_and_run_dir_of_round_trip(tmp_path):
    run_dir = tmp_path / "exp"
    work = generate.work_dir_of(run_dir)
    assert work == run_dir / "generated_datasets" / ".work"
    assert generate.run_dir_of(work) == run_dir.resolve()


# ============================== 已落盘后重跑 ==============================

def mark_emitted(work, task_id="t"):
    write_json(work / "50-emitted.json", {
        "task_id": task_id, "artifacts_dir": "/tmp/out", "emitted_at": "x",
        "record_count": 3, "has_gaps": False,
    })


def test_collect_state_reads_emitted_marker(tmp_path):
    assert generate.collect_state(tmp_path)["emitted"] is None
    mark_emitted(tmp_path)
    assert generate.collect_state(tmp_path)["emitted"]["task_id"] == "t"


def test_guard_rejects_when_progress_exists(tmp_path, capsys):
    run_dir, work = make_run(tmp_path, run_name="exp")
    write_json(work / "00-asset.json", {"root": "/tmp/a"})

    with pytest.raises(SystemExit) as exc:
        generate.guard_run_dir(work, "./agent", 5, "")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "已有未完成的进度" in err
    # 报错里必须给出两条可复制的出路
    assert f"--work {work}" in err
    assert "rm -rf" in err


def test_guard_reports_emitted_run_specifically(tmp_path, capsys):
    run_dir, work = make_run(tmp_path, run_name="exp")
    mark_emitted(work)

    with pytest.raises(SystemExit) as exc:
        generate.guard_run_dir(work, "./agent", 5, "")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "已跑完" in err
    assert "落盘于 x" in err


def test_guard_allows_empty_work_dir(tmp_path):
    """S0 建完就崩留下的空壳：.work 里没有文件，可以重跑。"""
    work = tmp_path / "exp" / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME
    work.mkdir(parents=True)
    generate.guard_run_dir(work, "./agent", 5, "")   # 不抛即通过


def test_guard_allows_missing_work_dir(tmp_path):
    work = tmp_path / "exp" / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME
    generate.guard_run_dir(work, "./agent", 5, "")   # 不抛即通过


def test_emit_step_carries_work_dir_stamp(tmp_path):
    """S5 把本轮时间戳透传给 emit.py，task_id 才能沿用同一份推导。"""
    seed_asset_and_input(tmp_path)
    for name in ("11-merge.answer.json", "12-agent-profile.json"):
        write_json(tmp_path / name, {})
    seed_plan(tmp_path, make_plan(gwt_kept=0, quota={}))
    (tmp_path / "40-verified.jsonl").write_text('{"a":1}\n')
    (tmp_path / "30-gwt.answer.json").write_text("{}")
    write_json(tmp_path / "run-args.json",
               {"agent": "./agent", "count": 6, "input": "", "stamp": "T"})

    _, kind, payload = generate.next_step(tmp_path, 6, make_plan(gwt_kept=0, quota={}),
                                          "./agent", "")
    assert kind == "script"
    script, extra = payload[0]
    assert script == "emit.py"
    assert extra == ["--stamp", "T"]


def test_emit_step_without_stamp_passes_nothing(tmp_path):
    """老中间态没有 stamp 字段：不带参数，emit.py 自行回退。"""
    seed_asset_and_input(tmp_path)
    for name in ("11-merge.answer.json", "12-agent-profile.json"):
        write_json(tmp_path / name, {})
    seed_plan(tmp_path, make_plan(gwt_kept=0, quota={}))
    (tmp_path / "40-verified.jsonl").write_text('{"a":1}\n')
    (tmp_path / "30-gwt.answer.json").write_text("{}")

    _, _, payload = generate.next_step(tmp_path, 6, make_plan(gwt_kept=0, quota={}),
                                       "./agent", "")
    assert payload[0][1] == []


@pytest.fixture
def tiny_agent(tmp_path):
    """最小可跑通 S0 的 agent 目录（main 会真的执行 parse.py）。"""
    root = tmp_path / "tiny"
    root.mkdir()
    (root / "COSIGHT.md").write_text("# tiny\n\n## 定位\n\n最小工程。\n",
                                     encoding="utf-8")
    return root


def run_dirs(root):
    """列出 outputs/ 下的 run 目录名。"""
    out_root = root / "outputs"
    if not out_root.is_dir():
        return []
    return sorted(p.name for p in out_root.iterdir() if p.is_dir())


def test_new_round_creates_prefixed_run_dir(tmp_path, monkeypatch, capsys,
                                            tiny_agent):
    """带 --agent = 开新一轮：新建 <前缀>-<时间戳> 的 run 目录。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generate, "stamp_now", lambda: "20260101-120000")

    assert generate.main(["--agent", str(tiny_agent), "--count", "5"]) == 0

    assert run_dirs(tmp_path) == ["e2e-test-20260101-120000"]
    run_dir = tmp_path / "outputs" / "e2e-test-20260101-120000"
    assert (run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME /
            "00-asset.json").is_file()
    # 产出位置记进 run-args.json，续跑与 emit 都靠它
    saved = json.loads((run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME /
                        "run-args.json").read_text())
    assert saved["out_dir"] == str(run_dir)


def test_explicit_output_is_used_verbatim(tmp_path, monkeypatch, tiny_agent):
    """显式 --output 原样使用：不拼前缀、不加时间戳、不吃 cwd。"""
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "my-exp"

    assert generate.main(["--agent", str(tiny_agent), "--output",
                          str(run_dir)]) == 0

    assert run_dirs(tmp_path) == []          # outputs/ 下什么都没建
    assert (run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME /
            "00-asset.json").is_file()


def test_new_round_refuses_when_run_dir_has_progress(tmp_path, monkeypatch,
                                                     capsys, tiny_agent):
    """同一 run 目录再开一轮：拒绝，而不是静默覆盖。"""
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "my-exp"
    assert generate.main(["--agent", str(tiny_agent), "--output",
                          str(run_dir)]) == 0
    work = run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        generate.main(["--agent", str(tiny_agent), "--output", str(run_dir)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "已有未完成的进度" in err
    assert f"--work {work}" in err


def test_new_round_empty_work_dir_is_retried(tmp_path, monkeypatch, tiny_agent):
    """S0 建完就崩留下的空壳：可以原地重跑。"""
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "my-exp"
    (run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME).mkdir(parents=True)

    assert generate.main(["--agent", str(tiny_agent), "--output",
                          str(run_dir)]) == 0
    assert (run_dir / config.ARTIFACT_DIRNAME / config.WORK_DIRNAME /
            "00-asset.json").is_file()


def test_resume_with_work_keeps_partial_state(tmp_path, monkeypatch, tiny_agent):
    """带 --work 是同一轮续跑：已填答案必须保留，否则永远走不完。"""
    monkeypatch.chdir(tmp_path)
    run_dir, work = make_run(tmp_path, run_name="exp", agent=str(tiny_agent))
    write_json(work / "11-merge.answer.json",
               {"capabilities": [{"id": "C01", "name": "检查", "desc": "d"}]})
    write_json(work / "00-asset.json", {"root": str(tiny_agent),
                                        "agent_slug": "tiny"})
    write_json(work / "10-profile-input.json", {"root": str(tiny_agent)})

    generate.main(["--work", str(work)])

    # 答案仍在原位，也没有滚到新的 run 目录
    assert (work / "11-merge.answer.json").is_file()
    assert not (tmp_path / "outputs").exists()


def test_resume_inherits_saved_args(tmp_path, tiny_agent):
    """续跑沿用首轮记录在 run-args.json 里的参数。"""
    _, work = make_run(tmp_path, run_name="exp", agent=str(tiny_agent))
    write_json(work / "run-args.json", {
        "agent": str(tiny_agent), "count": 5, "input": "原要求",
        "stamp": "20260101-120000", "out_dir": str(tmp_path / "exp"),
    })

    generate.main(["--work", str(work)])
    saved = json.loads((work / "run-args.json").read_text(encoding="utf-8"))
    assert saved["input"] == "原要求"
