"""inject-input-assets.py 测试（Step 1b 注入器）。

运行: python -m pytest tests/knowledge/test_inject_input_assets.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
INJECTOR = PLUGIN_ROOT / "scripts" / "inject-input-assets.py"
SKILL_REL = Path(".claude") / "skills" / "rag-knowledge-search"
DSH_SKILL_REL = Path("dsh") / "skills" / "rag-knowledge-search"
CLIENT_REL = SKILL_REL / "scripts" / "rag_knowledge_search.py"
DSH_CLIENT_REL = DSH_SKILL_REL / "scripts" / "rag_knowledge_search.py"
WORKFLOW_ID = "RAG_Workflow_780f"


def _workspace(tmp_path: Path):
    out = tmp_path / "out"
    work = tmp_path / "work"
    inputs = tmp_path / "inputs"
    out.mkdir()
    work.mkdir()
    inputs.mkdir()
    return out, work, inputs


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INJECTOR), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _inject(out: Path, work: Path, inputs: Path, *extra: str) -> subprocess.CompletedProcess:
    return _run(
        "--input-dir", str(inputs),
        "--output-dir", str(out),
        "--work-dir", str(work),
        *extra,
    )


def _write_knowledge(inputs: Path, workflow_id: str) -> None:
    (inputs / "knowledge.json").write_text(
        json.dumps({"workflow_id": workflow_id}), encoding="utf-8"
    )


def _manifest(work: Path) -> dict:
    return yaml.safe_load((work / "injected-assets.yaml").read_text(encoding="utf-8"))


def test_first_injection_writes_skill_and_manifest(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)

    completed = _inject(out, work, inputs)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "injected"
    assert result["workflow_id"] == WORKFLOW_ID

    for rel in ("SKILL.md", "scripts/execute.py", "scripts/rag_knowledge_search.py", "scripts/check_env.py"):
        assert (out / SKILL_REL / rel).is_file(), rel

    manifest = _manifest(work)
    assert manifest["status"] == "injected"
    assert manifest["knowledge"]["workflow_id"] == WORKFLOW_ID
    assert manifest["knowledge"]["query_path"] == "/api/co-knowledge/v1/agent/query"
    assert manifest["knowledge"]["relative_dir"] == ".claude/skills/rag-knowledge-search"
    assert manifest["knowledge"]["base_url"] == "http://localhost:4910"
    assert "scope" not in manifest["knowledge"], "Agent API 不再写入已废弃的 scope 字段"
    assert sorted(manifest["knowledge"]["files"]) == sorted(result["files"])
    assert len(manifest["knowledge"]["files"]) >= 4

    client_text = (out / CLIENT_REL).read_text(encoding="utf-8")
    # 注入器保留模板的引号风格, 这里只校验字面量本身
    assert re.search(
        rf"DEFAULT_WORKFLOW_ID\s*=\s*['\"]{re.escape(WORKFLOW_ID)}['\"]", client_text
    )
    assert "OPENPALETTE" not in client_text.upper()
    assert "zae-ragcomponentservice" not in client_text.lower()


def test_second_injection_is_noop(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)
    assert _inject(out, work, inputs).returncode == 0

    completed = _inject(out, work, inputs)

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["status"] == "noop"
    assert result["renames"] == []
    assert not list((out / SKILL_REL).parent.glob("rag-knowledge-search.bak-*"))


def test_changed_workflow_id_backs_up_and_rewrites(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)
    assert _inject(out, work, inputs).returncode == 0

    new_id = "RAG_Workflow_999"
    _write_knowledge(inputs, new_id)
    completed = _inject(out, work, inputs)

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["status"] == "injected"
    assert len(result["renames"]) == 1
    backup = out / SKILL_REL.parent / result["renames"][0]["to"].split("/")[-1]
    assert backup.is_dir()
    assert WORKFLOW_ID in (backup / "scripts" / "rag_knowledge_search.py").read_text(encoding="utf-8")
    assert new_id in (out / CLIENT_REL).read_text(encoding="utf-8")


def test_cli_workflow_id_overrides_knowledge_json(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)

    completed = _inject(out, work, inputs, "--knowledge-workflow-id", "RAG_Workflow_cli1")

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["workflow_id"] == "RAG_Workflow_cli1"
    assert "RAG_Workflow_cli1" in (out / CLIENT_REL).read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_id", ["bad id", "a/b", "x" * 129, "", "../evil"])
def test_invalid_workflow_id_rejected(tmp_path, bad_id):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, bad_id)

    completed = _inject(out, work, inputs)

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "error"
    assert not (out / SKILL_REL).exists()


def test_missing_knowledge_json_rejected(tmp_path):
    out, work, inputs = _workspace(tmp_path)

    completed = _inject(out, work, inputs)

    assert completed.returncode == 2
    assert "knowledge.json" in json.loads(completed.stdout)["error"]


def test_invalid_json_rejected(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    (inputs / "knowledge.json").write_text("{not json", encoding="utf-8")

    completed = _inject(out, work, inputs)

    assert completed.returncode == 2
    assert "JSON" in json.loads(completed.stdout)["error"]


def test_mcp_json_ignored_with_warning(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)
    (inputs / "mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")

    completed = _inject(out, work, inputs)

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert any("mcp.json" in w and "忽略" in w for w in result["warnings"])
    assert not (out / ".mcp.json").exists()
    assert not (work / "mcp.json").exists()


def test_finalize_without_manifest_rejected(tmp_path):
    out, work, inputs = _workspace(tmp_path)

    completed = _inject(out, work, inputs, "--finalize")

    assert completed.returncode == 2
    assert "finalize" in json.loads(completed.stdout)["error"].lower()


def test_finalize_keeps_existing_content(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)
    assert _inject(out, work, inputs).returncode == 0

    completed = _inject(out, work, inputs, "--finalize")

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["status"] == "noop"
    assert _manifest(work)["input_dir"] == str(inputs.resolve())


def test_dsh_platform_injects_under_dsh_skills(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)

    completed = _inject(out, work, inputs, "--target-platform", "dsh")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["target_platform"] == "dsh"
    assert result["skill_dir"] == "dsh/skills/rag-knowledge-search"
    assert (out / DSH_CLIENT_REL).is_file()
    assert not (out / ".claude").exists()

    manifest = _manifest(work)
    assert manifest["target_platform"] == "dsh"
    assert manifest["knowledge"]["relative_dir"] == "dsh/skills/rag-knowledge-search"
    assert all(p.startswith("dsh/skills/rag-knowledge-search/") for p in manifest["knowledge"]["files"])
    assert WORKFLOW_ID in (out / DSH_CLIENT_REL).read_text(encoding="utf-8")


def test_dsh_rewrites_skill_self_paths(tmp_path):
    """skill 文档内的可执行路径必须指向自身落点，且不得残留 .claude/ 引用。"""
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)

    assert _inject(out, work, inputs, "--target-platform", "dsh").returncode == 0

    text = (out / DSH_SKILL_REL / "SKILL.md").read_text(encoding="utf-8")
    assert ".claude/skills/" not in text
    assert "dsh/skills/rag-knowledge-search/scripts/execute.py" in text
    assert "dsh/skills/rag-knowledge-search/scripts/check_env.py" in text


def test_claude_platform_keeps_skill_self_paths(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)

    assert _inject(out, work, inputs).returncode == 0

    text = (out / SKILL_REL / "SKILL.md").read_text(encoding="utf-8")
    assert ".claude/skills/rag-knowledge-search/scripts/execute.py" in text


def test_both_platform_injects_both_roots(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)

    completed = _inject(out, work, inputs, "--target-platform", "both")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["target_platform"] == "both"
    assert result["skill_dirs"] == [
        ".claude/skills/rag-knowledge-search",
        "dsh/skills/rag-knowledge-search",
    ]
    assert (out / CLIENT_REL).is_file()
    assert (out / DSH_CLIENT_REL).is_file()

    manifest = _manifest(work)
    assert manifest["knowledge"]["relative_dirs"] == result["skill_dirs"]
    assert manifest["knowledge"]["relative_dir"] == ".claude/skills/rag-knowledge-search"
    assert any(p.startswith(".claude/skills/rag-knowledge-search/")
               for p in manifest["knowledge"]["files"])
    assert any(p.startswith("dsh/skills/rag-knowledge-search/")
               for p in manifest["knowledge"]["files"])


def test_dsh_backup_moves_outside_skills_root(tmp_path):
    """customSkillDirs 会扫到技能根下的每个子目录——备份不能留在 dsh/skills/ 里。"""
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)
    assert _inject(out, work, inputs, "--target-platform", "dsh").returncode == 0

    _write_knowledge(inputs, "RAG_Workflow_999")
    completed = _inject(out, work, inputs, "--target-platform", "dsh")

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["status"] == "injected"
    assert len(result["renames"]) == 1
    backup = Path(result["renames"][0]["to"])
    assert backup.is_dir()
    assert backup.parent == work / "backups"
    assert list((out / DSH_SKILL_REL.parent).iterdir()) == [out / DSH_SKILL_REL]
    assert "RAG_Workflow_999" in (out / DSH_CLIENT_REL).read_text(encoding="utf-8")


def test_finalize_rejects_platform_switch(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)
    assert _inject(out, work, inputs, "--target-platform", "dsh").returncode == 0

    completed = _inject(out, work, inputs, "--finalize")

    assert completed.returncode == 2
    error = json.loads(completed.stdout)["error"]
    assert "目标平台" in error and "dsh" in error


def test_legacy_manifest_without_platform_defaults_to_claude(tmp_path):
    out, work, inputs = _workspace(tmp_path)
    _write_knowledge(inputs, WORKFLOW_ID)
    assert _inject(out, work, inputs).returncode == 0

    manifest_path = work / "injected-assets.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("target_platform", None)
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")

    completed = _inject(out, work, inputs, "--finalize")

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["target_platform"] == "claude-code"
