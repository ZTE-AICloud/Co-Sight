"""drive/scripts/agents_to_tasks.py 输出格式。

修复 A3：之前输出 envelope `{"ok": true, "data": {"tasks": [...]}}`，但
`topo-sort-from-tasks` 期望裸 JSON 数组 stdin，直接 pipe 必失败。

新行为：成功时输出裸 JSON 数组（与 topo-sort-from-tasks 输入对齐），
失败时仍输出 envelope 到 stderr 让上层判别。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PLUGIN_ROOT / "skills" / "drive" / "scripts" / "agents_to_tasks.py"

sys.path.insert(0, str(SCRIPT.parent))
import agents_to_tasks as a2t  # noqa: E402


def _write_wf(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_outputs_bare_json_array_on_success(tmp_path: Path):
    """成功时 stdout 是裸 JSON 数组，可直接 pipe 给 topo-sort-from-tasks。"""
    wf = _write_wf(
        tmp_path,
        """mode: dag
agents:
  - id: a
    agent: drive:analyzer
    depends_on: []
  - id: b
    agent: drive:executor
    depends_on: [a]
""",
    )
    result = subprocess.run(
        ["python3", str(SCRIPT), "--workflow", str(wf)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list), f"stdout must be JSON array, got {type(parsed).__name__}"
    assert parsed == [
        {"task_id": "a", "depends_on": []},
        {"task_id": "b", "depends_on": ["a"]},
    ]


def test_pipe_to_topo_sort_from_tasks(tmp_path: Path):
    """agents_to_tasks → topo-sort-from-tasks pipe 无需 Python unwrap。"""
    wf = _write_wf(
        tmp_path,
        """mode: dag
agents:
  - id: x
    agent: drive:analyzer
    depends_on: []
  - id: y
    agent: drive:executor
    depends_on: [x]
""",
    )
    pipe = subprocess.Popen(
        ["python3", str(SCRIPT), "--workflow", str(wf)],
        stdout=subprocess.PIPE,
    )
    topo = TOPO_SORT = PLUGIN_ROOT / "skills" / "wave-scheduling" / "scripts" / "topo_sort.py"
    result = subprocess.run(
        ["python3", str(topo), "topo-sort-from-tasks"],
        stdin=pipe.stdout,
        capture_output=True, text=True,
    )
    pipe.stdout.close()
    pipe.wait()
    assert result.returncode == 0, f"pipe failed: {result.stderr}"
    env = json.loads(result.stdout)
    assert env["ok"] is True
    assert "data" in env


def test_outputs_envelope_on_failure(tmp_path: Path):
    """workflow.yaml 不存在时 stderr 输出 envelope，exit 1。"""
    result = subprocess.run(
        ["python3", str(SCRIPT), "--workflow", str(tmp_path / "missing.yaml")],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    # 失败 envelope 走 stderr（不污染 stdout pipe）
    assert "{" in result.stderr
    env = json.loads(result.stderr.strip())
    assert env["ok"] is False
    assert env["reason"] == "file_missing"


def test_load_tasks_returns_list():
    """load_tasks 是纯函数，返回 list of dict。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        wf = Path(td) / "workflow.yaml"
        wf.write_text(
            "mode: dag\nagents:\n  - id: x\n    agent: drive:analyzer\n    depends_on: []\n",
            encoding="utf-8",
        )
        tasks = a2t.load_tasks(wf)
        assert isinstance(tasks, list)
        assert tasks == [{"task_id": "x", "depends_on": []}]