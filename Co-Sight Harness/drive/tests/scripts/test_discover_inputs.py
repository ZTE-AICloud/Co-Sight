"""输入发现的 CLI 契约。

SKILL.md 让 agent 用 `python3 discover_inputs.py --work-dir <dir>` 调它。没有
CLI 入口时这条命令静默无输出 —— agent 拿不到结果也收不到错误，只会以为输入
都齐了继续往下走。故 exit code 必须能表达 input_check gate 的判定。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.script_loader import scripts_dir

SCRIPT = scripts_dir("startup") / "discover_inputs.py"


def run(work_dir: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--work-dir", str(work_dir)],
        capture_output=True, text=True,
    )
    assert proc.stdout.strip(), f"无 stdout 输出（stderr: {proc.stderr}）"
    return proc.returncode, json.loads(proc.stdout)


class TestReadyPath:
    def test_proposal_present_exits_zero(self, tmp_path):
        (tmp_path / "proposal.md").write_text("# 需求", encoding="utf-8")
        code, payload = run(tmp_path)
        assert code == 0
        assert payload["ok"] is True

    def test_reports_found_category(self, tmp_path):
        (tmp_path / "proposal.md").write_text("# 需求", encoding="utf-8")
        _, payload = run(tmp_path)
        assert payload["data"]["categories"]["proposal"]["found"] is True
        assert payload["data"]["categories"]["proposal"]["relative_path"] == "proposal.md"

    def test_reports_absent_optional_categories(self, tmp_path):
        (tmp_path / "proposal.md").write_text("# 需求", encoding="utf-8")
        _, payload = run(tmp_path)
        assert payload["data"]["categories"]["knowledge"]["found"] is False

    def test_discovers_workflow_yaml(self, tmp_path):
        (tmp_path / "proposal.md").write_text("# 需求", encoding="utf-8")
        (tmp_path / "workflow.yaml").write_text("phases: []\n", encoding="utf-8")
        _, payload = run(tmp_path)
        assert payload["data"]["categories"]["workflow"]["found"] is True

    def test_readme_is_a_proposal_fallback(self, tmp_path):
        (tmp_path / "README.md").write_text("# 需求", encoding="utf-8")
        code, _ = run(tmp_path)
        assert code == 0


class TestBlockedPath:
    """input_check gate 该拦的情况必须靠 exit code 表达，不能只写在 JSON 里。"""

    def test_missing_proposal_exits_one(self, tmp_path):
        code, payload = run(tmp_path)
        assert code == 1
        assert payload["ok"] is False
        assert payload["reason"] == "inputs_incomplete"

    def test_names_the_missing_requirement(self, tmp_path):
        _, payload = run(tmp_path)
        assert payload["details"]["missing_required"] == ["proposal"]

    def test_hint_tells_user_where_to_put_it(self, tmp_path):
        _, payload = run(tmp_path)
        assert "proposal.md" in payload["details"]["hint"]

    def test_optional_inputs_alone_do_not_satisfy(self, tmp_path):
        (tmp_path / "workflow.yaml").write_text("phases: []\n", encoding="utf-8")
        code, _ = run(tmp_path)
        assert code == 1

    def test_missing_work_dir_exits_one(self, tmp_path):
        code, payload = run(tmp_path / "nope")
        assert code == 1
        assert payload["reason"] == "invalid_arg"


def test_skill_md_command_shape_matches_cli():
    """SKILL.md 里写的调用方式必须与脚本实际支持的参数一致。"""
    body = (SCRIPT.parent.parent / "SKILL.md").read_text(encoding="utf-8")
    assert "discover_inputs.py" in body
    assert "--work-dir" in body
