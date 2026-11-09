"""C2 边界校验专项测试 —— advance-wave 防越界。

拿到 waves_total 后必须拒绝 new_wave > waves_total；缺 waves_total 数据时不
fail-closed（与现有 base smoke 兼容），但拿得到时必须 fail-closed。

覆盖：
1. waves_total 在 state 字段里 + new_wave 越界 → fail-closed
2. waves_total 在 waves.yaml 里 + new_wave 越界 → fail-closed
3. waves_total 在 state + new_wave 不越界 → ok
4. 缺 waves_total 数据 → ok（base smoke 兼容）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DAG_RUNTIME_CLI = (
    PLUGIN_ROOT / "skills" / "dag-runtime" / "scripts" / "dag_runtime.py"
)


def _run(planning_dir: Path, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(DAG_RUNTIME_CLI), "--planning-dir", str(planning_dir), *args],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode in (0, 1), f"unexpected rc={proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


def _init(planning_dir: Path, *, waves_total: int | None = None) -> Path:
    """建空 plan 目录；可选在 state 里设 waves_total。"""
    planning_dir.mkdir(parents=True, exist_ok=True)
    if waves_total is not None:
        state_path = planning_dir / "executeState.json"
        state_path.write_text(
            json.dumps({"current_wave": waves_total, "waves_total": waves_total}),
            encoding="utf-8",
        )
    return planning_dir


class TestAdvanceWaveBounds:
    def test_state_waves_total_blocks_overflow(self, tmp_path):
        """state 里 waves_total=2 + current_wave=2 → advance 应 fail-closed。"""
        planning = _init(tmp_path / ".drive" / "plan-001", waves_total=2)
        # current_wave 设到 waves_total
        state_path = planning / "executeState.json"
        state_path.write_text(
            json.dumps({"current_wave": 2, "waves_total": 2}),
            encoding="utf-8",
        )
        result = _run(planning, "advance-wave")
        assert not result["ok"], result
        assert result["reason"] == "invalid_arg"
        assert "已达最大" in result.get("details", {}).get("error", "") or \
               "已达最大" in str(result), result

    def test_waves_yaml_fallback_blocks_overflow(self, tmp_path):
        """state 缺 waves_total 时回退读 waves.yaml；越界仍 fail-closed。"""
        planning = tmp_path / ".drive" / "plan-001"
        planning.mkdir(parents=True)
        # waves.yaml 写 1 wave
        (planning / "waves.yaml").write_text(
            "waves:\n  - name: w1\n    agents: [a]\n", encoding="utf-8"
        )
        # current_wave 设到 1
        (planning / "executeState.json").write_text(
            json.dumps({"current_wave": 1}), encoding="utf-8"
        )
        result = _run(planning, "advance-wave")
        assert not result["ok"], result
        assert result["reason"] == "invalid_arg"

    def test_state_waves_total_allows_within_bounds(self, tmp_path):
        """state waves_total=3 + current_wave=1 → advance 应 ok。"""
        planning = _init(tmp_path / ".drive" / "plan-001")
        state_path = planning / "executeState.json"
        # 显式覆盖 waves_total=3（dag_runtime 自动建 state 时默认 waves_total=1，
        # 必须显式声明更大总数）
        state_path.write_text(
            json.dumps({"current_wave": 1, "waves_total": 3}),
            encoding="utf-8",
        )
        result = _run(planning, "advance-wave")
        assert result["ok"], result

    def test_no_waves_total_allows_advance_base_smoke(self, tmp_path):
        """缺 waves_total 数据时 advance 不报错（与现有 base smoke 兼容）。

        显式覆盖 state 把 waves_total 字段也去掉（dag_runtime 自动建 state
        默认 waves_total=1，会让测试落进 fail-closed 分支不是这个测试的本意）。
        """
        planning = tmp_path / ".drive" / "plan-001"
        planning.mkdir(parents=True)
        (planning / "executeState.json").write_text(
            json.dumps({"current_wave": 0}), encoding="utf-8"
        )
        result = _run(planning, "advance-wave")
        assert result["ok"], result
