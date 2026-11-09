"""drive/scripts/extract_verdict.py --all-verdict-required 批量模式。

修复 B5：之前只有 --agent-id X 单 agent 模式，多 verdict_required 时
orchestrator 必须循环 subprocess。本测试覆盖 batch 模式 + 与 single 互斥校验。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PLUGIN_ROOT / "skills" / "drive" / "scripts" / "extract_verdict.py"


def _seed_plan(tmp_path: Path, *, report_text: str | None) -> Path:
    """建 .drive/<plan> 骨架 + 可选 evaluation/verification-report.md。"""
    planning = tmp_path / "plan-x"
    planning.mkdir(parents=True)
    state_path = planning / "executeState.json"
    state = {
        "schema_version": "drive.runtime.state.v1",
        "revision": 0,
        "active_agents": [],
        "verdicts": {},
        "updated_at": "2026-09-23T08:00:00+00:00",
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    if report_text is not None:
        (planning / "evaluation").mkdir(exist_ok=True)
        (planning / "evaluation" / "verification-report.md").write_text(report_text, encoding="utf-8")
    return planning


REPORT_OK = "## Verdict: pass\n"


def _read_state(planning: Path) -> dict:
    return json.loads((planning / "executeState.json").read_text(encoding="utf-8"))


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        capture_output=True, text=True,
    )


# ---------- batch mode ----------


def test_batch_writes_verdict_to_all_agents(tmp_path: Path):
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    result = _run([
        "--planning-dir", str(p),
        "--all-verdict-required", '["a", "b", "c"]',
    ])
    assert result.returncode == 0, result.stderr
    state = _read_state(p)
    assert state["verdicts"] == {"a": "pass", "b": "pass", "c": "pass"}


def test_batch_preserves_existing_verdicts(tmp_path: Path):
    """batch 不擦除已写入的 verdict（其他 agent 已先单独写入）。"""
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    state = _read_state(p)
    state["verdicts"]["existing"] = "partial"
    (p / "executeState.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    result = _run([
        "--planning-dir", str(p),
        "--all-verdict-required", '["a"]',
    ])
    assert result.returncode == 0
    state = _read_state(p)
    assert state["verdicts"] == {"existing": "partial", "a": "pass"}


def test_batch_dry_run_does_not_write(tmp_path: Path):
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    result = _run([
        "--planning-dir", str(p),
        "--all-verdict-required", '["a"]',
        "--dry-run",
    ])
    assert result.returncode == 0
    state = _read_state(p)
    assert state["verdicts"] == {}


# ---------- arg validation ----------


def test_mutual_exclusion_fails_when_neither(tmp_path: Path):
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    result = _run(["--planning-dir", str(p)])
    assert result.returncode == 1
    env = json.loads(result.stdout)
    assert env["ok"] is False
    assert "二选一" in env["details"]["error"]


def test_mutual_exclusion_fails_when_both(tmp_path: Path):
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    result = _run([
        "--planning-dir", str(p),
        "--agent-id", "a",
        "--all-verdict-required", '["b"]',
    ])
    assert result.returncode == 1
    env = json.loads(result.stdout)
    assert env["ok"] is False
    assert "二选一" in env["details"]["error"]


def test_batch_rejects_non_json(tmp_path: Path):
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    result = _run([
        "--planning-dir", str(p),
        "--all-verdict-required", "not-json",
    ])
    assert result.returncode == 1


def test_batch_rejects_non_list(tmp_path: Path):
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    result = _run([
        "--planning-dir", str(p),
        "--all-verdict-required", '{"a": 1}',
    ])
    assert result.returncode == 1


# ---------- single mode still works ----------


def test_single_mode_still_works(tmp_path: Path):
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    result = _run(["--planning-dir", str(p), "--agent-id", "solo"])
    assert result.returncode == 0
    state = _read_state(p)
    assert state["verdicts"] == {"solo": "pass"}


def test_single_mode_unchanged_by_batch_change(tmp_path: Path):
    """回归测试：--agent-id 单独调用语义不变。"""
    p = _seed_plan(tmp_path, report_text=REPORT_OK)
    _run(["--planning-dir", str(p), "--agent-id", "first"])
    _run(["--planning-dir", str(p), "--agent-id", "second"])
    state = _read_state(p)
    assert state["verdicts"] == {"first": "pass", "second": "pass"}