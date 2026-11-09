"""topo_sort helper 拓扑排序 + 调度 单元测试。

覆盖:
- Kahn 拓扑排序: 线性 / 菱形 / 多层 / 并行根 / 未知依赖
- 环检测: 直接环 / 间接环 / 自环
- schema 校验: 空 / 缺 task_id / 重复 / depends_on 非 list
- 调度: budget 均摊 / 并行度决策
- 端到端: taskRecord.yaml → waves.yaml + topo-state.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from .conftest import load_agent_script  # noqa: E402

topo_sort = load_agent_script("wave-scheduling", "topo_sort")
cmd_schedule_waves = topo_sort.cmd_schedule_waves
cmd_topo_sort = topo_sort.cmd_topo_sort
run_topo_sort = topo_sort.run_topo_sort


def _t(task_id: str, deps: list[str] | None = None) -> dict:
    return {"task_id": task_id, "depends_on": deps or []}


# =============================================================================
# 拓扑排序 — 正常图
# =============================================================================

def test_topo_linear_chain():
    tasks = [_t("T01"), _t("T02", ["T01"]), _t("T03", ["T02"])]
    env = cmd_topo_sort(tasks)
    assert env.ok
    assert env.data["waves"] == [["T01"], ["T02"], ["T03"]]
    assert env.data["wave_count"] == 3


def test_topo_diamond():
    # T01 -> {T02, T03} -> T04
    tasks = [_t("T01"), _t("T02", ["T01"]), _t("T03", ["T01"]), _t("T04", ["T02", "T03"])]
    env = cmd_topo_sort(tasks)
    assert env.ok
    assert env.data["waves"] == [["T01"], ["T02", "T03"], ["T04"]]
    assert env.data["wave_count"] == 3


def test_topo_multi_layer():
    # 两条独立链在 wave 布局中对齐
    tasks = [
        _t("A"), _t("B"),
        _t("C", ["A"]), _t("D", ["B"]),
        _t("E", ["C", "D"]),
    ]
    env = cmd_topo_sort(tasks)
    assert env.ok
    assert env.data["waves"] == [["A", "B"], ["C", "D"], ["E"]]


def test_topo_all_parallel_roots():
    tasks = [_t("T01"), _t("T02"), _t("T03")]
    env = cmd_topo_sort(tasks)
    assert env.ok
    assert env.data["waves"] == [["T01", "T02", "T03"]]
    assert env.data["wave_count"] == 1


def test_topo_wave_ordering_is_sorted():
    tasks = [_t("T03"), _t("T01"), _t("T02")]
    env = cmd_topo_sort(tasks)
    assert env.ok
    assert env.data["waves"][0] == ["T01", "T02", "T03"]


def test_topo_single_task():
    env = cmd_topo_sort([_t("only")])
    assert env.ok
    assert env.data["waves"] == [["only"]]


def test_topo_unknown_dependency_is_warning_not_error():
    # depends_on 指向不存在的 task → 忽略 + warning，不阻断
    tasks = [_t("T01", ["GHOST"]), _t("T02", ["T01"])]
    env = cmd_topo_sort(tasks)
    assert env.ok
    assert env.data["waves"] == [["T01"], ["T02"]]
    assert any("GHOST" in w for w in env.data["warnings"])


# =============================================================================
# 环检测
# =============================================================================

def test_cycle_direct():
    tasks = [_t("A", ["B"]), _t("B", ["A"])]
    env = cmd_topo_sort(tasks)
    assert not env.ok
    assert env.reason == "schema_invalid"
    assert env.details["cycle_detected"] is True
    assert env.details["cycle_path"][0] == env.details["cycle_path"][-1]
    assert set(env.details["unresolved"]) == {"A", "B"}


def test_cycle_indirect():
    # A -> B -> C -> A
    tasks = [_t("A", ["C"]), _t("B", ["A"]), _t("C", ["B"])]
    env = cmd_topo_sort(tasks)
    assert not env.ok
    assert env.reason == "schema_invalid"
    path = env.details["cycle_path"]
    assert path[0] == path[-1]
    assert set(env.details["unresolved"]) == {"A", "B", "C"}


def test_cycle_self_loop():
    tasks = [_t("A", ["A"])]
    env = cmd_topo_sort(tasks)
    assert not env.ok
    assert env.details["cycle_detected"] is True


def test_cycle_partial_graph_still_reports():
    # 干净的 T01 + 环 {A,B}
    tasks = [_t("T01"), _t("A", ["B"]), _t("B", ["A"])]
    env = cmd_topo_sort(tasks)
    assert not env.ok
    assert set(env.details["unresolved"]) == {"A", "B"}


# =============================================================================
# schema 校验
# =============================================================================

def test_empty_tasks_rejected():
    env = cmd_topo_sort([])
    assert not env.ok
    assert env.reason == "schema_invalid"


def test_missing_task_id_rejected():
    env = cmd_topo_sort([{"depends_on": []}])
    assert not env.ok
    assert env.reason == "schema_invalid"


def test_duplicate_task_id_rejected():
    env = cmd_topo_sort([_t("T01"), _t("T01")])
    assert not env.ok
    assert "重复" in env.details["hint"]


def test_depends_on_not_list_rejected():
    env = cmd_topo_sort([{"task_id": "T01", "depends_on": "T00"}])
    assert not env.ok
    assert env.reason == "schema_invalid"


def test_non_dict_task_rejected():
    env = cmd_topo_sort(["not-a-dict"])
    assert not env.ok
    assert env.reason == "schema_invalid"


# =============================================================================
# 调度 — budget + 并行度
# =============================================================================

def test_schedule_budget_split_even():
    tasks = [_t("T01"), _t("T02"), _t("T03"), _t("T04")]
    env = cmd_schedule_waves(tasks, plan_id="p", budget=200_000)
    assert env.ok
    assert env.data["budget_per_task"] == 50_000


def test_schedule_budget_floor():
    # 极小 budget 触发下限
    tasks = [_t(f"T{i:02d}") for i in range(20)]
    env = cmd_schedule_waves(tasks, budget=10_000)
    assert env.ok
    assert env.data["budget_per_task"] == topo_sort.MIN_TASK_BUDGET


def test_schedule_multi_task_wave_is_parallel():
    # wave 内 > 1 task → parallel=True
    tasks = [_t("T01"), _t("T02"), _t("T03")]
    env = cmd_schedule_waves(tasks, budget=200_000)
    assert env.ok
    assert env.data["waves"][0]["count"] == 3
    assert env.data["waves"][0]["parallel"] is True


def test_schedule_single_task_wave_not_parallel():
    # 纯链 → 每 wave 1 task → parallel=False
    tasks = [_t(f"T{i:02d}", [f"T{i-1:02d}"] if i else []) for i in range(5)]
    env = cmd_schedule_waves(tasks, budget=1_000_000)
    assert env.ok
    assert all(w["count"] == 1 and w["parallel"] is False for w in env.data["waves"])


def test_schedule_mixed_wave_parallelism():
    # wave1: T01 单独 (串行); wave2: T02+T03 (并行)
    tasks = [_t("T01"), _t("T02", ["T01"]), _t("T03", ["T01"])]
    env = cmd_schedule_waves(tasks, budget=200_000)
    assert env.ok
    assert env.data["waves"][0]["parallel"] is False  # 1 task
    assert env.data["waves"][1]["parallel"] is True    # 2 tasks


def test_schedule_propagates_cycle_failure():
    env = cmd_schedule_waves([_t("A", ["B"]), _t("B", ["A"])])
    assert not env.ok
    assert env.reason == "schema_invalid"


def test_schedule_task_shape_matches_spec():
    tasks = [_t("T01"), _t("T02", ["T01"])]
    env = cmd_schedule_waves(tasks, plan_id="plan-x", budget=100_000)
    assert env.ok
    wave2 = env.data["waves"][1]
    assert wave2["wave"] == 2
    assert wave2["count"] == 1
    t02 = wave2["tasks"][0]
    assert t02["task_id"] == "T02"
    assert t02["depends_on"] == ["T01"]
    assert t02["agent_name"] == "drive:executor"
    # 未传 planning_dir 时 plan_dir fallback 为 "plan-unknown"
    assert t02["upstream_artifacts"] == [".drive/plan-unknown/artifacts/T01/"]
    assert "budget" in t02  # per-task budget 字段


def test_schedule_agent_name_from_task_record(tmp_path: Path):
    # agent_name 从 taskRecord 透传，不覆盖用户指定的业务 agent
    # 在 tmp_path/.claude/agents/ 建一个真实 agent 文件，让 _scan_agent_names 找到
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "agents" / "my-biz-agent.md").write_text(
        "---\nname: my-biz-agent\n---\n# test agent\n", encoding="utf-8"
    )
    planning_dir = tmp_path / ".planning"
    planning_dir.mkdir()
    tasks = [
        {"task_id": "T01", "depends_on": [], "agent_name": "my-biz-agent"},
        {"task_id": "T02", "depends_on": ["T01"]},  # 缺省 → drive:executor
    ]
    env = cmd_schedule_waves(tasks, budget=100_000, planning_dir=planning_dir)
    assert env.ok
    assert env.data["waves"][0]["tasks"][0]["agent_name"] == "my-biz-agent"
    assert env.data["waves"][1]["tasks"][0]["agent_name"] == "drive:executor"


def test_schedule_root_task_has_no_upstream_artifacts_key():
    # 无依赖的 task 不带 upstream_artifacts 字段
    env = cmd_schedule_waves([_t("T01")], budget=100_000)
    assert env.ok
    assert "upstream_artifacts" not in env.data["waves"][0]["tasks"][0]


def test_schedule_multi_dep_upstream_artifacts():
    # T03 依赖 T01+T02 → 两条 upstream_artifacts 约定路径
    tasks = [_t("T01"), _t("T02"), _t("T03", ["T01", "T02"])]
    env = cmd_schedule_waves(tasks, budget=100_000)
    assert env.ok
    t03 = env.data["waves"][-1]["tasks"][0]
    # upstream_artifacts 路径格式：.drive/<plan_dir>/artifacts/<task_id>/
    assert t03["upstream_artifacts"] == [
        ".drive/plan-unknown/artifacts/T01/",
        ".drive/plan-unknown/artifacts/T02/",
    ]


# =============================================================================
# 端到端 — 落盘
# =============================================================================

def _write_record(planning_dir: Path, doc) -> None:
    planning_dir.mkdir(parents=True, exist_ok=True)
    (planning_dir / "taskRecord.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_run_topo_sort_writes_outputs(tmp_path: Path):
    _write_record(tmp_path, {
        "plan_id": "plan-20260724-001",
        "tasks": [
            {"task_id": "plan-20260724-001-T01", "depends_on": []},
            {"task_id": "plan-20260724-001-T02", "depends_on": ["plan-20260724-001-T01"]},
            {"task_id": "plan-20260724-001-T03", "depends_on": ["plan-20260724-001-T01"]},
        ],
    })
    env = run_topo_sort(tmp_path, budget=150_000)
    assert env.ok
    assert env.data["plan_id"] == "plan-20260724-001"

    waves = yaml.safe_load((tmp_path / "waves.yaml").read_text(encoding="utf-8"))
    assert waves["plan_id"] == "plan-20260724-001"
    assert waves["total_tasks"] == 3
    assert waves["waves"][0]["wave"] == 1
    assert waves["waves"][1]["count"] == 2

    state = json.loads((tmp_path / "topo-state.json").read_text(encoding="utf-8"))
    assert state["total_tasks"] == 3
    assert state["budget_per_task"] == 50_000
    assert state["budget_allocated"] == 150_000
    assert "generated_at" in state


def test_integration_full_chain_matches_contract_schema(tmp_path: Path):
    """完整链路: taskRecord.yaml → schedule-waves → waves.yaml,
    校验 interface-contracts.md 的 waves.yaml schema 全字段 + wave 分配合理性。"""
    _write_record(tmp_path, {
        "plan_id": "plan-20260724-001",
        "tasks": [
            {"task_id": "plan-20260724-001-T01", "depends_on": [], "agent_name": "drive:executor"},
            {"task_id": "plan-20260724-001-T02", "depends_on": [], "agent_name": "drive:executor"},
            {"task_id": "plan-20260724-001-T03", "depends_on": ["plan-20260724-001-T01"], "agent_name": "drive:executor"},
            {"task_id": "plan-20260724-001-T04", "depends_on": ["plan-20260724-001-T01", "plan-20260724-001-T02"], "agent_name": "drive:executor"},
            {"task_id": "plan-20260724-001-T05", "depends_on": ["plan-20260724-001-T02"], "agent_name": "drive:executor"},
        ],
    })
    env = run_topo_sort(tmp_path, budget=250_000)
    assert env.ok

    waves = yaml.safe_load((tmp_path / "waves.yaml").read_text(encoding="utf-8"))
    # 顶层字段
    assert waves["plan_id"] == "plan-20260724-001"
    assert waves["total_tasks"] == 5
    assert isinstance(waves["waves"], list)

    # wave 分配合理性: 无依赖在 wave 1，有依赖在后续 wave
    wave1_ids = {t["task_id"] for t in waves["waves"][0]["tasks"]}
    assert wave1_ids == {"plan-20260724-001-T01", "plan-20260724-001-T02"}
    later_ids = {t["task_id"] for w in waves["waves"][1:] for t in w["tasks"]}
    assert later_ids == {"plan-20260724-001-T03", "plan-20260724-001-T04", "plan-20260724-001-T05"}

    # 每个 task 条目字段完整（waves.yaml schema）
    for wave in waves["waves"]:
        assert set(wave) >= {"wave", "count", "parallel", "budget_per_task", "tasks"}
        assert wave["count"] == len(wave["tasks"])
        assert isinstance(wave["parallel"], bool)
        for task in wave["tasks"]:
            assert set(task) >= {"task_id", "depends_on", "agent_name"}
            assert task["agent_name"] == "drive:executor"
            if task["depends_on"]:
                assert len(task["upstream_artifacts"]) == len(task["depends_on"])


def test_run_topo_sort_bare_list_record(tmp_path: Path):
    # 顶层裸 list → plan_id 回退目录名
    _write_record(tmp_path, [{"task_id": "T01", "depends_on": []}])
    env = run_topo_sort(tmp_path)
    assert env.ok
    assert env.data["plan_id"] == tmp_path.name


def test_run_topo_sort_missing_file(tmp_path: Path):
    env = run_topo_sort(tmp_path)
    assert not env.ok
    assert env.reason == "file_missing"


def test_run_topo_sort_cycle_no_output(tmp_path: Path):
    _write_record(tmp_path, {
        "plan_id": "p",
        "tasks": [{"task_id": "A", "depends_on": ["B"]}, {"task_id": "B", "depends_on": ["A"]}],
    })
    env = run_topo_sort(tmp_path)
    assert not env.ok
    assert env.reason == "schema_invalid"
    assert not (tmp_path / "waves.yaml").exists()


def test_run_topo_sort_bad_yaml(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "taskRecord.yaml").write_text("key: [unclosed", encoding="utf-8")
    env = run_topo_sort(tmp_path)
    assert not env.ok
    assert env.reason == "schema_invalid"


def test_run_topo_sort_dict_missing_tasks(tmp_path: Path):
    _write_record(tmp_path, {"plan_id": "p"})
    env = run_topo_sort(tmp_path)
    assert not env.ok
    assert env.reason == "schema_invalid"


# =============================================================================
# CLI
# =============================================================================

def test_cli_topo_sort(tmp_path: Path, capsys):
    _write_record(tmp_path, {"plan_id": "p", "tasks": [{"task_id": "T01", "depends_on": []}]})
    with pytest.raises(SystemExit) as exc:
        topo_sort.main(["topo-sort", "--planning-dir", str(tmp_path)])
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True


def test_cli_schedule_waves(tmp_path: Path, capsys):
    _write_record(tmp_path, {"plan_id": "p", "tasks": [{"task_id": "T01", "depends_on": []}]})
    with pytest.raises(SystemExit) as exc:
        topo_sort.main(["schedule-waves", "--planning-dir", str(tmp_path), "--budget", "100000"])
    assert exc.value.code == 0
    assert (tmp_path / "waves.yaml").exists()


def test_cli_rejects_nonpositive_budget(tmp_path: Path, capsys):
    _write_record(tmp_path, {"plan_id": "p", "tasks": [{"task_id": "T01", "depends_on": []}]})
    with pytest.raises(SystemExit) as exc:
        topo_sort.main(["schedule-waves", "--planning-dir", str(tmp_path), "--budget", "0"])
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "invalid_arg"


# =============================================================================
# 加权 budget 分配
# =============================================================================

def _tw(task_id: str, deps: list[str] | None = None, estimated_tokens: int | None = None) -> dict:
    t = {"task_id": task_id, "depends_on": deps or []}
    if estimated_tokens is not None:
        t["estimated_tokens"] = estimated_tokens
    return t


def test_weighted_budget_heavy_task_gets_more():
    """重 task 拿到比轻 task 多的 budget。"""
    tasks = [
        _tw("heavy", estimated_tokens=80_000),
        _tw("light", estimated_tokens=20_000),
    ]
    env = cmd_schedule_waves(tasks, budget=100_000)
    assert env.ok
    assert env.data["weighted"] is True
    budgets = {
        t["task_id"]: t["budget"]
        for w in env.data["waves"]
        for t in w["tasks"]
    }
    assert budgets["heavy"] > budgets["light"]
    assert budgets["heavy"] >= 8_000  # MIN_TASK_BUDGET


def test_weighted_budget_proportional():
    """4:1 比例 → budget 也近似4:1。"""
    tasks = [
        _tw("big", estimated_tokens=40_000),
        _tw("small", estimated_tokens=10_000),
    ]
    env = cmd_schedule_waves(tasks, budget=100_000)
    assert env.ok
    budgets = {
        t["task_id"]: t["budget"]
        for w in env.data["waves"]
        for t in w["tasks"]
    }
    ratio = budgets["big"] / budgets["small"]
    assert 3.5 <= ratio <= 4.5


def test_uniform_budget_when_no_estimates():
    """无 estimated_tokens 时均摊（向后兼容）。"""
    tasks = [_t("T01"), _t("T02"), _t("T03")]
    env = cmd_schedule_waves(tasks, budget=150_000)
    assert env.ok
    assert env.data["weighted"] is False
    budgets = {
        t["task_id"]: t["budget"]
        for w in env.data["waves"]
        for t in w["tasks"]
    }
    assert len(set(budgets.values())) == 1  # 全部相等


def test_partial_estimates_trigger_weighted_mode():
    """部分 task 有 estimated_tokens 就进加权模式（缺失的用默认估算值）。"""
    tasks = [
        _tw("T01", estimated_tokens=50_000),
        _t("T02"),   # 无 estimated_tokens
    ]
    env = cmd_schedule_waves(tasks, budget=100_000)
    assert env.ok
    assert env.data["weighted"] is True


def test_min_budget_floor_respected():
    """加权后也不低于 MIN_TASK_BUDGET。"""
    tasks = [
        _tw("huge", estimated_tokens=99_000),
        _tw("tiny", estimated_tokens=1_000),
    ]
    env = cmd_schedule_waves(tasks, budget=100_000)
    assert env.ok
    budgets = {
        t["task_id"]: t["budget"]
        for w in env.data["waves"]
        for t in w["tasks"]
    }
    assert all(b >= 8_000 for b in budgets.values())


def test_weighted_flag_in_topo_state(tmp_path: Path):
    """topo-state.json 包含 weighted 标志。"""
    _write_record(tmp_path, {
        "plan_id": "p",
        "tasks": [
            {"task_id": "T01", "depends_on": [], "estimated_tokens": 30_000},
            {"task_id": "T02", "depends_on": [], "estimated_tokens": 70_000},
        ],
    })
    env = run_topo_sort(tmp_path, budget=100_000)
    assert env.ok
    state = json.loads((tmp_path / "topo-state.json").read_text())
    assert state["weighted"] is True


def test_artifacts_dir_uses_plan_dir_name(tmp_path: Path):
    """传 planning_dir 时 upstream_artifacts 用 plan_dir 名。"""
    planning_dir = tmp_path / ".drive" / "plan-20260817-1530-add-user-auth"
    planning_dir.mkdir(parents=True)
    tasks = [_t("T01"), _t("T02", ["T01"])]
    env = cmd_schedule_waves(tasks, plan_id="plan-20260817-1530-add-user-auth",
                            planning_dir=planning_dir, budget=100_000)
    assert env.ok
    # 找到 T02 任务
    t02 = None
    for w in env.data["waves"]:
        for t in w["tasks"]:
            if t["task_id"] == "T02":
                t02 = t
    assert t02 is not None
    # upstream_artifacts 应含 plan_dir 名
    assert t02["upstream_artifacts"] == [
        ".drive/plan-20260817-1530-add-user-auth/artifacts/T01/"
    ]


def test_artifacts_dir_for_helper():
    """artifacts_dir_for() 接受 plan_dir 返回完整路径模板。"""
    artifacts_dir_for = topo_sort.artifacts_dir_for
    assert artifacts_dir_for("plan-20260817-1530-foo") == ".drive/plan-20260817-1530-foo/artifacts"
    assert artifacts_dir_for("plan-x") == ".drive/plan-x/artifacts"
