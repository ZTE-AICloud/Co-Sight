"""tests/agents/test_pack_context.py — pack_context.py 单元测试。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from .conftest import load_agent_script

mod = load_agent_script("context-packaging", "pack_context")
pack_context = mod.pack_context

pytestmark = pytest.mark.unit

SAMPLE_TASKRECORD = """\
plan_id: plan-20260101-001
tasks:
  - task_id: plan-20260101-001-T01
    title: Setup
    description: Setup the project
    agent_name: executor
    execution_mode: code
    depends_on: []
    acceptance_criteria:
      - The project is set up
    files_owned: []
  - task_id: plan-20260101-001-T02
    title: Implement
    description: Implement the feature
    agent_name: executor
    execution_mode: code
    depends_on: [plan-20260101-001-T01]
    acceptance_criteria:
      - The feature is implemented
    files_owned: []
"""

SAMPLE_MANIFEST = (
    "# Manifest\n\ncomplexity: standard\n\n## Requirements\n\n- R1: Setup\n"
)


class TestPackContext:
    def _setup(self, tmp_path: Path) -> Path:
        planning = tmp_path / ".drive" / "plan-test"
        planning.mkdir(parents=True)
        (planning / "taskRecord.yaml").write_text(SAMPLE_TASKRECORD, encoding="utf-8")
        (planning / "manifest.md").write_text(SAMPLE_MANIFEST, encoding="utf-8")
        return planning

    def test_produces_one_pack_per_task(self, tmp_path):
        planning = self._setup(tmp_path)
        result = pack_context(planning)
        assert result["ok"] is True
        assert result["data"]["tasks_packed"] == 2
        assert (planning / "context_pack" / "plan-20260101-001-T01.json").is_file()
        assert (planning / "context_pack" / "plan-20260101-001-T02.json").is_file()

    def test_pack_contains_expected_fields(self, tmp_path):
        planning = self._setup(tmp_path)
        pack_context(planning)
        pack = json.loads(
            (planning / "context_pack" / "plan-20260101-001-T01.json").read_text()
        )
        assert pack["task_id"] == "plan-20260101-001-T01"
        assert pack["taskrecord_digest"].startswith("sha256:")
        assert pack["manifest_digest"].startswith("sha256:")
        assert "generated_at" in pack
        assert pack["depends_on"] == []
        assert pack["upstream_artifact_paths"] == []
        assert pack["task"]["title"] == "Setup"

    def test_depends_on_populates_upstream_paths(self, tmp_path):
        planning = self._setup(tmp_path)
        pack_context(planning)
        pack = json.loads(
            (planning / "context_pack" / "plan-20260101-001-T02.json").read_text()
        )
        assert pack["depends_on"] == ["plan-20260101-001-T01"]
        assert ".drive/<plan_dir>/artifacts/plan-20260101-001-T01/" in pack["upstream_artifact_paths"]

    def test_digest_matches_file_content(self, tmp_path):
        planning = self._setup(tmp_path)
        pack_context(planning)
        pack = json.loads(
            (planning / "context_pack" / "plan-20260101-001-T01.json").read_text()
        )
        expected = "sha256:" + hashlib.sha256(
            (planning / "taskRecord.yaml").read_text(encoding="utf-8").encode()
        ).hexdigest()
        assert pack["taskrecord_digest"] == expected

    def test_missing_taskrecord_fails(self, tmp_path):
        planning = tmp_path / ".drive" / "plan-test"
        planning.mkdir(parents=True)
        (planning / "manifest.md").write_text(SAMPLE_MANIFEST)
        result = pack_context(planning)
        assert result["ok"] is False
        assert result["reason"] == "file_missing"

    def test_missing_manifest_fails(self, tmp_path):
        planning = tmp_path / ".drive" / "plan-test"
        planning.mkdir(parents=True)
        (planning / "taskRecord.yaml").write_text(SAMPLE_TASKRECORD)
        result = pack_context(planning)
        assert result["ok"] is False
        assert result["reason"] == "file_missing"

    def test_invalid_yaml_fails(self, tmp_path):
        planning = tmp_path / ".drive" / "plan-test"
        planning.mkdir(parents=True)
        (planning / "taskRecord.yaml").write_text(": : invalid: :")
        (planning / "manifest.md").write_text(SAMPLE_MANIFEST)
        result = pack_context(planning)
        assert result["ok"] is False
        assert result["reason"] == "schema_invalid"

    def test_missing_tasks_key_fails(self, tmp_path):
        planning = tmp_path / ".drive" / "plan-test"
        planning.mkdir(parents=True)
        (planning / "taskRecord.yaml").write_text("plan_id: test\n")
        (planning / "manifest.md").write_text(SAMPLE_MANIFEST)
        result = pack_context(planning)
        assert result["ok"] is False
        assert result["reason"] == "schema_invalid"

    def test_idempotent_rerun(self, tmp_path):
        """重跑覆盖旧文件，不报错。"""
        planning = self._setup(tmp_path)
        pack_context(planning)
        result = pack_context(planning)
        assert result["ok"] is True
        assert result["data"]["tasks_packed"] == 2
